.text
.global r5_aspect_ap_prepare
.global r5_aspect_ap_send

/* 0x70–0x72 是原生三字节局部数组，0x78 起是下一局部对象。 */
.equ wire_in_frame, 0x77

r5_aspect_ap_prepare:
    /* 首条开机配置消息也必须恢复；文件库调用可破坏所有易失寄存器。 */
    stp x16, x17, [sp, #-16]!
    mrs x16, nzcv
    adrp x17, aspect_session
    add x17, x17, :lo12:aspect_session
    ldar w17, [x17]
    cbnz w17, restore_ready
    sub sp, sp, #0x310
    stp x0, x1, [sp]
    stp x2, x3, [sp, #0x10]
    stp x4, x5, [sp, #0x20]
    stp x6, x7, [sp, #0x30]
    stp x8, x9, [sp, #0x40]
    stp x10, x11, [sp, #0x50]
    stp x12, x13, [sp, #0x60]
    stp x14, x15, [sp, #0x70]
    stp x16, x30, [sp, #0x80]
    mrs x9, fpsr
    mrs x10, fpcr
    stp x9, x10, [sp, #0x90]
    str x18, [sp, #0xa0]
    stp q0, q1, [sp, #0x100]
    stp q2, q3, [sp, #0x120]
    stp q4, q5, [sp, #0x140]
    stp q6, q7, [sp, #0x160]
    stp q8, q9, [sp, #0x180]
    stp q10, q11, [sp, #0x1a0]
    stp q12, q13, [sp, #0x1c0]
    stp q14, q15, [sp, #0x1e0]
    stp q16, q17, [sp, #0x200]
    stp q18, q19, [sp, #0x220]
    stp q20, q21, [sp, #0x240]
    stp q22, q23, [sp, #0x260]
    stp q24, q25, [sp, #0x280]
    stp q26, q27, [sp, #0x2a0]
    stp q28, q29, [sp, #0x2c0]
    stp q30, q31, [sp, #0x2e0]
    bl r5_aspect_restore_once
    ldp q0, q1, [sp, #0x100]
    ldp q2, q3, [sp, #0x120]
    ldp q4, q5, [sp, #0x140]
    ldp q6, q7, [sp, #0x160]
    ldp q8, q9, [sp, #0x180]
    ldp q10, q11, [sp, #0x1a0]
    ldp q12, q13, [sp, #0x1c0]
    ldp q14, q15, [sp, #0x1e0]
    ldp q16, q17, [sp, #0x200]
    ldp q18, q19, [sp, #0x220]
    ldp q20, q21, [sp, #0x240]
    ldp q22, q23, [sp, #0x260]
    ldp q24, q25, [sp, #0x280]
    ldp q26, q27, [sp, #0x2a0]
    ldp q28, q29, [sp, #0x2c0]
    ldp q30, q31, [sp, #0x2e0]
    ldp x9, x10, [sp, #0x90]
    msr fpsr, x9
    msr fpcr, x10
    ldp x0, x1, [sp]
    ldp x2, x3, [sp, #0x10]
    ldp x4, x5, [sp, #0x20]
    ldp x6, x7, [sp, #0x30]
    ldp x8, x9, [sp, #0x40]
    ldp x10, x11, [sp, #0x50]
    ldp x12, x13, [sp, #0x60]
    ldp x14, x15, [sp, #0x70]
    ldp x16, x30, [sp, #0x80]
    ldr x18, [sp, #0xa0]
    add sp, sp, #0x310
restore_ready:
    msr nzcv, x16
    ldp x16, x17, [sp], #16
    ldr w1, [x20, #8]
    stp x16, x17, [sp, #-16]!
    mrs x16, nzcv
    cbnz w1, clear_wire
    adrp x17, aspect_selection
    add x17, x17, :lo12:aspect_selection
    ldar w17, [x17]
    and w17, w17, #0xff
    sub w17, w17, #4
    cmp w17, #5
    b.hi clear_wire
    add w17, w17, #0xe0
    b save_wire
clear_wire:
    mov w17, wzr
save_wire:
    strb w17, [x29, #wire_in_frame]
    msr nzcv, x16
    ldp x16, x17, [sp], #16
    ret

r5_aspect_ap_send:
    stp x16, x17, [sp, #-16]!
    mrs x16, nzcv
    ldrb w17, [x29, #wire_in_frame]
    cbz w17, send_native
    mov w17, #0x402d
    cmp w3, w17
    b.ne send_native
    ldrb w17, [x1, #8]
    cmp w17, #2
    b.ne send_native
    ldrb w17, [x29, #wire_in_frame]
    strb w17, [x1, #8]
send_native:
    msr nzcv, x16
    ldp x16, x17, [sp], #16
    b stock_sender
