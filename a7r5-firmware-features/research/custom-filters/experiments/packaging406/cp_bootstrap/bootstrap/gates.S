/* 原入口参数与原厂尾部均保留，phase非2只走原路径。 */
#include "image_constants.h"
.syntax unified
.thumb
.text
.global af_boot34_start
.type af_boot34_start,%function
.thumb_func
af_boot34_start:
 push {r0,r1}
 ldr r0,phase
 ldr r0,[r0]
 cmp r0,#2
 pop {r0,r1}
 it eq
 ldreq.w pc,start_target
 push {r4,r5,r6,r7,lr}
 add r7,sp,#0xc
 push.w {r8,r9,r10,r11}
 ldr.w pc,start_return
.balign 4
start_target:.word compact_start
start_return:.word 0x495fe1
.size af_boot34_start,.-af_boot34_start

.global af_boot34_hs
.type af_boot34_hs,%function
.thumb_func
af_boot34_hs:
 push {r0,r1}
 ldr r0,phase
 ldr r0,[r0]
 cmp r0,#2
 pop {r0,r1}
 it eq
 ldreq.w pc,hs_target
 movs r0,#0x24
 blx stock_lock_fn
 ldrb r0,[r6]
 ldr lr,hs_lr
 ldr.w pc,hs_return
.balign 4
hs_target:.word compact_hs
hs_lr:.word 0x49604b
hs_return:.word 0x49604d
.size af_boot34_hs,.-af_boot34_hs

.global af_boot34_snapshot
.type af_boot34_snapshot,%function
.thumb_func
af_boot34_snapshot:
 ldr r0,phase
 ldr r0,[r0]
 cmp r0,#2
 beq 3f
 movw r0,#0xb7d0
 movt r0,#0x157
 ldr.w pc,snapshot_return
3:ldr.w pc,snapshot_target
.balign 4
snapshot_return:.word 0x898575
snapshot_target:.word compact_snapshot
.size af_boot34_snapshot,.-af_boot34_snapshot
.global af_boot34_map
.type af_boot34_map,%function
.thumb_func
af_boot34_map:
 ldr r3,phase
 ldr r3,[r3]
 /* phase1与已验证phase2均保留映射；执行跳板仍只允许phase2。 */
 cmp r3,#0
 ite ne
 adrne r2,map
 moveq r2,#0
 str r2,[r0]
 /* 旧尾被链接约束在[800000,1000000)，合法descriptor指针>>23恰为1。 */
 lsrs r2,r2,#23
 str r2,[r1]
 bx lr
.size af_boot34_map,.-af_boot34_map
.balign 4
phase:.word AF_PHASE_ADDRESS
.balign 4
.global af_boot34_descriptor
af_boot34_descriptor:
map:.word 1,15,0x1a3b000,0x1a3c000,0x1a3b000
