ENTRY(_start)
SECTIONS { . = 0; .vectors : { *(.vectors) } . = 0x40000; .text : { *(.text*) *(.rodata*) } /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) } }
