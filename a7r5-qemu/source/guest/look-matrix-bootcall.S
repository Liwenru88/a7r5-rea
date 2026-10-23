/* 原厂引导ARM指令到Thumb复制器的固定调用点。 */
.syntax unified
.arch armv7-a
.arm
.section .text,"ax"
.global matrix_boot_call
matrix_boot_call:
    blx matrix_boot_copy_entry
