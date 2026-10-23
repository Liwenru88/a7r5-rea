/* 隔离 CP 候选：仅替换54～57的矩阵来源，继续执行原厂展开算术。 */
.syntax unified
.arch armv7-a
.thumb
.section .text,"ax"
.global matrix_inline
.thumb_func
matrix_inline:
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
    /* 原函数银行>=32分支逐组连续读12字节；不访问设置银行。 */
    movs r5, #32
    mov.w r11, #0
    movs r6, #0
    str r5, [sp, #4]
    b.w native_matrix_expand
legacy:
    b.w native_matrix_legacy
