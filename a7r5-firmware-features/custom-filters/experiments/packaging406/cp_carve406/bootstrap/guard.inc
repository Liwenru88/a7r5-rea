/* 与guard.c相同的准入顺序；共享literal以保持原408B容量。 */
.global af_carve_prepare
.type af_carve_prepare,%function
.thumb_func
af_carve_prepare:
 push {r4,r5,r6,lr}
 ldr r5,phase
 movs r0,#0
 str r0,[r5]
 bl carve_root_bad
 cbnz r0,prepare_return
 /* helper成功时r2保留精确原L1根；不重复占用literal。 */
 ldr.w r0,[r2,#0xa8]
 ldr r1,carve_cold_section
 cmp r0,r1
 bne prepare_return
 ldr r0,carve_rx
 ldr r1,carve_source
 movw r2,#AF_RX_BYTES
 blx stock_copy
 ldr r4,carve_rw
 mov r0,r4
 movw r1,#AF_RW_BYTES
 blx stock_zero
 movs r0,#1
 mvn r1,r0
 str r1,[r4]
 str r0,[r5]
prepare_return:
 movs r0,#0
 pop {r4,r5,r6,pc}
.size af_carve_prepare,.-af_carve_prepare

/* 返回0仅当MMU开启、TTBCR精确为0、TTBR0精确为原根。 */
.type carve_root_bad,%function
.thumb_func
carve_root_bad:
 mrc p15,0,r0,c1,c0,0
 mrc p15,0,r1,c2,c0,2
 lsrs r0,r0,#1
 it cc
 movcc r1,#1
 mrc p15,0,r0,c2,c0,0
 ldr r2,carve_root
 eors r0,r2
 orrs r0,r1
 bx lr
.size carve_root_bad,.-carve_root_bad

.global af_carve_cache
.type af_carve_cache,%function
.thumb_func
af_carve_cache:
 push {r4,r5,r6,lr}
 mov r4,r0
 blx stock_dcache
 ldr r5,phase
 ldr r0,[r5]
 cmp r0,#1
 bne cache_return
 movs r0,#0
 str r0,[r5]
 bl carve_root_bad
 cbnz r0,cache_return
 ldr.w r0,[r2,#0xa8]
 bic r1,r0,#0x7c00
 ldr r2,carve_coarse
 cmp r1,r2
 bne cache_return
 addw r0,r0,#AF_CARVE_PTE_BIAS
 ldr r1,carve_rx
 addw r1,r1,#0x63e
 movs r2,#AF_CARVE_RX_PAGES
pte_loop:
 ldr r3,[r0],#4
 cmp r3,r1
 bne cache_return
 add.w r1,r1,#0x1000
 subs r2,#1
 bne pte_loop
 /* 仅用expected PTE低位区分两个已固定区间；实际PTE必须先逐项精确相等。 */
 lsls r3,r1,#31
 bmi pages_done
 ldr r1,carve_rw
 addw r1,r1,#0x41f
 movs r2,#AF_CARVE_RW_PAGES
 b pte_loop
pages_done:
 ldr r1,carve_rx
 movw r2,#AF_RX_BYTES
 ldr r3,carve_crc_table
 movs r0,#0
crc_loop:
 ldrb r6,[r1],#1
 eor.w r6,r6,r0,lsr #24
 ldr.w r6,[r3,r6,lsl #2]
 eor.w r0,r6,r0,lsl #8
 subs r2,#1
 bne crc_loop
 ldr r1,carve_crc
 cmp r0,r1
 bne cache_return
 mov r0,r4
 blx stock_icache
 movs r0,#2
 str r0,[r5]
cache_return:
 pop {r4,r5,r6,pc}
.size af_carve_cache,.-af_carve_cache
.balign 4
carve_root:.word 0x1a3c000
carve_coarse:.word 0x1a40001
carve_cold_section:.word 0x2a10c12
carve_rx:.word AF_CARVE_RX
carve_rw:.word AF_CARVE_RW
carve_source:.word AF_CARVE_COLD
carve_crc_table:.word 0xce0354
carve_crc:.word AF_RX_CRC
