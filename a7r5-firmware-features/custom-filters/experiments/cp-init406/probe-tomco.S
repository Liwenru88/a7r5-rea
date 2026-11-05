/* 独立离线调用器；实际核身份和原屏障写入均由CPU/原CP产生。 */
.syntax unified
.arch armv8-a
.fpu neon
.arm
.section .vectors,"ax"
 b _start
 b undef_exception
 b svc_exception
 b prefetch_exception
 b data_exception
 b reserved_exception
 b irq_exception
 b fiq_exception
.section .text,"ax"
.global _start
_start:
 cpsid if
 mrc p15,0,r0,c1,c0,0
 bic r0,r0,#2
 mcr p15,0,r0,c1,c0,0
 isb
 mrc p15,0,r8,c0,c0,5
 and r9,r8,#3
 /* SVC栈取自原5f0a50消费的同ROM表，不用猜栈值。 */
 ldr r0,=0x12800c
 mov r1,#0x48
 mla r0,r1,r9,r0
 /* 六bank栈均按原5f0a70..c8的同ROM字段准备。 */
 cps #0x12
 ldr sp,[r0,#0xc]
 cps #0x11
 ldr sp,[r0,#0x18]
 cps #0x1b
 ldr sp,[r0,#0x24]
 cps #0x17
 ldr sp,[r0,#0x30]
 cps #0x1f
 ldr sp,[r0,#0x3c]
 cps #0x13
 ldr sp,[r0]
 mrc p15,0,r0,c1,c0,2
 orr r0,r0,#0xf00000
 mcr p15,0,r0,c1,c0,2
 isb
 mov r0,#0x40000000
 vmsr fpexc,r0
 ldr r11,=0x3000000
 add r11,r11,r9,lsl#6
 str r8,[r11]
 str sp,[r11,#8]
 mov r0,#1
 str r0,[r11,#4]
 cmp r9,#0
 bne secondary
 /* 来自原5e3f34的主核入口；不称执行完整boot前缀。 */
 /* 原5e3f28/2c先设置本核VBAR及异常回调。 */
 ldr r12,=0x5ec7c8
 blx r12
 ldr r12,=0x5e43a0
 blx r12
 ldr r12,=0x5e7ad4
 blx r12
 ldr r11,=0x3000000
 mov r1,#2
 str r1,[r11,#4]
 str r0,[r11,#12]
 /* 保留原5e3f44/7c/80/84/94顺序，避免省略堆/属性生产者。 */
 ldr r12,=0x5efac8
 blx r12
 ldr r11,=0x3000000
 mov r1,#0x12
 str r1,[r11,#4]
 ldr r12,=0x5ed098
 blx r12
 ldr r12,=0x5e6f88
 blx r12
 ldr r11,=0x3000000
 mov r1,#3
 str r1,[r11,#4]
 ldr r12,=0x5e8424
 blx r12
 ldr r11,=0x3000000
 mov r1,#4
 str r1,[r11,#4]
 ldr r12,=0x5e5b88
 blx r12
 ldr r11,=0x3000000
 mov r1,#5
 str r1,[r11,#4]
 /* 原主5e3fa4/5e3fb4的timer生产者，保持原顺序。 */
 ldr r12,=0x5ec438
 blx r12
 ldr r12,=0x5ec4f4
 blx r12
 ldr r11,=0x3000000
 mov r0,#0x27
 str r0,[r11,#4]
 /* 原5e3fd4/fe0开启IRQ并自然发布阶段5，满足原服务入口门限。 */
 cpsie if
 mov r0,#5
 ldr r12,=0x5ea8ac
 blx r12
 /* 原RTOS主入口自行恢复三个从核启动并产生所有目录。 */
 ldr r12,=0x5ccadc
 bx r12
idle:
 wfe
 b idle
secondary:
 /* 原5f0afc选择的完整从核函数，自行产生barrier参数。 */
 ldr r12,=0x5eb3b8
 blx r12
 ldr r11,=0x3000000
 add r11,r11,r9,lsl#6
 mov r1,#3
 str r1,[r11,#4]
 b idle
undef_exception:
 mov r10,#1
 b exception
svc_exception:
 mov r10,#2
 b exception
prefetch_exception:
 mov r10,#3
 b exception
data_exception:
 mov r10,#4
 b exception
reserved_exception:
 mov r10,#5
 b exception
irq_exception:
 mov r10,#6
 b exception
fiq_exception:
 mov r10,#7
exception:
 mrc p15,0,r8,c0,c0,5
 and r9,r8,#3
 ldr r11,=0x3000000
 add r11,r11,r9,lsl#6
 orr r0,r10,#0x80
 str r0,[r11,#4]
 str lr,[r11,#16]
 mrc p15,0,r0,c5,c0,0
 str r0,[r11,#20]
 mrc p15,0,r0,c6,c0,0
 str r0,[r11,#24]
 mrs r0,spsr
 str r0,[r11,#28]
 b idle
