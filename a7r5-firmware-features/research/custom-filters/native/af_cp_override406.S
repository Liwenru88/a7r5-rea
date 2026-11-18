/* 89856c：原0x24锁已取得，原DBC memcpy已完成，R6为真实目标副本。 */
.syntax unified
.thumb
.section .text.af_cp_override406_snapshot_gate,"ax",%progbits
.global af_cp_override406_snapshot_gate
.type af_cp_override406_snapshot_gate,%function
.thumb_func
af_cp_override406_snapshot_gate:
    push {r0,r1,r2,r3,r12,lr}
    mov r0,r6
    movw r1,#0xdbc
    bl af_cp_override406_snapshot_target
    pop {r0,r1,r2,r3,r12,lr}
    /* 配对入口均回放完整MOVW/MOVT；4B分支型也越过原MOVT，保留后续转移/unlock。 */
    movw r0,#0xb7d0
    movt r0,#0x157
    ldr.w pc,original_return
.balign 4
original_return: .word 0x898575
.size af_cp_override406_snapshot_gate,.-af_cp_override406_snapshot_gate
#ifdef AF_CP_CAPTURE_INPUT406
/* 898568：原互斥已取得；C胶合先busy、原copy、九字段覆盖、最后同锁发布。 */
.section .text.af_cp_override406_snapshot_copy_gate,"ax",%progbits
.global af_cp_override406_snapshot_copy_gate
.type af_cp_override406_snapshot_copy_gate,%function
.thumb_func
af_cp_override406_snapshot_copy_gate:
    push {r0,r1,r2,r3,r12,lr}
    bl af_cp_override406_snapshot_copy_target
    pop {r0,r1,r2,r3,r12,lr}
    /* 原MOVW/MOVT从未覆盖；本次copy的scratch返回值后续不再读取。 */
    ldr.w pc,copy_return
.balign 4
copy_return: .word 0x89856d
.size af_cp_override406_snapshot_copy_gate,.-af_cp_override406_snapshot_copy_gate
#endif
