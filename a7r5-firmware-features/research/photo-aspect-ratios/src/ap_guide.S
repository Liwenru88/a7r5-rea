.text
.global r5_aspect_guide_create_call
.global r5_aspect_guide_body
.global r5_aspect_guide_visibility_gate
.global r5_aspect_stock_cap_a
.global r5_aspect_stock_cap_b
.global r5_aspect_stock_draw
.global r5_aspect_stock_destroy

/* x8 是原虚调用目标，作为第九个参数交给包装器。 */
r5_aspect_guide_create_call:
    stp x8, x30, [sp, #-16]!
    bl r5_aspect_guide_create
    ldp x8, x30, [sp], #16
    ret

r5_aspect_guide_body:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl stock_guide_full_produce
guide_body_return:
    ldp x29, x30, [sp], #16
    ret

/* 只让已登记、原厂纵横比为 3:2 的静态照片控件通过这一次显示判断。 */
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
