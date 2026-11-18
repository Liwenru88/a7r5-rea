/* 普通AAPCS导入可使用x16；四个全状态返回出口必须保持为单B，不借临时寄存器。 */
.text
.hidden af_ap_requests_targets
.macro IMPORT name,index
.global \name
.type \name,%function
\name:
 adrp x16,af_ap_requests_targets+(8*\index)
 ldr x16,[x16,:lo12:af_ap_requests_targets+(8*\index)]
 cbnz x16,1f
 brk #0x406
1: br x16
.size \name,.-\name
.endm
IMPORT af_stock_msg_size,0
IMPORT af_stock_dlsym,1
IMPORT af_stock_open,2
IMPORT af_stock_read,3
IMPORT af_stock_close,4
IMPORT af_stock_errno,5
IMPORT af_stock_allocate,6
IMPORT af_stock_source,7
IMPORT af_stock_send,8
IMPORT af_stock_receive,9
IMPORT af_stock_usleep,10
.macro EXIT name
.global \name
.type \name,%function
\name:
 /* 未完成来源/地址核验的模块不可运行；装载者以最终单B替换此显式陷阱。 */
 brk #0x406
.size \name,.-\name
.endm
EXIT af_ap_hs_original_return
EXIT af_ap_hs_owned_return
EXIT af_ap_receive_return
EXIT af_ap_receive_loop
