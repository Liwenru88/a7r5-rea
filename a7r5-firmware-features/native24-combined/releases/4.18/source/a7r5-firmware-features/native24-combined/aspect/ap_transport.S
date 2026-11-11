.text
.global r5_aspect_ap_prepare
.global r5_aspect_ap_send

/* 0x70–0x72 是原生三字节局部数组，0x78 起是下一局部对象。 */
.equ wire_in_frame, 0x77

r5_aspect_ap_prepare:
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
