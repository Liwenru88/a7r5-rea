/* 修改版4.06旧包装器的等价紧凑布局及五个常驻生命周期门。
 * 固定BEF838..BEF9C8；仅使用同次构建生成的目标与已校验原CP切片。 */
#include "native_capture_constants.h"
#ifndef AF_CAPTURE_PHASE_ENTRY
#error "缺少同次构建的Capture常驻phase地址"
#endif
#ifndef AF_CAPTURE_PRESERVED_NATIVE_BIN
#error "缺少已校验原CP的constructor切片"
#endif
#ifndef AF_CAPTURE_PRESERVED_CALL_BIN
#error "缺少已校验原CP的参数及cleanup切片"
#endif
.syntax unified
.arch armv7-a
.arch_extension idiv
.thumb
.section .text.capture_factor,"ax",%progbits
.global capture_factor_base
capture_factor_base:
.set .Lcapture_phase,capture_factor_base+(AF_CAPTURE_PHASE_ENTRY-0x00bef838)
.set .Lcapture_payload_literal,capture_factor_base+(AF_CAPTURE_PAYLOAD_LITERAL-0x00bef838)
.set .Lcapture_full_continue,capture_factor_base+(0x00aa81ce-0x00bef838)
.set .Lcapture_partial_continue,capture_factor_base+(0x00aa868c-0x00bef838)
.set .Lcapture_partial_invalid,capture_factor_base+(0x00aa86b8-0x00bef838)
/* 由最终链接脚本以绝对ARM地址005F51BC绑定，不能在Thumb汇编中定义成Thumb函数。 */
.extern capture_original_memcpy
.set .Lgamma_arguments,capture_factor_base+0x176
.set .Lgamma_native,capture_factor_base+0x84
.set .Lreturn_identity,capture_factor_base+0x180
.global gamma_full_native
.thumb_func
gamma_full_native:
 push {r4,r5,r6,r7,lr}
 add r7,sp,#12
 b.w .Lcapture_full_continue
.org 8
.global gamma_partial_native
.thumb_func
gamma_partial_native:
 cmp r0,#0
 beq .Lpartial_invalid
 cmp r1,#0
 beq .Lpartial_invalid
 b.w .Lcapture_partial_continue
.Lpartial_invalid:
 b.w .Lcapture_partial_invalid
.org 0x18
.global joint_gamma_full
.thumb_func
joint_gamma_full:
 push {r4,r5,r6,lr}
 mov r4,r0
 mov r5,r1
.global full_original_call
full_original_call:
 bl gamma_full_native
 ldr r6,[r4,#16]
 b.n .Lroute
 nop
.org 0x28
.global joint_gamma_partial
.thumb_func
joint_gamma_partial:
 push {r4,r5,r6,lr}
 mov r4,r0
 mov r5,r1
.global partial_original_call
partial_original_call:
 bl gamma_partial_native
 ldrb r6,[r4]
 cmp r6,#0
 beq .Lroute_done
 ldr r6,[r4,#4]
.Lroute:
 subs r6,#249
 cmp r6,#5
 bhi .Lroute_done
 lsls r6,r6,#1
 /* carry 映射：10→0，0→FFFFFFFF；暂存基准多1，最终恢复原映射。 */
 adds r6,#52
 movs r4,#48
.Lroute_field:
 ldr r0,[r5,r4]
 cmp r0,#10
 beq .Lroute_write
 cbnz r0,.Lroute_next
.Lroute_write:
 sbcs r0,r0
 adds r0,r6
 str r0,[r5,r4]
.Lroute_next:
 adds r4,#4
 cmp r4,#56
 it eq
 addeq r4,#8
 cmp r4,#68
 bne .Lroute_field
.Lroute_done:
 pop {r4,r5,r6,pc}
.global matrix_compact_end
matrix_compact_end:
.global permanent_capture_birth
.thumb_func
permanent_capture_birth:
 push {r0,r1,r2,lr}
 adr.n r0,birth_record
 b.n .Lcapture_phase
.global permanent_capture_restore
.thumb_func
permanent_capture_restore:
 push {r0,r1,r2,lr}
 adr.n r0,restore_record
 b.n .Lcapture_phase
.global permanent_capture_rebuild
.thumb_func
permanent_capture_rebuild:
 push {r0,r1,r2,lr}
 adr.n r0,rebuild_record
 b.n .Lcapture_phase
.balign 4
birth_record:.word AF_CAPTURE_BIRTH_TARGET,0x00ae0317
restore_record:.word AF_CAPTURE_RESTORE_TARGET,0x00833cb5
.org 0x84
.global gamma_native
.thumb_func
gamma_native:
 .incbin AF_CAPTURE_PRESERVED_NATIVE_BIN,0,8
.global gamma_special_selector
.thumb_func
gamma_special_selector:
 ldr.w ip,[sp,#140]
 adr.n r6,.Lreturn_identity
 adds r6,#3
 cmp ip,r6
 bne .Lselector_native
 ldr r1,[sp,#108]
 bx lr
.Lselector_native:
 ldr r1,[r1,r2,lsl #2]
 bx lr
.global permanent_capture_reverse
.thumb_func
permanent_capture_reverse:
 push {r0,r1,r2,lr}
 adr.n r0,reverse_record
 b.n .Lcapture_phase
.org 0xa8
.global joint_gamma
.thumb_func
joint_gamma:
 ldr.w ip,[r1,#48]
 sub.w ip,ip,#51
 cmp.w ip,#11
 bhi .Lgamma_native
 push.w {r4-r11,lr}
 mov r4,r0
 mov r5,r1
 mov r6,r2
 lsr.w r7,ip,#1
 /* 原 pad4 与 record576 合并；活动栈总量和固定 cleanup 不变。 */
 sub.w sp,sp,#580
 /* r8 原值已在固定外层帧保存；此处到原 MOV r8,SP 前均无原读取。 */
 mrs r8,apsr
 ldr r0,[r5,#48]
 movs r1,#28
 muls r0,r1,r0
 ldr.n r1,.Lgamma_table_va
 add r1,r0
 ldrb r2,[r5,#56]
 ldr r1,[r1,r2,lsl #2]
 mov r0,sp
 movw r2,#576
 blx capture_original_memcpy
 ldr.w r0,.Lcapture_payload_literal
 movs r1,#108
 mla r0,r7,r1,r0
 ldrsh.w r9,[r0]
 ldrsh.w r10,[r0,#2]
 ldrsh.w r11,[r0,#4]
 mov r7,sp
 mov.w ip,#129
.Lcurve:
 ldr r0,[r7]
 ldr r1,[sp,#512]
 lsl.w r2,r0,#12
 udiv r1,r2,r1
 rsb.w r2,r1,#4096
 mul r3,r0,r9
 asrs r3,r3,#10
 add.w lr,r0,r3
 mul r3,r0,r10
 asrs r3,r3,#10
 muls r3,r2,r3
 asrs r3,r3,#12
 muls r3,r2,r3
 asrs r3,r3,#12
 add lr,r3
 mul r3,r0,r11
 asrs r3,r3,#10
 muls r3,r1,r3
 asrs r3,r3,#12
 muls r3,r2,r3
 asrs r3,r3,#12
 add lr,r3
 usat lr,#18,lr
 str lr,[r7],#4
 subs.w ip,ip,#1
 bne .Lcurve
 /* USAT 可置 Q；调用原 constructor 前恢复原 Q，原私有 inner 跳过本段。 */
 msr APSR_nzcvq,r8
 ldr r0,[sp,#512]
 str r0,[sp,#544]
 b.n .Lgamma_arguments
.global gamma_compact_end
gamma_compact_end:
.global permanent_capture_gamma
.thumb_func
permanent_capture_gamma:
 push {r0,r1,r2,lr}
 adr.n r0,gamma_record
 b.n .Lcapture_phase
.balign 4
rebuild_record:.word AF_CAPTURE_REBUILD_TARGET,0x00aebdc3
reverse_record:.word AF_CAPTURE_REVERSE_TARGET,0x00845cf5
gamma_record:.word AF_CAPTURE_GAMMA_TARGET,0x00845db9
.org 0x176
.global gamma_original_arguments
.thumb_func
gamma_original_arguments:
 .incbin AF_CAPTURE_PRESERVED_CALL_BIN,0,22
/* 旧 9C4 仅供 guard 二级尾跳，现由 guard 直接尾入 8BC。 */
.Lgamma_table_va:.word 0x01a396d8
.global capture_factor_end
capture_factor_end:
