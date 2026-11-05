/* 没有SHN_ABS原AP符号；最终返回分支在预检后的受控装载阶段填充。 */
ENTRY(af_ap_hs_gate)
PHDRS { code PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); dynamic PT_DYNAMIC FLAGS(6); }
SECTIONS {
 . = SIZEOF_HEADERS;
 .text : { *(.text*) } :code
 .rodata : { *(.rodata*) } :code
 .dynsym : { *(.dynsym) } :code
 .gnu.hash : { *(.gnu.hash) } :code
 .hash : { *(.hash) } :code
 .dynstr : { *(.dynstr) } :code
 .rela.dyn : { *(.rela.dyn) } :code
 . = ALIGN(0x1000);
 .dynamic : { *(.dynamic) } :data :dynamic
 .data : { *(.data*) *(.got*) } :data
 .bss (NOLOAD) : { *(.bss*) *(COMMON) } :data
 /DISCARD/ : { *(.comment) *(.eh_frame*) }
}
