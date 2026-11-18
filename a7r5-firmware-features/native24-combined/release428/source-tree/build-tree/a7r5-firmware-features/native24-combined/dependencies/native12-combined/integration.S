/* 复用本地已审查的矩阵复制、原厂展开及限定type1声音选择器。 */
.syntax unified
.arch armv7-a
.arch_extension idiv
.thumb

/* 拆开两个段以避开远端108f40..108f8c映射器，不改变校验语义。 */
.section .text.checksum,"ax"
.thumb_func
checksum:
    ldr r2, =0x811c9dc5
    ldr r3, =0x01000193
1:  ldrb r12, [r0], #1
    eor r2, r2, r12
    mul r2, r3, r2
    subs r1, #1
    bne 1b
    mov r0, r2
    bx lr
.ltorg

.section .text.matrix_boot_copy,"ax"
.global matrix_boot_copy
.thumb_func
matrix_boot_copy:
    push {r4-r7,lr}
    sub sp, #4
    ldr r4, =0x011d4000
    ldr r5, =0x01a3a000
    movw r6, #3456
    mov r0, r4
    mov r1, r6
    bl checksum
    ldr r2, =PAYLOAD_FNV
    cmp r0, r2
    beq copy
    mov r0, r5
    mov r1, r6
    bl checksum
    ldr r2, =PAYLOAD_FNV
    cmp r0, r2
    beq done
.global matrix_copy_invalid
matrix_copy_invalid:
    wfi
    b matrix_copy_invalid
copy:
    mov r0, r4
    mov r1, r5
    movw r2, #864
1:  ldr r3, [r0]
    str r3, [r1], #4
    movs r3, #0
    str r3, [r0], #4
    subs r2, #1
    bne 1b
done:
    ldr r0, [sp, #4]
    ldr.w r0, [r0, #0x148]
    add sp, #4
    pop {r4-r7,pc}
.ltorg

.section .text.sound,"ax"
.global combined_sound
.thumb_func
combined_sound:
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

.section .text.matrix,"ax"
.global combined_matrix
.thumb_func
combined_matrix:
    cmp r3, #54
    blo legacy
    cmp r3, #57
    bhi legacy
    cmp r1, #15
    it hi
    movhi r1, #0
    sub.w r3, r3, #54
    movw r2, #576
    mul r3, r2, r3
    movw r10, #0xa000
    movt r10, #0x01a3
    add r10, r3
    movs r2, #36
    mla r10, r1, r2, r10
    movs r5, #32
    mov.w r11, #0
    movs r6, #0
    str r5, [sp, #4]
    b.w native_matrix_expand
legacy:
    b.w native_matrix_legacy
