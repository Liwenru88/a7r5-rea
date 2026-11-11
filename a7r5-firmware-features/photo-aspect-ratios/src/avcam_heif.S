.section .heif,"ax",%progbits
.global r5_avcam_scn
.global r5_avcam_thumbnail

/* 只识别局部 source 的六档精确 SCN 尺寸，不改共享上下文。 */
cropped_heif:
    mov w14, wzr
    ldrh w10, [x15, #4]
    ldrh w11, [x15, #6]
    adr x12, scene_pairs
    mov w13, #6
check_next:
    ldp w14, w15, [x12], #8
    cmp w10, w14
    ccmp w11, w15, #0, eq
    b.eq check_match
    subs w13, w13, #1
    b.ne check_next
    mov w14, wzr
    b check_done
check_match:
    mov w14, #1
check_done:
    ret

r5_avcam_scn:
    mov x15, x27
    bl cropped_heif
    cbz w14, stock_scn
    ldr w0, [x27, #4]
    str w0, [sp, #0xd8]
    b scn_continue
stock_scn:
    ldr w0, [x22, #0x80]
    b scn_stock_resume

r5_avcam_thumbnail:
    mov x15, x23
    bl cropped_heif
    cbz w14, stock_thumbnail
    ldrh w12, [x23, #4]
    ldrh w13, [x23, #6]
    cbz w12, stock_thumbnail
    cbz w13, stock_thumbnail
    mul w10, w8, w13
    mul w11, w9, w12
    cmp w10, w11
    b.hi fit_width
    mov w0, w8
    udiv w1, w10, w12
    b finish_fit
fit_width:
    udiv w0, w11, w13
    mov w1, w9
finish_fit:
    and w0, w0, #0xfffffffc
    and w1, w1, #0xfffffffe
    cbz w0, stock_thumbnail
    cbz w1, stock_thumbnail
    strh w0, [sp, #0x148]
    strh w1, [sp, #0x14a]
    sub w8, w8, w0
    lsr w8, w8, #1
    strh w8, [sp, #0x144]
    sub w9, w9, w1
    lsr w9, w9, #1
    strh w9, [sp, #0x146]
    mov w10, #0x08000000
    str w10, [sp, #0x58]
    mov w11, #0x0800
    strh w11, [sp, #0x5c]
    b thumbnail_continue
stock_thumbnail:
    ldr w0, [x20, #0x80]
    b thumbnail_stock_resume

.balign 4
scene_pairs:
.include "aspect_scenes.inc"
