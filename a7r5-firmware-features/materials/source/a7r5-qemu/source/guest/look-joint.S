/* A7R5逐槽联合参数；执行原厂函数后应用增量，不提供硬件应答。 */
.syntax unified
.arch armv7-a
.arch_extension idiv
.thumb
.section .text,"ax"
.macro addr reg, value
    movw \reg, #:lower16:\value
    movt \reg, #:upper16:\value
.endm
.macro entry name
    .balign 4
    .global \name
    .thumb_func
\name:
.endm
.macro wrapper name, native, ctx, parameter, offset, count
entry \name
    cmp \parameter, #0
    bne 9f
    cmp \ctx, #0
    beq 9f
    ldr ip, [\ctx]
    cmp ip, #0
    beq 9f
    ldrb.w ip, [ip, #1]
    cmp ip, #1
    bhi 9f
    ldr ip, [\ctx]
    ldrb.w ip, [ip, #0x2e]
    sub.w ip, ip, #249
    cmp ip, #5
    bhi 9f
    push {r4-r6,lr}
    mov r4, r0
    mov r5, ip
    bl \native
    addr r6, PARAMS_VA
    movs r0, #108
    mla r6, r5, r0, r6
    adds r6, #\offset
    movs r3, #\count
1:  ldrh r0, [r4]
    ldrsh r1, [r6], #2
    add r0, r1
    strh r0, [r4], #2
    subs r3, #1
    bne 1b
    pop {r4-r6,pc}
9:  b.w \native
.endm

entry matrix_native
    push {r4-r7,lr}
    add r7, sp, #12
    b.w native_matrix_continue
entry primary_native
    push {r4-r7,lr}
    add r7, sp, #12
    b.w native_primary_continue
entry secondary_native
    push {r4-r7,lr}
    add r7, sp, #12
    b.w native_secondary_continue
wrapper joint_matrix, matrix_native, r2, r3, 6, 27
wrapper joint_primary, primary_native, r2, r1, 60, 24
wrapper joint_secondary, secondary_native, r3, r1, 60, 8

entry gamma_full_native
    push {r4-r7,lr}
    add r7, sp, #12
    b.w native_gamma_full_continue
entry gamma_partial_native
    cmp r0, #0
    beq 1f
    cmp r1, #0
    beq 1f
    b.w native_gamma_partial_continue
1:  b.w native_gamma_partial_invalid

/* 原输入不修改，完整和局部路线各保留原生条件。 */
entry joint_gamma_full
    push {r4-r6,lr}
    mov r4, r0
    mov r5, r1
    bl gamma_full_native
    ldr r6, [r4, #0x10]
    b gamma_route
entry joint_gamma_partial
    push {r4-r6,lr}
    mov r4, r0
    mov r5, r1
    bl gamma_partial_native
    ldrb r6, [r4]
    cmp r6, #0
    beq gamma_route_done
    ldr r6, [r4, #4]
gamma_route:
    subs r6, #249
    cmp r6, #5
    bhi gamma_route_done
    lsls r6, #1
    adds r6, #51
    .irp off, 0x30,0x34,0x40
    ldr r0, [r5, #\off]
    cmp r0, #0
    beq 1f
    cmp r0, #10
    bne 2f
    add.w r0, r6, #1
    b 3f
1:  mov r0, r6
3:  str r0, [r5, #\off]
2:
    .endr
gamma_route_done:
    pop {r4-r6,pc}

entry gamma_native
    push {r4-r7,lr}
    add r7, sp, #12
    b.w native_gamma_continue

/* 只在本包装器调用时使用栈上曲线，其他调用读原生表。 */
entry joint_record_primary
    ldr.w ip, [sp, #140]
    addr r6, gamma_after_call + 1
    cmp ip, r6
    bne 1f
    ldr r1, [sp, #108]
    bx lr
1:  ldr.w r1, [r1, r2, lsl #2]
    bx lr
entry joint_gamma
    ldr.w ip, [r1, #0x30]
    sub.w ip, ip, #51
    cmp ip, #11
    bhi 9f
    push {r4-r11,lr}
    sub sp, #4
    mov r4, r0
    mov r5, r1
    mov r6, r2
    lsr.w r7, ip, #1
    sub.w sp, sp, #0x240
    /* 精确保留原始域和曲线列，表中所有原厂指针已保留。 */
    ldr r0, [r5, #0x30]
    movs r1, #28
    mul r0, r1, r0
    addr r1, GAMMA_VA
    add r1, r0
    ldrb r2, [r5, #0x38]
    ldr.w r1, [r1, r2, lsl #2]
    mov r0, sp
    movw r2, #576
1:  ldr r3, [r1], #4
    str r3, [r0], #4
    subs r2, #4
    bne 1b
    addr r0, PARAMS_VA
    movs r1, #108
    mla r0, r7, r1, r0
    ldrsh.w r9, [r0]
    ldrsh.w r10, [r0, #2]
    ldrsh.w r11, [r0, #4]
    mov r7, sp
    mov.w ip, #129
2:  ldr r0, [r7]
    ldr r1, [sp, #0x200]
    lsl.w r2, r0, #12
    udiv r1, r2, r1
    rsb.w r2, r1, #4096
    mul r3, r0, r9
    asrs r3, #10
    add.w lr, r0, r3
    mul r3, r0, r10
    asrs r3, #10
    muls r3, r2, r3
    asrs r3, #12
    muls r3, r2, r3
    asrs r3, #12
    add lr, r3
    mul r3, r0, r11
    asrs r3, #10
    muls r3, r1, r3
    asrs r3, #12
    muls r3, r2, r3
    asrs r3, #12
    add lr, r3
    cmp.w lr, #0
    bge 3f
    mov.w lr, #0
3:  movw r3, #65535
    movt r3, #3
    cmp lr, r3
    bls 4f
    mov lr, r3
4:  str lr, [r7], #4
    subs.w ip, ip, #1
    bne 2b
    ldr r0, [sp, #0x200]
    str r0, [sp, #0x220]
    mov r0, r4
    mov r1, r5
    mov r2, r6
    mov r8, sp
    bl gamma_native
.global gamma_after_call
gamma_after_call:
    add.w sp, sp, #0x240
    add sp, #4
    pop {r4-r11,pc}
9:  b.w gamma_native

/* R5与A7C II不同：type0抑制路径也共用此赋值，必须限定type1。 */
entry joint_sound
    movs r1, #3
    cmp r0, #0
    beq 1f
    movw ip, #0x1618
    ldr.w ip, [r4, ip]
    cmp ip, #1
    it ne
    movne r1, #0
1:  mov.w r0, #0x5b00
    b.w native_sound_store
