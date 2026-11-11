ENTRY(r5_aspect_ap_prepare)
stock_sender = 0x355882c;
aspect_selection = 0x8f12b60;
aspect_registrations = 0x8f12b68;
stock_get = 0x1c448dc;
stock_set = 0x1c61d14;
stock_commit = 0x1c93d88;
stock_list_commit = 0x1bd9410;
stock_register = 0x1c91e94;
stock_parent_register = 0x1c927e4;
stock_alias_register = 0x1c93a9c;
stock_list_resume = 0x1bc36fc;
stock_available_resume = 0x1bd5418;
stock_size_resume = 0x1bcfd1c;
stock_apply_resume = 0x1bc7724;
aspect_guide_slots = 0x8f12bc8;
stock_view_vtable = 0x5783098;
stock_guide_vtable = 0x57836a0;
stock_descriptors_a = 0x4125d78;
stock_descriptors_a_alt = 0x412d480;
stock_descriptors_b = 0x4039480;
stock_descriptors_b_alt = 0x403ee80;
stock_guide_produce = 0x240dae0;
stock_guide_full_produce = 0x240dd00;
stock_guide_visible = 0x240de30;
stock_guide_hidden = 0x240db10;
stock_guide_cap_a_resume = 0x2146228;
stock_guide_cap_b_resume = 0x2156e74;
stock_guide_draw_resume = 0x182e13c;
stock_guide_destroy_resume = 0x182e1b0;
stock_guide_rotate = 0x182d974;
stock_guide_mask = 0x182dee8;
SECTIONS {
    . = 0x8f04400;
    .text : { *(.text*) *(.rodata*) }
    /DISCARD/ : { *(.eh_frame*) *(.comment*) *(.note*) }
}
