/* Sony 4.00 HEIF 辅助图分类：补齐本机新旧裁切生成的七个精确尺寸。
 * 入口在原生 ispe 成功读取之后；其余尺寸继续原生 320/1080/1920 规则。
 * X29 是原函数栈帧，X22 为原生输出分类指针。无新状态或绝对地址。
 */
.text
.p2align 2
.global aspect_mpr_heif_aux_entry
.type aspect_mpr_heif_aux_entry,%function
aspect_mpr_heif_aux_entry:
    ldr w1, [x29, #0x60]
    ldr w0, [x29, #0x64]
    adr x2, .Lscene_pairs
    mov w3, #6
1:
    ldp w4, w5, [x2], #8
    cmp w1, w4
    ccmp w0, w5, #0, eq
    b.eq 3f
    subs w3, w3, #1
    b.ne 1b
    cmp w0, #208
    b.ne 2f
    cmp w1, #256
    b.eq 4f
    cmp w1, #240
    b.eq 4f
2:
    b aspect_mpr_native_aux_body
3:
    mov w0, #1
    b aspect_mpr_native_scn
4:
    b aspect_mpr_native_thumb
.size aspect_mpr_heif_aux_entry,.-aspect_mpr_heif_aux_entry

/* RAW私有TIFF已构造且SCN SOI已完成。保留调用点所有volatile整数
 * 寄存器及NZCV；C代码编译禁用向量化，无浮点/SIMD指令。 */
.p2align 2
.global aspect_mpr_raw_metadata_entry
.type aspect_mpr_raw_metadata_entry,%function
aspect_mpr_raw_metadata_entry:
    sub sp, sp, #176
    stp x0, x1, [sp, #0]
    stp x2, x3, [sp, #16]
    stp x4, x5, [sp, #32]
    stp x6, x7, [sp, #48]
    stp x8, x9, [sp, #64]
    stp x10, x11, [sp, #80]
    stp x12, x13, [sp, #96]
    stp x14, x15, [sp, #112]
    stp x16, x17, [sp, #128]
    stp x18, x30, [sp, #144]
    mrs x9, nzcv
    str x9, [sp, #160]
    cmp w20, #0
    b.le .Lraw_metadata_fail
    ldr x0, [x26, #0x1798]
    mov x1, x28
    mov w2, w20
    bl aspect_mpr_raw_metadata
    cbnz w0, .Lraw_metadata_fail
    ldr x9, [sp, #160]
    msr nzcv, x9
    ldp x0, x1, [sp, #0]
    ldp x2, x3, [sp, #16]
    ldp x4, x5, [sp, #32]
    ldp x6, x7, [sp, #48]
    ldp x8, x9, [sp, #64]
    ldp x10, x11, [sp, #80]
    ldp x12, x13, [sp, #96]
    ldp x14, x15, [sp, #112]
    ldp x16, x17, [sp, #128]
    ldp x18, x30, [sp, #144]
    add sp, sp, #176
    add x1, x26, x10
    b aspect_mpr_native_raw_metadata_body
.Lraw_metadata_fail:
    add sp, sp, #176
    mov w1, #-1
    b aspect_mpr_native_raw_metadata_error
.size aspect_mpr_raw_metadata_entry,.-aspect_mpr_raw_metadata_entry

.balign 4
.Lscene_pairs:
.include "aspect_scenes.inc"

