ENTRY(r5_aspect_boot)
PROVIDE(old_mapper = 0x108f40);
native_mapper = 0x108768;
SECTIONS {
    .aspect 0x118000 : { *(.text*) *(.rodata*) }
    .aspect_boot 0xbef7c0 : { *(.aspect_boot) }
    /DISCARD/ : { *(.ARM.attributes*) *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }
}
ASSERT(SIZEOF(.aspect_boot) <= 0x3c0, "aspect loader exceeds relocated curve page")
ASSERT(SIZEOF(.aspect) <= 0x1000, "aspect code exceeds its executable page")
