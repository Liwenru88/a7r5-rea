ENTRY(matrix_boot_copy)
native_matrix_expand = 0x71e489;
native_matrix_legacy = 0xbef3b5;
native_sound_store = 0x47f62f;
SECTIONS {
  .checksum 0x108f20 : { *(.text.checksum) }
  .matrix_boot_copy 0x108f8c : { *(.text.matrix_boot_copy) }
  .sound 0xbef700 : { *(.text.sound) }
  .matrix 0xbef720 : { *(.text.matrix) }
  /DISCARD/ : { *(.ARM.attributes*) *(.comment*) }
}
ASSERT(SIZEOF(.checksum) <= 32, "checksum overlaps upstream mapper")
ASSERT(SIZEOF(.matrix_boot_copy) <= 116, "bootstrap overlaps native stack")
ASSERT(SIZEOF(.sound) <= 32, "sound overlaps matrix")
ASSERT(SIZEOF(.matrix) <= 1120, "matrix exceeds relocated curve area")
