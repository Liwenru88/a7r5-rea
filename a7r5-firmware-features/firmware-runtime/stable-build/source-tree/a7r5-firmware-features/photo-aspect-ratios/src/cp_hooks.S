.syntax unified
.arch armv7-a

/* 首次映射时复用现有 mapper，再映射扩展代码并清零比例状态。 */
.arm
.section .aspect_boot,"ax",%progbits
.global r5_aspect_boot
r5_aspect_boot:
    push {r4, lr}
    bl old_mapper
    push {r0-r3, r12, lr}
    mrs r4, apsr
    movw r0, #0x8000
    movt r0, #0x11
    mov r2, r0
    mov r1, #0x1000
    mov r3, #0xe
    bl native_mapper
    movw r0, #0xad80
    movt r0, #0x1a3
    mov r1, #128
    mov r2, #0
1:  str r2, [r0], #4
    subs r1, #1
    bne 1b
    msr APSR_nzcvq, r4
    pop {r0-r3, r12, lr}
    pop {r4, pc}

.thumb
.text

.macro entry name
.global \name
.thumb_func
\name:
.endm

.macro save_volatile
    push {r0-r4, r12, lr}
    mrs r4, apsr
    sub sp, #4
.endm

.macro restore_volatile
    add sp, #4
    msr APSR_nzcvq, r4
    pop {r0-r4, r12, lr}
.endm

entry r5_aspect_select_hook
    save_volatile
    mov r0, r5
    bl r5_cp_select
    restore_volatile
    bx lr

entry r5_aspect_snapshot_hook
    /* 原捕获快照函数的 LR 位于其帧指针之后一个字。 */
    ldr r3, [r7, #4]
    b r5_cp_snapshot

entry r5_aspect_pool_reset_hook
    save_volatile
    mov r0, r9
    bl r5_cp_pool_reset
    restore_volatile
    movs r2, #0
    str r2, [r0]
    bx lr

entry r5_aspect_jpeg_hook
    mov r3, r4
    b r5_cp_jpeg_copy

entry r5_aspect_thumbnail_hook
    mov r2, r4
    b r5_cp_thumbnail_clear

entry r5_aspect_heif_hook
    mov r3, r4
    b r5_cp_heif_copy

.macro dimensions name, format
entry \name
    push {r0-r3, r12, lr}
    ldr r12, [sp, #24]
    sub sp, #8
    str r12, [sp]
    movw r12, #0xb9d9
    movt r12, #0x48
    blx r12
    add sp, #8
    ldr r0, [sp]
    mov r1, r4
    movw r2, #\format
    ldr r2, [r4, r2]
    bl r5_cp_notify_jpeg
    pop {r0-r3, r12, pc}
.endm

dimensions r5_aspect_primary_hook, 0x5980
dimensions r5_aspect_secondary_hook, 0x5988
