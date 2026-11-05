/* 源4.06研究绑定：只准备输入状态，实际消息入口及物理装载仍未接入。 */
.syntax unified
.thumb
.text
.global af_cp406_locked_prepare
.type af_cp406_locked_prepare,%function
.thumb_func
af_cp406_locked_prepare:
    push {r4,r5,r6,lr}
    mov r4,r0
    bl af_validate
    cmp r0,#0
    bne done
    ldrb r1,[r4,#1]
    cmp r1,#0
    bne invalid
    movs r0,#0x24
    movw r12,#0x8d6c
    movt r12,#0x5b
    blx r12
    cmp r0,#0
    bne io_error
    mov r0,r4
    movw r1,#0xaa10
    movt r1,#0x157
    movw r2,#0xdbc
    movw r3,#0x999d
    movt r3,#0x19c
    bl af_cp406_write_state
    mov r5,r0
    dmb sy
    movs r0,#0x24
    movw r12,#0x8910
    movt r12,#0x5b
    blx r12
    cmp r0,#0
    bne io_error
    mov r0,r5
    b done
invalid:
    movs r0,#1
    rsbs r0,r0,#0
    b done
io_error:
    movs r0,#6
    rsbs r0,r0,#0
done:
    pop {r4,r5,r6,pc}
.size af_cp406_locked_prepare,.-af_cp406_locked_prepare
