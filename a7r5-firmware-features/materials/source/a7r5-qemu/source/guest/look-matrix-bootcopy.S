/* 原CP文件等长：在MMU开启/RTOS初始化前复制矩阵并擦除暂存的BSS零区。 */
.syntax unified
.arch armv7-a
.thumb
.section .text,"ax"
.global matrix_boot_copy
.thumb_func
matrix_boot_copy:
    push {r4-r7,lr}
    sub sp, #4
    ldr r4, =0x011d4000
    ldr r5, =0x01a3a000
    movw r6, #2304
    mov r0, r4
    mov r1, r6
    bl checksum
    ldr r2, =0xc08d9b7e
    cmp r0, r2
    beq copy
    /* 支持暂存区已擦除的重复调用；只接受目标矩阵仍完整的状态。 */
    mov r0, r5
    mov r1, r6
    bl checksum
    ldr r2, =0xc08d9b7e
    cmp r0, r2
    beq done
invalid:
    wfi
    b invalid
copy:
    mov r0, r4
    mov r1, r5
    movw r2, #576
1:
    ldr r3, [r0]
    str r3, [r1], #4
    movs r3, #0
    str r3, [r0], #4
    subs r2, #1
    bne 1b
done:
    /* 重放原厂指令；r4的原值在栈中，恢复全部callee-saved寄存器。 */
    ldr r0, [sp, #4]
    ldr.w r0, [r0, #0x148]
    add sp, #4
    pop {r4-r7,pc}
checksum:
    ldr r2, =0x811c9dc5
    ldr r3, =0x01000193
2:
    ldrb r12, [r0], #1
    eor r2, r2, r12
    mul r2, r3, r2
    subs r1, #1
    bne 2b
    mov r0, r2
    bx lr
.ltorg
