/* 只供固定Thumb-2源码；复用旧outer的真实BL和selector返回地址。 */
.syntax unified
.thumb
.text
.align 2
.global af_cp_components406_gamma_inner
.type af_cp_components406_gamma_inner,%function
.thumb_func
af_cp_components406_gamma_inner:
    push.w {r4-r11,lr}
    sub sp,sp,#4
    mov r4,r0
    mov r5,r1
    mov r6,r2
    sub.w sp,sp,#576
    mov r0,sp
    movw r1,#144
1:
    ldr r2,[r3],#4
    str r2,[r0],#4
    subs r1,r1,#1
    bne 1b
    /* BEF9AE重新装载r0/r1/r2并MOV r8,SP，原BL返回BEF9BB。
     * 原BEF9BA..9C2负责释放616B并恢复全部原callee-saved。 */
    ldr.w pc,2f
.align 2
2: .word 0x00bef9af
.size af_cp_components406_gamma_inner,.-af_cp_components406_gamma_inner

/* 原230DA8总帧40B；BEF550的savedLR在原SP+36。附加32B后为SP+68。
 * flags与临时continuation在额外8B，保存全部原caller-saved并保持8字节对齐。 */
.align 2
.global af_cp_components406_grid_gate
.type af_cp_components406_grid_gate,%function
.thumb_func
af_cp_components406_grid_gate:
    push.w {r0-r3,r12,lr}
    sub sp,sp,#8
    mrs r12,apsr
    str r12,[sp,#4]
    mov r0,r9
    mov r1,r8
    add r2,sp,#68
    bl af_cp_components406_grid_enter_target
    cmp r0,#0
    bne 3f
    ldr r0,5f
3:  str r0,[sp]
    ldr r12,[sp,#4]
    msr APSR_nzcvq,r12
    add sp,sp,#8
    pop.w {r0-r3,r12,lr}
    sub sp,sp,#32
    ldr pc,[sp],#32
.align 2
5:  .word 0x00bef551
.size af_cp_components406_grid_gate,.-af_cp_components406_grid_gate

.align 2
.global af_cp_components406_grid_cleanup
.type af_cp_components406_grid_cleanup,%function
.thumb_func
af_cp_components406_grid_cleanup:
    push.w {r0-r3,r12,lr}
    sub sp,sp,#8
    mrs r12,apsr
    str r12,[sp,#4]
    bl af_cp_components406_grid_leave_target
    str r0,[sp]
    ldr r12,[sp,#4]
    msr APSR_nzcvq,r12
    add sp,sp,#8
    pop.w {r0-r3,r12,lr}
    sub sp,sp,#32
    ldr pc,[sp],#32
.size af_cp_components406_grid_cleanup,.-af_cp_components406_grid_cleanup

/* 原71D6EC处r6=root/r5=sector，phase0不经过本shim。
 * 只补齐C端口的第三、第四参；真实LR及r0/r1保持原样。 */
.align 2
.global af_cp_components406_matrix9_shim
.type af_cp_components406_matrix9_shim,%function
.thumb_func
af_cp_components406_matrix9_shim:
    mov r2,r6
    mov r3,r5
    b.w af_cp_components406_matrix9_target
.size af_cp_components406_matrix9_shim,.-af_cp_components406_matrix9_shim
