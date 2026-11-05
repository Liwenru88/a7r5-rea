/* 同包原三增量包装器及四个永久phase gate；目标与phase编码由配对构建生成。 */
#include "native_factor_constants.h"
/* 静态候选：保留三个公开入口、原BL位置和原16字节包装帧；不安装。 */
.syntax unified
.thumb
.section .text.factor,"ax",%progbits
.global factor_base
factor_base:
.global factor_matrix
.thumb_func
factor_matrix:
 cmp r3,#0
 bne.n original_matrix
 push {r4,r5,r6,lr}
 mov r4,r0
 movs r5,#0
 mov r6,r2
validate:
 cbz r6,ineligible
 ldr r6,[r6]
 cbz r6,ineligible
 ldrb.w ip,[r6,#1]
 cmp ip,#1
 bhi ineligible
 ldrb.w r6,[r6,#0x2e]
 subs r6,#249
 mov ip,r6
 cmp r6,#5
 bhi ineligible
 b.n eligible
.global factor_validate_end
factor_validate_end:
.global permanent_gamma_source
.thumb_func
permanent_gamma_source:
 push {r0,r1,r2,lr}
 adr.n r0,source_record
 b.n .Lpermanent_phase
.org 0x34
.global factor_matrix_original_call
factor_matrix_original_call:
 bl original_matrix
 b.w add_parameters
ineligible:
 cmp r5,#1
 pop.w {r4,r5,r6,lr}
 /* BEF75A BLO→BEF700；BEF75C BEQ→BEF708，独立静态pin验证。 */
 .hword 0xd3d1
 .hword 0xd0d4
 b.w original_secondary
eligible:
 ldr.w lr,call_base
 mov.w ip,#0x60
 mla lr,r5,ip,lr
 mov ip,r6
 bx lr
.global factor_picker_end
factor_picker_end:
.global permanent_grid
.thumb_func
permanent_grid:
 push {r0,r1,r2,lr}
 adr.n r0,grid_record
 b.n .Lpermanent_phase
.org 0x60
.global factor_primary
.thumb_func
factor_primary:
 cmp r1,#0
 /* 固定BEF77A的16位BNE：PC=BEF77E，目标BEF708，独立解码核对。 */
 .hword 0xd1c5
 push {r4,r5,r6,lr}
 mov r4,r0
 movs r5,#1
 mov r6,r2
 b.n validate
add_parameters:
 ldr r0,payload_base
 movs r1,#0x6c
 mla r6,r6,r1,r0
 movs r3,#27
 cmp r5,#0
 ite eq
 addeq r6,#6
 addne r6,#0x3c
 it ne
 movne r3,#24
 cmp r5,#2
 it eq
 moveq r3,#8
 b.n add_loop
.global factor_parameters_end
factor_parameters_end:
.global permanent_gamma_reset
.thumb_func
permanent_gamma_reset:
 push {r0,r1,r2,lr}
 adr.n r0,reset_record
 b.n .Lpermanent_phase
.org 0x94
.global factor_primary_original_call
factor_primary_original_call:
 bl original_primary
 b.w add_parameters
add_loop:
 ldrh r0,[r4]
 ldrsh r1,[r6],#2
 add r0,r1
 strh r0,[r4],#2
 subs r3,#1
 bne add_loop
 pop {r4,r5,r6,pc}
.global factor_loop_end
factor_loop_end:
.global permanent_primary
.thumb_func
permanent_primary:
 push {r0,r1,r2,lr}
 adr.n r0,primary_record
 b.n .Lpermanent_phase
.balign 4
primary_record:.word native_primary_target,factor_primary
payload_base:.word 0x1a39450
.org 0xc0
.global factor_secondary
.thumb_func
factor_secondary:
 cmp r1,#0
 bne.n original_secondary
 push {r4,r5,r6,lr}
 mov r4,r0
 movs r5,#2
 mov r6,r3
 b.n validate
.global factor_secondary_entry_end
factor_secondary_entry_end:
.global permanent_matrix
.thumb_func
permanent_matrix:
 push {r0,r1,r2,lr}
 adr.n r0,matrix_record
 b.n .Lpermanent_phase
.global permanent_gamma
.thumb_func
permanent_gamma:
 push {r0,r1,r2,lr}
 adr.n r0,gamma_record
 b.n .Lpermanent_phase
.balign 4
matrix_record:.word native_matrix_target,factor_matrix
gamma_record:.word native_gamma_target,0xbef8e1
reset_record:.word native_gamma_reset_target,0xaa6413
.org 0xf4
.global factor_secondary_original_call
factor_secondary_original_call:
 bl original_secondary
 b.w add_parameters
.balign 4
call_base:.word 0xbef74d
.global factor_constants_end
factor_constants_end:
.global permanent_phase
.thumb_func
permanent_phase:
.Lpermanent_phase:
 /* 由最终bootstrap的phase symbol计算，不固定任何旧literal地址。 */
 .hword AF_FACTOR_PHASE_LDR
 ldr r1,[r1]
 cmp r1,#2
 ite eq
 ldreq r1,[r0]
 ldrne r1,[r0,#4]
 /* 只改保存LR的副本；真实LR寄存器始终保持原调用者返回地址。 */
 str r1,[sp,#12]
 pop {r0,r1,r2,pc}
.balign 4
/* 已位于原230F0C scope；phase0必须回旧BEF550 selector，不重放原函数prologue。 */
grid_record:.word native_grid_target,0xbef551
source_record:.word native_gamma_source_target,0xaacb17
.org 0x120
.global factor_end
factor_end:
