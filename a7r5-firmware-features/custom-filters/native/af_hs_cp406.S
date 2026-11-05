/* 0x496044原任务入口的匿名分流；私有路径直接回原消息释放点。 */
.syntax unified
.thumb
.text
.global af_cp_hs_gate
.type af_cp_hs_gate,%function
.thumb_func
af_cp_hs_gate:
    push {r0,r1,r2,r3,r12,lr}
    mov r0,r6
    mov r1,r5
    ldr r2,[r6,#-8]
    bl af_cp_hs_receive
    cmp r0,#0
    bne owned
    pop {r0,r1,r2,r3,r12,lr}
    movs r0,#0x24
    movw r12,#0x8d6c
    movt r12,#0x5b
    blx r12
    ldrb r0,[r6]
    movw lr,#0x604b
    movt lr,#0x49
    ldr.w pc,original_return
owned:
    pop {r0,r1,r2,r3,r12,lr}
    ldr.w pc,owned_return
.balign 4
original_return: .word 0x49604d
owned_return: .word 0x49606f
.size af_cp_hs_gate,.-af_cp_hs_gate
#ifdef AF_RUNTIME406
.global af_cp_runtime_gate
.type af_cp_runtime_gate,%function
.thumb_func
af_cp_runtime_gate:
    push {r0,r1,r2,r3,r12,lr}
    bl af_cp_hs_start_once
    pop {r0,r1,r2,r3,r12,lr}
    push {r4,r5,r6,r7,lr}
    add r7,sp,#0xc
    push.w {r8,r9,r10,r11}
    ldr.w pc,start_return
.balign 4
start_return: .word 0x495fe1
.size af_cp_runtime_gate,.-af_cp_runtime_gate
#endif
