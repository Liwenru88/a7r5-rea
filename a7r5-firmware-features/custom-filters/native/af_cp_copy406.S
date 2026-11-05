/* 原四个memcpy调用的LR分派；所有外部调用均保持8字节栈对齐。 */
.syntax unified
.thumb
.section .text.af_cp_copy406_gate,"ax",%progbits
.global af_cp_copy406_gate
.type af_cp_copy406_gate,%function
.thumb_func
af_cp_copy406_gate:
    push {r0,r1,r2,r3,r12,lr}
#ifdef AF_CP_NATIVE406
#ifdef AF_CP_CAPTURE406
    ldr r3,capture_request_return
    cmp lr,r3
    beq capture_request
#endif
    ldr r3,gamma_shadow_return
    cmp lr,r3
    beq gamma_shadow
    ldr r3,shot_cache_return
    cmp lr,r3
    beq shot_cache
    ldr r3,queue_direct_return
    cmp lr,r3
    beq queue
    ldr r3,queue_first_return
    cmp lr,r3
    beq queue
    ldr r3,queue_last_return
    cmp lr,r3
    beq queue
    ldr r3,c4_shot_return
    cmp lr,r3
    beq c4
    ldr r3,c4_color_return
    cmp lr,r3
    beq c4
    ldr r3,c4_third_return
    cmp lr,r3
    beq c4
#endif
    ldr r3,snapshot_return
    cmp lr,r3
    beq snapshot
    ldr r3,primary_return
    cmp lr,r3
    beq primary
    ldr r3,secondary_first_return
    cmp lr,r3
    beq secondary
    ldr r3,secondary_second_return
    cmp lr,r3
    beq secondary
    /* 未知返回位置不猜VD；仍完成原copy并撤销已知目的资格。 */
    bl af_cp_override406_untracked_copy_target
    b done
primary:
    /* 原4B8D84保存entry VD于SP+B0；本包装器已push24字节。 */
    ldr r3,[sp,#0xc8]
    b image
secondary:
    /* 原4BB206的STRD保存VD于SP+14，两条copy共用同一原调用帧。 */
    ldr r3,[sp,#0x2c]
image:
    bl af_cp_override406_image_copy_target
    b done
snapshot:
    bl af_cp_override406_snapshot_copy_target
#ifdef AF_CP_NATIVE406
    b done
#ifdef AF_CP_CAPTURE406
capture_request:
    bl af_cp_override406_request_copy_target
    b done
#endif
c4:
    mov r3,lr
    bl af_cp_native406_c4_target
    b done
shot_cache:
    mov r3,lr
    bl af_cp_native406_shot_copy_target
    b done
gamma_shadow:
    mov r3,lr
    bl af_cp_components406_gamma_copy_target
    b done
queue:
    mov r3,lr
    add r12,sp,#24
    sub sp,sp,#8
    str r12,[sp]
    bl af_cp_native406_queue_target
    add sp,sp,#8
#endif
done:
    pop {r0,r1,r2,r3,r12,lr}
    bx lr
.balign 4
snapshot_return: .word 0x89856d
primary_return: .word 0x4baabb
secondary_first_return: .word 0x4bba7d
secondary_second_return: .word 0x4bc007
#ifdef AF_CP_NATIVE406
#ifdef AF_CP_CAPTURE406
capture_request_return: .word 0xadf12d
#endif
gamma_shadow_return: .word 0xaa697d
shot_cache_return: .word 0x313c75
queue_direct_return: .word 0x5c36e4
queue_first_return: .word 0x5c3864
queue_last_return: .word 0x5c388c
c4_shot_return: .word 0x88476b
c4_color_return: .word 0x719605
c4_third_return: .word 0x9071fb
#endif
.size af_cp_copy406_gate,.-af_cp_copy406_gate
