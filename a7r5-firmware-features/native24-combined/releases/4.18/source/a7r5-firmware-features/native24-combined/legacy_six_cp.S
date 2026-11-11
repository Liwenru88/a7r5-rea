/* C1–C6 沿用 4.06 的原生选择编号、整组增量及色表控制器。 */
.syntax unified
.arch armv7-a
.thumb

.macro entry name
.balign 4
.global \name
.thumb_func
\name:
.endm

/* 新旧库共享原控制器。只有历史标记进入原六款的上传分支。 */
entry legacy_grid_dispatch
    ldr r2, [r0]
    ldrb r2, [r2, #0x2e]
    subs r2, #249
    cmp r2, #5
    bls 1f
    ldr pc, =current_grid_controller
1:  b.w native_grid_controller

/* 原厂和 SD 路径重放原窗口，只有 C1–C6 走历史选表及缓存分支。 */
entry legacy_grid_window
    ldrb r3, [r10, #0x2e]
    subs r3, #249
    cmp r3, #5
    bls grid_legacy
    cmp r2, #0
    str.w r2, [r5, #0x184]
    it eq
    moveq r1, r2
    strb.w r1, [r5, #0x188]
    strb.w r0, [r5, #0x189]
    ldrb.w r3, [r10, #3]
    str r4, [sp]
    cbz r3, grid_stock_ready
    cbz r4, grid_stock_skip
    bl grid_snapshot
grid_stock_ready:
    cbz r4, grid_stock_skip
    mov r0, r9
    b.w native_grid_build
grid_stock_skip:
    b.w native_grid_skip
grid_legacy:
    bl historical_grid_helper
    ldrb.w r3, [r10, #3]
    str r4, [sp]
    cbz r3, grid_legacy_ready
    cbz r4, grid_legacy_ready
    bl grid_snapshot
grid_legacy_ready:
    b.w historical_grid_build
grid_snapshot:
    ldr.w r3, [r8, #4]
    str r2, [r3, #0x60]
    strb.w r1, [r3, #0x64]
    strb.w r0, [r3, #0x65]
    bx lr

entry legacy_grid_upload
    push {r1,r2}
    mrs r2, apsr
    ldrb r1, [r10, #0x2e]
    subs r1, #249
    cmp r1, #5
    bls 1f
    msr apsr_nzcvq, r2
    pop {r1,r2}
    movw r0, #0xfd14
    b.w native_grid_upload
1:  msr apsr_nzcvq, r2
    pop {r1,r2}
    b.w historical_grid_upload

entry legacy_grid_consume
    push {r0,r2}
    mrs r2, apsr
    ldr.w r0, [r8]
    ldrb r0, [r0, #0x2e]
    subs r0, #249
    cmp r0, #5
    bls 1f
    msr apsr_nzcvq, r2
    pop {r0,r2}
    movs r5, #0
    b.w native_grid_consume
1:  msr apsr_nzcvq, r2
    pop {r0,r2}
    b.w historical_grid_consume

entry legacy_full_normalize
    push.w {r2,r12}
    mrs r2, apsr
    ldr r3, [r5, #0x10]!
    sub.w ip, r3, #249
    cmp ip, #5
    it ls
    movls r3, #0
    str r3, [r4, #0xc]
    msr apsr_nzcvq, r2
    pop.w {r2,r12}
    b.w native_full_resume

/* 仅将标记归一为 ST；现有动态 route getter 仍负责读取当前表。 */
entry legacy_partial_normalize
    push.w {r3,r12}
    mrs r3, apsr
    movw r2, #0xeefc
    ldr r0, [r0, #4]
    sub.w ip, r0, #249
    cmp ip, #5
    it ls
    movls r0, #0
    msr apsr_nzcvq, r3
    pop.w {r3,r12}
    ldr pc, =native_partial_getter

/* 私有行 75～86 与 SD 库的 51～74 独立。原厂及 SD 行仍经过原 getter。
 * 保存原分支点的通用寄存器、LR 和条件码。 */
.macro table_gate name, input, target, old, resume, scale=1, offset=0
entry \name
    push.w {r0-r1, r12, lr}
    mrs r12, apsr
    .if \offset
    ldr r0, [\input, #\offset]
    .else
    mov r0, \input
    .endif
    movw r1, #(75 * \scale)
    subs r0, r0, r1
    cmp.w r0, #(11 * \scale)
    bhi 1f
    ldr r0, =legacy_gamma_table - 75 * 28
    .ifc \target,r1
    str r0, [sp, #4]
    .else
    mov \target, r0
    .endif
    msr apsr_nzcvq, r12
    pop.w {r0-r1, r12, lr}
    b.w \resume
1:  msr apsr_nzcvq, r12
    pop.w {r0-r1, r12, lr}
    ldr pc, =\old
.endm

table_gate legacy_table_0, r1, r10, prior_table_0, resume_table_0
table_gate legacy_table_1, r6, r10, prior_table_1, resume_table_1, 1, 0x30
table_gate legacy_table_2, r2, r3, prior_table_2, resume_table_2, 7
table_gate legacy_table_3, r2, r3, prior_table_3, resume_table_3, 7
table_gate legacy_table_4, lr, r2, prior_table_4, resume_table_4
table_gate legacy_table_5, r0, r1, prior_table_5, resume_table_5, 7
.ltorg
