/* 按本地主选择身份固定FL2/FL3，其他槽继续使用原基底表。 */
.text
.global combined_selection
combined_selection:
    cmp w0, #16
    b.eq special
    cmp w0, #17
    b.eq fl2
    cmp w0, #18
    b.eq fl3
    cmp w1, #11
    b.hi invalid_base
    adr x0, base_table
    ldrb w0, [x0, w1, uxtw]
store:
    strb w0, [x2]
    ret
fl2:
    mov w0, #19
    b store
fl3:
    mov w0, #20
    b store
special:
    mov w0, #-1
    b store
.balign 4
base_table:
    .byte 0,3,2,1,16,15,17,18,5,13,19,20
