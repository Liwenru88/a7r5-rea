.text
.global r5_avcam_jpeg_both
.global r5_avcam_jpeg_format
.global r5_avcam_jpeg_one

/* 原双槽和单槽入口位置保持。只把公共的宽高写入压缩进同一窗口。 */
r5_avcam_jpeg_both:
    stp x0, x30, [sp, #-16]!
    mov w3, w2
    mov w2, w1
    mov w1, #1
    bl r5_avcam_jpeg_one
    ldp x0, x30, [sp], #16
    mov w1, #0x10
    b r5_avcam_jpeg_one

r5_avcam_jpeg_format:
    str x30, [sp, #-16]!
    bl stock_format
    ldr w10, [x20]
    cmp w10, #2
    ldr x30, [sp]
    add x8, x19, #0xa4
    add x9, x20, #0x1b6
    b choose_slot

r5_avcam_jpeg_one:
    cmp w1, #1
    add x8, x0, #0xa4
    b.eq select_format
    cmp w1, #0x10
    b.ne bad_slot
    add x8, x8, #0x180
select_format:
    ldr w9, [x8]
    cmp w9, #4
    b.hi one_done
    mov w10, #0x16
    lsr w9, w10, w9
    tbz w9, #0, one_done
    str w2, [x8, #0x10]
    stp w3, w2, [x8, #0x1c]
    stp w3, wzr, [x8, #0x2c]
    stp wzr, w2, [x8, #0x3c]
    stp w3, w2, [x8, #0x4c]
    stp w3, w2, [x8, #0x5c]
    stp w3, w2, [x8, #0x6c]
    stp w3, wzr, [x8, #0x7c]
    stp wzr, w2, [x8, #0x8c]
    str w3, [x8, #0x9c]
    add x0, x8, #0x10
    cmp w1, #0x10
    b.ne one_done
    ldr w9, [x8, #0x14]
    mov w10, #0xb6b0
    add w10, w9, w10
    add w9, w10, #0xbc
    str w10, [x8, #0x14]
    str w9, [x8, #0x54]
one_done:
    ret
bad_slot:
    adrp x1, stock_file
    add x0, x1, :lo12:stock_name
    add x1, x1, :lo12:stock_file
    mov w2, #0x471
    b stock_log
choose_slot:
    tbnz w30, #5, maybe_jpeg
    add x8, x8, #0x180
    add x9, x9, #0xc
maybe_jpeg:
    b.ne format_done
    ldr w10, [x8]
    cmp w10, #1
    b.ne format_done
    ldrh w2, [x9]
    ldrh w3, [x9, #2]
    cbz w2, format_done
    cbz w3, format_done
    ldr w10, [x8, #0x20]
    cmp w2, w10
    ldr w10, [x8, #0x2c]
    ccmp w3, w10, #0, eq
    b.eq format_done
    /* 已经完成原生第二槽地址的偏移，只更新本槽尺寸。 */
    sub x0, x8, #0xa4
    mov w1, #1
    bl r5_avcam_jpeg_one
format_done:
    ldr x30, [sp], #16
    ret
