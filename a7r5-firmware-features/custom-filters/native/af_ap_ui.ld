/* 仅匿名离线AP地址空间，严禁直接用于机身。AP基址0另作明确夹具。 */
ENTRY(af_ap_register)
PHDRS { code PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
  . = 0x9000000;
  .text : { *(.text*) } :code
  .rodata : { *(.rodata*) } :code
  . = ALIGN(0x1000);
  .data : { *(.data*) } :data
  .bss (NOLOAD) : { *(.bss*) *(COMMON) } :data
  /DISCARD/ : { *(.comment) *(.eh_frame*) }
}
af_stock_register = 0x1c91e94;
af_stock_base_label = 0x1bd54d8;
af_stock_base_icon = 0x220b838;
af_ret_alias = 0x1bd8ebc;
af_ret_alias_object = 0x1bd1efc;
af_ret_name = 0x1bd1b8c;
af_ret_visible = 0x1bd0000;
af_ret_display = 0x23fcd4c;
af_ret_inhibited = 0x2209584;
af_ret_direct = 0x2209340;
af_ret_select = 0x1c6f20c;
af_ret_preview = 0x25966d0;
af_ret_preview_menu = 0x1c956cc;
af_ret_refresh = 0x1e97a28;
af_ret_parameter_init = 0x220a7b0;
af_ret_base_cycle = 0x220ac78;
af_original_normalize = 0x2dc6160;
af_original_bases = 0x28c54cc;
af_ret_step_0 = 0x220991c;
af_ret_step_1 = 0x2209a70;
af_ret_step_2 = 0x2209bc4;
af_ret_step_3 = 0x2209d18;
af_ret_step_4 = 0x2209e6c;
af_ret_step_5 = 0x2209fc0;
af_ret_step_6 = 0x220a114;
af_ret_step_7 = 0x220a268;
af_ret_icon = 0x1bd18ec;
af_ret_icon_alternate = 0x1bd19ec;
af_ret_parent = 0x1bdb0b4;
af_ret_parameter_value = 0x220b624;
af_ret_parameter_disabled = 0x220b520;
af_ret_parameter_default = 0x220b70c;
af_ret_parameter_layout = 0x220b8a0;
af_ret_base_available = 0x2209468;
af_ret_reset = 0x263d55c;
af_ret_confirm = 0x21f360c;
af_ret_rename_leave_0 = 0x2197b60;
af_ret_rename_leave_1 = 0x219a2f0;
af_ret_rename_leave_2 = 0x219c818;
af_ret_rename_leave_3 = 0x219ed04;
af_ret_rename_init_0 = 0x2198044;
af_ret_rename_init_1 = 0x219a80c;
af_ret_rename_init_2 = 0x219ccc4;
af_ret_rename_init_3 = 0x219f220;
