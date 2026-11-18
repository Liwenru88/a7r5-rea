/* 4.29 guide 控件包装：完整保存/恢复调用者寄存器、NZCV 与 SIMD，避免破坏取景 UI 创建上下文。 */
.text
.global r5_aspect_guide_create_call
.global r5_aspect_guide_body
.global r5_aspect_guide_visibility_gate
.global r5_aspect_stock_cap_a
.global r5_aspect_stock_cap_b
.global r5_aspect_stock_draw
.global r5_aspect_stock_destroy

.macro SAVE_ALL
    sub sp, sp, #0x320
    stp x0, x1, [sp, #0]
    stp x2, x3, [sp, #0x10]
    stp x4, x5, [sp, #0x20]
    stp x6, x7, [sp, #0x30]
    stp x8, x9, [sp, #0x40]
    stp x10, x11, [sp, #0x50]
    stp x12, x13, [sp, #0x60]
    stp x14, x15, [sp, #0x70]
    stp x16, x17, [sp, #0x80]
    stp x18, x19, [sp, #0x90]
    stp x20, x21, [sp, #0xa0]
    stp x22, x23, [sp, #0xb0]
    stp x24, x25, [sp, #0xc0]
    stp x26, x27, [sp, #0xd0]
    stp x28, x29, [sp, #0xe0]
    mrs x9, nzcv
    mrs x10, fpcr
    mrs x11, fpsr
    stp x9, x10, [sp, #0xf0]
    str x11, [sp, #0x100]
    stp q0, q1, [sp, #0x110]
    stp q2, q3, [sp, #0x130]
    stp q4, q5, [sp, #0x150]
    stp q6, q7, [sp, #0x170]
    stp q8, q9, [sp, #0x190]
    stp q10, q11, [sp, #0x1b0]
    stp q12, q13, [sp, #0x1d0]
    stp q14, q15, [sp, #0x1f0]
    stp q16, q17, [sp, #0x210]
    stp q18, q19, [sp, #0x230]
    stp q20, q21, [sp, #0x250]
    stp q22, q23, [sp, #0x270]
    stp q24, q25, [sp, #0x290]
    stp q26, q27, [sp, #0x2b0]
    stp q28, q29, [sp, #0x2d0]
    stp q30, q31, [sp, #0x2f0]
.endm

.macro RESTORE_ALL
    ldp q0, q1, [sp, #0x110]
    ldp q2, q3, [sp, #0x130]
    ldp q4, q5, [sp, #0x150]
    ldp q6, q7, [sp, #0x170]
    ldp q8, q9, [sp, #0x190]
    ldp q10, q11, [sp, #0x1b0]
    ldp q12, q13, [sp, #0x1d0]
    ldp q14, q15, [sp, #0x1f0]
    ldp q16, q17, [sp, #0x210]
    ldp q18, q19, [sp, #0x230]
    ldp q20, q21, [sp, #0x250]
    ldp q22, q23, [sp, #0x270]
    ldp q24, q25, [sp, #0x290]
    ldp q26, q27, [sp, #0x2b0]
    ldp q28, q29, [sp, #0x2d0]
    ldp q30, q31, [sp, #0x2f0]
    ldr x11, [sp, #0x100]
    ldp x9, x10, [sp, #0xf0]
    msr fpsr, x11
    msr fpcr, x10
    msr nzcv, x9
    ldp x0, x1, [sp, #0]
    ldp x2, x3, [sp, #0x10]
    ldp x4, x5, [sp, #0x20]
    ldp x6, x7, [sp, #0x30]
    ldp x8, x9, [sp, #0x40]
    ldp x10, x11, [sp, #0x50]
    ldp x12, x13, [sp, #0x60]
    ldp x14, x15, [sp, #0x70]
    ldp x16, x17, [sp, #0x80]
    ldp x18, x19, [sp, #0x90]
    ldp x20, x21, [sp, #0xa0]
    ldp x22, x23, [sp, #0xb0]
    ldp x24, x25, [sp, #0xc0]
    ldp x26, x27, [sp, #0xd0]
    ldp x28, x29, [sp, #0xe0]
    add sp, sp, #0x320
.endm

r5_aspect_guide_create_call:
    sub sp, sp, #0x20
    stp x0, x5, [sp]
    str x30, [sp, #0x10]
    SAVE_ALL
    bl r5_aspect_guide_before_create
    str w0, [sp, #0x338]
    RESTORE_ALL
    blr x8
    SAVE_ALL
    add x9, sp, #0x320
    ldp x0, x1, [x9]
    ldr w2, [sp, #0x338]
    bl r5_aspect_guide_after_create
    RESTORE_ALL
    ldr x30, [sp, #0x10]
    add sp, sp, #0x20
    ret

r5_aspect_guide_body:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl stock_guide_full_produce
guide_body_return:
    ldp x29, x30, [sp], #16
    ret

r5_aspect_guide_visibility_gate:
    cbz w0, guide_visible
    stp x16, x17, [sp, #-16]!
    sub w16, w0, #1
    cbnz w16, 1f
    ldr x16, [x29, #8]
    adr x17, guide_body_return
    eor x16, x16, x17
    cbnz x16, 1f
    ldp x16, x17, [sp], #16
    b guide_visible
1:
    ldp x16, x17, [sp], #16
    b guide_hidden
guide_visible:
    b stock_guide_visible
guide_hidden:
    b stock_guide_hidden

r5_aspect_stock_cap_a:
    add x0, x0, #0x4f, lsl #12
    b stock_guide_cap_a_resume

r5_aspect_stock_cap_b:
    add x0, x0, #0x47, lsl #12
    b stock_guide_cap_b_resume

r5_aspect_stock_draw:
    stp x29, x30, [sp, #-0x20]!
    b stock_guide_draw_resume

r5_aspect_stock_destroy:
    stp x29, x30, [sp, #-0x20]!
    b stock_guide_destroy_resume
