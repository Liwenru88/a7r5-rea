/* 隔离动态AP模块；段从0开始，由来源/权限已校验的装载器重定位。不是安装脚本。 */
ENTRY(af_ap_register)
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
