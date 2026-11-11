.syntax unified
.arch armv7-a
.thumb
.text
.global r5_lens_af_capability_flag
.thumb_func
r5_lens_af_capability_flag:
    /* 五个调用点只替换兼容标志读取，保留其他寄存器及原条件码。 */
    push {r1, r2}
    mrs r2, apsr
    movw r0, #0xe5b1
    movt r0, #0x19c
    ldrb r0, [r0]
    cmp r0, #1
    bne done
    movw r1, #0xe357
    movt r1, #0x119
    ldrb r1, [r1]
    cmp r1, #0
    it eq
    moveq r0, #0
done:
    msr APSR_nzcvq, r2
    pop {r1, r2}
    bx lr
