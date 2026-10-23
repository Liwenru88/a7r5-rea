/* 独立 DMA 测试只允许 CPU0；原厂 CP 启动不使用这个入口。 */
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
    mrc p15, 0, r0, c0, c0, 5
    ands r0, r0, #3
    bne secondary_wait
    mrc p15, 0, r1, c1, c0, 0
    bic r1, r1, #2
    mcr p15, 0, r1, c1, c0, 0
    isb
    ldr sp, =0x03f00000
    ldr r0, =cp_probe_main
    bx r0
secondary_wait:
    wfi
    b secondary_wait
cp_exception:
    cpsid if
    ldr sp, =0x03ff0000
    ldr ip, =cp_exception_main
    bx ip
