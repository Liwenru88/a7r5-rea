/* 原厂AArch64用户态入口，只转交argc和argv。 */
.text
.global _start
_start:
    mov x29, xzr
    mov x30, xzr
    ldr x0, [sp]
    add x1, sp, #8
    bl main
    mov x8, #93
    svc #0
