ENTRY(af_bootstrap_start)
PHDRS { code PT_LOAD FLAGS(5); }
SECTIONS { . = 0x500fc70; .text : { *(.text*) } :code /DISCARD/ : { *(.comment) *(.eh_frame*) } }
af_bootstrap_dlopen = 0x16da8f0;
af_bootstrap_dlsym = 0x16dac90;
af_bootstrap_original_return = 0x17feac4;
af_ctor_original_return = 0x16fbfc0;
ASSERT(af_ctor_bootstrap_end<=0x5010000,"two bootstrap shims exceed original RX final page")
