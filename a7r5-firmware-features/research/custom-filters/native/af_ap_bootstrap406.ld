/* 起点紧接既有aspect 96B；必须另做源布局与零前像审核才可合入候选。 */
ENTRY(af_bootstrap_start)
PHDRS { code PT_LOAD FLAGS(5); }
SECTIONS {
 . = 0x500fc70;
 .text : { *(.text*) } :code
 /DISCARD/ : { *(.comment) *(.eh_frame*) }
}
af_bootstrap_dlopen = 0x16da8f0;
af_bootstrap_dlsym = 0x16dac90;
af_bootstrap_original_return = 0x17feac4;
ASSERT(af_bootstrap_end<=0x5010000,"bootstrap must fit existing final RX page")
