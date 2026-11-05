/* 固定公开数值资产，符号只读驻留；来源见assets/reference-context4.json。 */
#ifdef __APPLE__
.section __TEXT,__const
.globl _af_reference_context4_blob
.globl _af_reference_context4_blob_end
.p2align 3
_af_reference_context4_blob:
#else
.section .rodata.af_reference_context4,"a",%progbits
.globl af_reference_context4_blob
.globl af_reference_context4_blob_end
.balign 8
af_reference_context4_blob:
#endif
.incbin "a7r5-firmware-features/custom-filters/assets/reference-context4.bin"
#ifdef __APPLE__
_af_reference_context4_blob_end:
#else
af_reference_context4_blob_end:
.section .note.GNU-stack,"",%progbits
#endif
