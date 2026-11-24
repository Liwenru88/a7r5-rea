/* 只按本张已确认的尺寸显示画幅与像素数，不读取当前拍摄菜单。 */
.text
.balign 4
.global r5_aspect_badge
r5_aspect_badge:
    ldr w8, [x3]
    cbnz w8, badge_native
    ldrb w8, [x3, #0xb80]
    cbz w8, badge_native
    ldrb w8, [x3, #0xf3]
    cbnz w8, badge_raw
    ldrb w8, [x3, #0xf2]
    ldrb w9, [x3, #0xf4]
    orr w8, w8, w9
    cbz w8, badge_native
    ldp w10, w11, [x3, #0xc]
    b badge_dimensions
badge_raw:
    ldp w10, w11, [x3, #0x14]
badge_dimensions:
    ldr w8, [x3, #0xb84]
    ldr w9, [x3, #0xb88]
    cmp w8, w10
    ccmp w9, w11, #0, eq
    b.ne badge_native
    adr x10, badge_pairs
    mov w11, #18
badge_next:
    ldp w12, w13, [x10], #8
    ldr w14, [x10], #4
    cmp w8, w12
    ccmp w9, w13, #0, eq
    b.eq badge_found
    subs w11, w11, #1
    b.ne badge_next
badge_native:
    mov w0, #-1
    b stock_badge_continue
badge_found:
    mov w0, w14
    str w0, [x1, #0x3c]
    ret
.balign 4
badge_pairs:
.include "aspect_badges.inc"

.global r5_aspect_pixels
r5_aspect_pixels:
    ldr w8, [x3]
    cbnz w8, pixels_native
    ldrb w8, [x3, #0xb80]
    cbz w8, pixels_native
    ldrb w8, [x3, #0xf3]
    cbnz w8, pixels_raw
    ldrb w8, [x3, #0xf2]
    ldrb w9, [x3, #0xf4]
    orr w8, w8, w9
    cbz w8, pixels_native
    ldr w8, [x3, #0xb84]
    ldr w9, [x3, #0xb88]
    cmp w8, w2
    ccmp w9, w0, #0, eq
    b.ne pixels_native
    b pixels_dimensions
pixels_raw:
    ldp w8, w9, [x3, #0x14]
    cmp w8, w2
    ccmp w9, w0, #0, eq
    b.ne pixels_native
pixels_dimensions:
    adr x9, pixel_pairs
    mov w10, #18
pixels_next:
    ldp w11, w12, [x9], #8
    ldr w13, [x9], #4
    cmp w2, w11
    ccmp w0, w12, #0, eq
    b.eq pixels_found
    subs w10, w10, #1
    b.ne pixels_next
pixels_native:
    mov w3, #4320
    b stock_pixels_continue
pixels_found:
    mov w0, w13
    mov w3, #7680
    b stock_pixels_store
.balign 4
pixel_pairs:
.include "aspect_pixels.inc"
