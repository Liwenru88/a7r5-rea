/* 独立 ARM32 指令验收入口；不是 CP 启动器或 RTOS 替身。 */
.syntax unified
.arch armv7-a
.arm
.section .vectors,"ax"
    b _start
    b cp_exception
    b cp_exception
    b cp_exception
    b cp_exception
    b cp_exception
    b cp_exception
    b cp_exception
.section .startup,"ax"
.global _start
_start:
    cpsid if
    /* 与原 CP 启动 +0x18..0x28 一样清除 SCTLR.A；测试入口不启动 RTOS。 */
    mrc p15, 0, r1, c1, c0, 0
    bic r1, r1, #2
    mcr p15, 0, r1, c1, c0, 0
    isb
    ldr sp, =0x03f00000
    ldr r0, =cp_probe_main
    bx r0
cp_exception:
    cpsid if
    mov r2, lr
    mrs r3, spsr
    mrc p15, 0, r0, c5, c0, 0
    mrc p15, 0, r1, c6, c0, 0
    ldr sp, =0x03ff0000
    ldr ip, =cp_exception_main
    bx ip
