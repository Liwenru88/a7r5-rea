.text
.global r5_aspect_stock_list
.global r5_aspect_available
.global r5_aspect_size_class
.global r5_aspect_apply
.global r5_aspect_icon
.global r5_aspect_icon_alt

.macro icon_entry name, fallback, first
\name:
    sub w8, w1, #1, lsl #12
    sub w8, w8, #0x600
    cmp w8, #5
    b.hi \fallback
    mov w0, #\first
    movk w0, #0x0200, lsl #16
    add w0, w0, w8, lsl #1
    ret
.endm

icon_entry r5_aspect_icon, prior_icon, 0x1e90
icon_entry r5_aspect_icon_alt, prior_icon_alt, 0x1e91

r5_aspect_stock_list:
    sub sp, sp, #0x830
    b stock_list_resume

r5_aspect_available:
    sub w16, w0, #1, lsl #12
    sub w16, w16, #0x600
    cmp w16, #5
    b.ls 1f
    stp x29, x30, [sp, #-0x20]!
    b stock_available_resume
1:
    mov w0, #1
    ret

r5_aspect_size_class:
    sub w1, w0, #1, lsl #12
    sub w1, w1, #0x600
    cmp w1, #5
    mov w1, #126
    csel w0, w1, w0, ls
    sub w0, w0, #126
    b stock_size_resume

r5_aspect_apply:
    stp x29, x30, [sp, #-0x30]!
    stp x0, x2, [sp, #0x10]
    stp x3, x4, [sp, #0x20]
    mov w0, w1
    bl r5_aspect_project_apply
    mov w1, w0
    ldp x3, x4, [sp, #0x20]
    ldp x0, x2, [sp, #0x10]
    ldp x29, x30, [sp], #0x30
    stp x29, x30, [sp, #-0x20]!
    b stock_apply_resume
