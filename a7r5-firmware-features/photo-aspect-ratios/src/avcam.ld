ENTRY(r5_avcam_jpeg_both)
stock_format = 0x1f4160;
stock_log = 0x20bb10;
stock_name = 0x42977a;
stock_file = 0x429c59;
scn_stock_resume = 0x2066b8;
scn_continue = 0x206490;
thumbnail_stock_resume = 0x206850;
thumbnail_continue = 0x2068b4;
SECTIONS {
    .heif 0xa80 : { *(.heif) }
    .text 0x1f4dbc : { *(.text) }
    /DISCARD/ : { *(.comment*) }
}
ASSERT(SIZEOF(.heif) <= 0x180, "HEIF exceeds verified text padding")
ASSERT(SIZEOF(.text) == 0x128, "JPEG setter window changed")
