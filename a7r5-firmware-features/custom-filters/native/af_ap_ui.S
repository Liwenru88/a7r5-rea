/* 重放被覆盖的首条位置无关指令，然后回到原厂函数+4。
 * 动态模式由绑定表解析原地址，只使用ABI临时寄存器x16；未绑定则明确陷阱。
 * 默认模式保留原8字节跳板布局，兼容现有基址0匿名联验。 */
.text
#ifdef AF_AP_DYNAMIC
.hidden af_ap_stock_targets
.macro RESOLVE index
adrp x16, af_ap_stock_targets + (8*\index)
ldr x16, [x16, :lo12:af_ap_stock_targets + (8*\index)]
cbnz x16, 1f
brk #0x406
1:
.endm
.macro STOCK name, instruction, target, index
.global af_stock_\name
.type af_stock_\name,%function
af_stock_\name:
RESOLVE \index
.inst \instruction
br x16
.size af_stock_\name,.-af_stock_\name
.endm
.macro DIRECT name, index
.global \name
.type \name,%function
\name:
RESOLVE \index
br x16
.size \name,.-\name
.endm
DIRECT af_stock_register, 21
DIRECT af_original_normalize, 22
DIRECT af_original_bases, 23
DIRECT af_stock_base_label, 32
DIRECT af_stock_base_icon, 33
#else
.macro STOCK name, instruction, target, index
.global af_stock_\name
.type af_stock_\name,%function
af_stock_\name:
.inst \instruction
b \target
.size af_stock_\name,.-af_stock_\name
.endm
#endif
STOCK alias, 0xa9be7bfd, af_ret_alias, 0
STOCK alias_object, 0xa9bc7bfd, af_ret_alias_object, 1
STOCK name, 0xa9bb7bfd, af_ret_name, 2
STOCK visible, 0x5282bb03, af_ret_visible, 3
STOCK display, 0xb9402060, af_ret_display, 4
STOCK inhibited, 0xa9bc7bfd, af_ret_inhibited, 5
STOCK direct, 0xa9bd7bfd, af_ret_direct, 6
STOCK select, 0xa9b97bfd, af_ret_select, 7
STOCK preview, 0xa9b97bfd, af_ret_preview, 8
STOCK preview_menu, 0xa9bd7bfd, af_ret_preview_menu, 9
STOCK refresh, 0xa9bd7bfd, af_ret_refresh, 10
STOCK parameter_init, 0xa9b87bfd, af_ret_parameter_init, 11
STOCK base_cycle, 0xa9b67bfd, af_ret_base_cycle, 12
STOCK step_0, 0xa9bc7bfd, af_ret_step_0, 13
STOCK step_1, 0xa9bc7bfd, af_ret_step_1, 14
STOCK step_2, 0xa9bc7bfd, af_ret_step_2, 15
STOCK step_3, 0xa9bc7bfd, af_ret_step_3, 16
STOCK step_4, 0xa9bc7bfd, af_ret_step_4, 17
STOCK step_5, 0xa9bc7bfd, af_ret_step_5, 18
STOCK step_6, 0xa9bc7bfd, af_ret_step_6, 19
STOCK step_7, 0xa9bc7bfd, af_ret_step_7, 20
STOCK icon, 0xa9bb7bfd, af_ret_icon, 24
STOCK icon_alternate, 0xa9bb7bfd, af_ret_icon_alternate, 25
STOCK parent, 0x528566c2, af_ret_parent, 26
STOCK parameter_value, 0xa9be7bfd, af_ret_parameter_value, 27
STOCK parameter_disabled, 0xa9be7bfd, af_ret_parameter_disabled, 28
STOCK parameter_default, 0xa9bd7bfd, af_ret_parameter_default, 29
STOCK parameter_layout, 0xa9bc7bfd, af_ret_parameter_layout, 30
STOCK base_available, 0xa9b97bfd, af_ret_base_available, 31
STOCK reset, 0xa9bc7bfd, af_ret_reset, 34
STOCK confirm, 0xa9b67bfd, af_ret_confirm, 35
STOCK rename_leave_0, 0xa9b87bfd, af_ret_rename_leave_0, 36
STOCK rename_leave_1, 0xa9b87bfd, af_ret_rename_leave_1, 37
STOCK rename_leave_2, 0xa9b87bfd, af_ret_rename_leave_2, 38
STOCK rename_leave_3, 0xa9b87bfd, af_ret_rename_leave_3, 39
STOCK rename_init_0, 0xa9b77bfd, af_ret_rename_init_0, 40
STOCK rename_init_1, 0xa9b77bfd, af_ret_rename_init_1, 41
STOCK rename_init_2, 0xa9b77bfd, af_ret_rename_init_2, 42
STOCK rename_init_3, 0xa9b77bfd, af_ret_rename_init_3, 43
