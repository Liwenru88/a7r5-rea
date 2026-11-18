/* 所有跳板始终驻留原408B尾；未准备成功只重放原指令。 */
#include "layout_constants.h"
#ifndef AF_CARVE_LAYOUT_PROBE
#include "image_constants.h"
#endif
.syntax unified
.thumb
.section .text.gates,"ax",%progbits
.global af_carve_start
.type af_carve_start,%function
.thumb_func
af_carve_start:
 push {r0,r1}
 ldr r0,phase
 ldr r0,[r0]
 cmp r0,#2
 pop {r0,r1}
 it eq
 ldreq.w pc,start_target
 push {r4,r5,r6,r7,lr}
 add r7,sp,#0xc
 b.w stock_start_return
.balign 4
start_target:.word compact_start
.size af_carve_start,.-af_carve_start
.global af_carve_hs
.type af_carve_hs,%function
.thumb_func
af_carve_hs:
 /* 原496044立即MOVS r0,24；私有返回49606e也立即重写r0，旧r0无消费者。 */
 ldr r0,phase
 ldr r0,[r0]
 cmp r0,#2
 it eq
 ldreq.w pc,hs_target
 movs r0,#0x24
 ldr lr,hs_lr
 ldr.w pc,hs_lock
.balign 4
hs_target:.word compact_hs
hs_lr:.word 0x49604b
hs_lock:.word stock_lock_fn
.size af_carve_hs,.-af_carve_hs
.global af_carve_snapshot
.type af_carve_snapshot,%function
.thumb_func
af_carve_snapshot:
#ifdef AF_CP_CAPTURE_COPIES406
 /* 四处BL提供原LR；phase0直接尾调原ARM memcpy，禁止另造固定返回地址。 */
 ldr r3,phase
 ldr r3,[r3]
 cmp r3,#2
 beq 1f
 ldr.w pc,stock_copy_target
#elif defined(AF_CP_CAPTURE_INPUT406)
 /* 原三参在r0/r1/r2；r3为原memcpy自设scratch，不能拿r0查phase。 */
 ldr r3,phase
 ldr r3,[r3]
 cmp r3,#2
 beq 1f
 blx stock_copy
 /* 复制后的原MOVW/MOVT及原解锁全部回原地址继续。 */
 b.w stock_snapshot_return
#else
 ldr r0,phase
 ldr r0,[r0]
 cmp r0,#2
 beq 1f
 movw r0,#0xb7d0
 b.w stock_snapshot_return
#endif
1:ldr.w pc,snapshot_target
.balign 4
#ifdef AF_CP_CAPTURE_COPIES406
snapshot_target:.word compact_copy
stock_copy_target:.word stock_copy
#else
snapshot_target:.word compact_snapshot
#endif
.size af_carve_snapshot,.-af_carve_snapshot
.global af_carve_map
.type af_carve_map,%function
.thumb_func
af_carve_map:
 ldr r3,phase
 ldr r3,[r3]
 cmp r3,#0
 ite ne
 adrne r2,af_carve_descriptors
 moveq r2,#0
 str r2,[r0]
 /* 原尾地址位于[800000,c00000)，实际descriptor指针>>22恰为2。 */
 lsrs r2,r2,#22
 str r2,[r1]
 bx lr
.size af_carve_map,.-af_carve_map
.balign 4
.global af_carve_descriptors
af_carve_descriptors:
 /* type2显式建立VA→PA；type1只能改已有属性，不能复活fault页。 */
 .word 2,15,AF_CARVE_RX,AF_CARVE_RW,AF_CARVE_RX
 .word 2,12,AF_CARVE_RW,0x2b00000,AF_CARVE_RW
#ifndef AF_CARVE_LAYOUT_PROBE
#include "guard.inc"
#endif
.balign 4
phase:.word 0x1a3ac60
