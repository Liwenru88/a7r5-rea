// R5 4.00 原生 RAW 目录接口；代码只使用已替换映射函数的原执行区。
.syntax unified
.thumb
.text
.balign 4
.global r5_raw_mapping
.thumb_func
r5_raw_mapping:
    push {r4, lr}
    movw r2, #0x780c
    movt r2, #0x198
    ldrb r3, [r2, #3]
    cmp r3, #12
    bhi .Lmissing
    add.w r2, r2, #0x70
    add.w r12, r2, r3
    movs r3, #0
.Lfind:
    cmp r2, r12
    beq .Lmissing
    ldrb r4, [r2], #1
    cmp r4, r0
    beq .Lfound
    adds r3, #1
    b .Lfind
.Lfound:
    str r3, [r1]
    movs r0, #0
    pop {r4, pc}
.Lmissing:
    mvn r0, #3
    pop {r4, pc}

.balign 4
.global r5_raw_quantity
.thumb_func
r5_raw_quantity:
    movw r1, #0x780c
    movt r1, #0x198
    ldrb r1, [r1, #3]
    strb r1, [r0]
    cmp r1, #10
    beq .Lquantity_ok
    cmp r1, #12
    beq .Lquantity_ok
    mvn r0, #3
    bx lr
.Lquantity_ok:
    movs r0, #0
    bx lr

.balign 4
.global r5_raw_construct
.thumb_func
r5_raw_construct:
    movw r2, #0x780c
    movt r2, #0x198
    ldrb r3, [r2, #3]
    // 未知配置保留原路径；只扩张已经识别的十项目录。
    cmp r3, #10
    bne .Lconstruct_native
    movs r3, #10
    strb.w r3, [r2, #0x7a]
    movs r3, #11
    strb.w r3, [r2, #0x7b]
    movs r3, #12
    strb r3, [r2, #3]
.Lconstruct_native:
    b.w r5_raw_original_construct
