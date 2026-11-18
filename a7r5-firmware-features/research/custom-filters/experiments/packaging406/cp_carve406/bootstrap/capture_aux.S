/* 原576B helper及80B matrix helper保留尾部中的五个常驻门。
 * 来源与前像必须由构建器独立校验；不改变原helper任何有效指令。 */
#include "native_capture_constants.h"
#ifndef AF_CAPTURE_PHASE_ENTRY
#error "缺少同次构建的Capture常驻phase地址"
#endif

.syntax unified
.thumb

/* cp_runtime.helper_blob最后48B槽实际止于BEF69A；使用其对齐后20B尾部。 */
.section .text.capture_pool,"ax",%progbits
.global capture_pool_base
capture_pool_base:
.set .Lpool_phase,capture_pool_base+(AF_CAPTURE_PHASE_ENTRY-0x00bef69c)
.global permanent_capture_pool
.type permanent_capture_pool,%function
.thumb_func
permanent_capture_pool:
 push {r0,r1,r2,lr}
 adr.n r0,.Lpool_record
 b.n .Lpool_phase
.balign 4
.global capture_pool_record
.Lpool_record:
capture_pool_record:
 .word AF_CAPTURE_POOL_TARGET,0x00ae07e1
/* colour门位于其record之后，16位ADR不能后寻；在已拥有的末4B存按值地址。 */
.global capture_color_record_pointer
capture_color_record_pointer:
 .word 0x00bef534
.org 20
.global capture_pool_end
capture_pool_end:

/* look_matrix_embed/compact明确预留80B，原60B helper后剩余20B。 */
.section .text.capture_release,"ax",%progbits
.global capture_release_base
capture_release_base:
.set .Lrelease_phase,capture_release_base+(AF_CAPTURE_PHASE_ENTRY-0x00bef6ec)
.global permanent_capture_release
.type permanent_capture_release,%function
.thumb_func
permanent_capture_release:
 push {r0,r1,r2,lr}
 adr.n r0,.Lrelease_record
 b.n .Lrelease_phase
.balign 4
.global capture_release_record
.Lrelease_record:
capture_release_record:
 .word AF_CAPTURE_RELEASE_TARGET,0x00ae0361
.org 20
.global capture_release_end
capture_release_end:

/* 槽0实际止于BEF524，下一槽从BEF53E开始；完整576B生成器拥有此保留尾部。
 * 仅挂AA7F08的实际AA81CA调用，debug旁路不会经过该见证门。 */
.section .text.capture_format,"ax",%progbits
.global capture_format_base
capture_format_base:
.set .Lformat_phase,capture_format_base+(AF_CAPTURE_PHASE_ENTRY-0x00bef524)
.global permanent_capture_format
.type permanent_capture_format,%function
.thumb_func
permanent_capture_format:
 push {r0,r1,r2,lr}
 adr.n r0,.Lformat_record
 b.n .Lformat_phase
.balign 4
.global capture_format_record
.Lformat_record:
capture_format_record:
 .word AF_CAPTURE_FORMAT_TARGET,0x00aa81cb
.global capture_color_record
capture_color_record:
 .word AF_CAPTURE_COLOR_TARGET,0x00719ef7
.org 26
.global capture_format_end
capture_format_end:

/* 原offset90槽有效50B，尾582..588是明确预留的6B。 */
.section .text.capture_rsource,"ax",%progbits
.global capture_rsource_base
capture_rsource_base:
.set .Lrsource_phase,capture_rsource_base+(AF_CAPTURE_PHASE_ENTRY-0x00bef582)
.global permanent_capture_rsource
.type permanent_capture_rsource,%function
.thumb_func
permanent_capture_rsource:
 push {r0,r1,r2,lr}
 /* 582半字起始且记录跨段，显式16位ADR避免汇编器按未知段对齐扩大为4B。 */
 .hword 0xa03c /* PC=BEF588，+F0=BEF678；构建器独立解码。 */
 b.n .Lrsource_phase
.org 6
.global capture_rsource_end
capture_rsource_end:

/* 原offset160槽有效58B；原门/原helper入口均保留。 */
.section .text.capture_color,"ax",%progbits
.global capture_color_base
capture_color_base:
.set .Lcolor_phase,capture_color_base+(AF_CAPTURE_PHASE_ENTRY-0x00bef65a)
.global permanent_capture_color
.type permanent_capture_color,%function
.thumb_func
permanent_capture_color:
 push {r0,r1,r2,lr}
 .hword 0x4813 /* PC=BEF660，+4C=BEF6AC；构建器独立解码。 */
 b.n .Lcolor_phase
.org 6
.global capture_color_end
capture_color_end:

/* 原offset1A0槽有效22B，记录使用其对齐后8B尾部。 */
.section .text.capture_rsource_record,"ax",%progbits
.global capture_rsource_record_base
.global capture_rsource_record
capture_rsource_record_base:
capture_rsource_record:
 .word AF_CAPTURE_RSOURCE_TARGET,0x004596f5
.org 8
.global capture_rsource_record_end
capture_rsource_record_end:

/* 原cp_runtime.helper_blob的FNV槽容量96B；原92B等价改为80B。
 * 五个MOVW/MOVT常量改用本槽只读literal；ADDS后的NZCV由原循环SUBS/CMP覆盖。
 * checker两个POP均在literal前返回，不能顺落新增门或常量池。 */
.section .text.capture_checker,"ax",%progbits
.global capture_checker_base
capture_checker_base:
.global capture_checker_entry
.type capture_checker_entry,%function
.thumb_func
capture_checker_entry:
 push {r0,r1,r2,r4,r5,r6,r7,lr}
 ldr r4,.Lchecker_prefix
 ldr r5,[r4]
 ldr r6,.Lchecker_magic
 cmp r5,r6
 bne .Lchecker_invalid
 ldr r5,[r4,#4]
 ldr r6,.Lchecker_version
 cmp r5,r6
 bne .Lchecker_invalid
 adds r4,#8
 ldr.w r4,[r4,r3,lsl #2]
 ldr r5,.Lchecker_seed
 ldr r6,.Lchecker_prime
 movw r1,#1215
.Lchecker_loop:
 ldrb r0,[r2],#1
 eors r5,r0
 muls r5,r6,r5
 subs r1,#1
 bne .Lchecker_loop
 cmp r5,r4
 ite eq
 moveq r3,#1
 movne r3,#0
 pop {r0,r1,r2,r4,r5,r6,r7,pc}
.Lchecker_invalid:
 movs r3,#0
 pop {r0,r1,r2,r4,r5,r6,r7,pc}
.balign 4
.Lchecker_prefix: .word 0x011952c0
.Lchecker_magic: .word 0x364c3741
.Lchecker_version: .word 0x00010006
.Lchecker_seed: .word 0x811c9dc5
.Lchecker_prime: .word 0x01000193
.org 80
.global permanent_capture_matrix9
.type permanent_capture_matrix9,%function
.thumb_func
permanent_capture_matrix9:
.set .Lmatrix9_phase,capture_checker_base+(AF_CAPTURE_PHASE_ENTRY-0x00bef5c0)
 push {r0,r1,r2,lr}
 adr.n r0,.Lmatrix9_record
 b.n .Lmatrix9_phase
.balign 4
.global capture_matrix9_record
.Lmatrix9_record:
capture_matrix9_record:
 .word AF_CAPTURE_MATRIX9_TARGET,0x0071eccd
.org 96
.global capture_checker_end
capture_checker_end:
