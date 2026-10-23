/* 独立 Linux ELF 入口；不依赖未随包提供的 crt 对象。 */
.text
.global _start
.type _start,%function
_start:
    mov x29, xzr
    mov x30, xzr
    ldr x0, [sp]
    add x1, sp, #8
    bl main
    mov x8, #93
    svc #0
