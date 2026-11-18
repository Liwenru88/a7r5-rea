/* 0x3554d90原接收解析入口；通用、完整SIMD和浮点/条件状态配对保存。 */
.text
.macro SAVE
    sub sp,sp,#0x2c0
    stp x0,x1,[sp]
    stp x2,x3,[sp,#0x10]
    stp x4,x5,[sp,#0x20]
    stp x6,x7,[sp,#0x30]
    stp x8,x9,[sp,#0x40]
    stp x10,x11,[sp,#0x50]
    stp x12,x13,[sp,#0x60]
    stp x14,x15,[sp,#0x70]
    stp x16,x17,[sp,#0x80]
    stp x18,x30,[sp,#0x90]
    mrs x9,nzcv
    str x9,[sp,#0xa0]
    mrs x9,fpcr
    str x9,[sp,#0xa8]
    mrs x9,fpsr
    str x9,[sp,#0xb0]
    stp q0,q1,[sp,#0xc0]
    stp q2,q3,[sp,#0xe0]
    stp q4,q5,[sp,#0x100]
    stp q6,q7,[sp,#0x120]
    stp q8,q9,[sp,#0x140]
    stp q10,q11,[sp,#0x160]
    stp q12,q13,[sp,#0x180]
    stp q14,q15,[sp,#0x1a0]
    stp q16,q17,[sp,#0x1c0]
    stp q18,q19,[sp,#0x1e0]
    stp q20,q21,[sp,#0x200]
    stp q22,q23,[sp,#0x220]
    stp q24,q25,[sp,#0x240]
    stp q26,q27,[sp,#0x260]
    stp q28,q29,[sp,#0x280]
    stp q30,q31,[sp,#0x2a0]
.endm
.macro RESTORE
    ldr x9,[sp,#0xa8]
    msr fpcr,x9
    ldr x9,[sp,#0xb0]
    msr fpsr,x9
    ldp q0,q1,[sp,#0xc0]
    ldp q2,q3,[sp,#0xe0]
    ldp q4,q5,[sp,#0x100]
    ldp q6,q7,[sp,#0x120]
    ldp q8,q9,[sp,#0x140]
    ldp q10,q11,[sp,#0x160]
    ldp q12,q13,[sp,#0x180]
    ldp q14,q15,[sp,#0x1a0]
    ldp q16,q17,[sp,#0x1c0]
    ldp q18,q19,[sp,#0x1e0]
    ldp q20,q21,[sp,#0x200]
    ldp q22,q23,[sp,#0x220]
    ldp q24,q25,[sp,#0x240]
    ldp q26,q27,[sp,#0x260]
    ldp q28,q29,[sp,#0x280]
    ldp q30,q31,[sp,#0x2a0]
    ldr x9,[sp,#0xa0]
    msr nzcv,x9
    ldp x0,x1,[sp]
    ldp x2,x3,[sp,#0x10]
    ldp x4,x5,[sp,#0x20]
    ldp x6,x7,[sp,#0x30]
    ldp x8,x9,[sp,#0x40]
    ldp x10,x11,[sp,#0x50]
    ldp x12,x13,[sp,#0x60]
    ldp x14,x15,[sp,#0x70]
    ldp x16,x17,[sp,#0x80]
    ldp x18,x30,[sp,#0x90]
    add sp,sp,#0x2c0
.endm
.global af_ap_hs_gate
.type af_ap_hs_gate,%function
af_ap_hs_gate:
    SAVE
    mov x0,x19
    bl af_stock_msg_size
    mov w2,w0
    mov x0,x19
    mov w1,w20
    bl af_ap_hs_receive
    cbnz w0,owned
    RESTORE
    ldrb w0,[x19]
    b af_ap_hs_original_return
owned:
    RESTORE
    b af_ap_hs_owned_return
.size af_ap_hs_gate,.-af_ap_hs_gate
#ifdef AF_RUNTIME406
/* 原接收调用处以B进入；无消息直接回循环，保留原任务完整寄存器状态。 */
.global af_ap_runtime_gate
.type af_ap_runtime_gate,%function
af_ap_runtime_gate:
    SAVE
    bl af_ap_runtime_next
    cbz w0,empty_receive
    RESTORE
    b af_ap_receive_return
empty_receive:
    RESTORE
    b af_ap_receive_loop
.size af_ap_runtime_gate,.-af_ap_runtime_gate
#endif
