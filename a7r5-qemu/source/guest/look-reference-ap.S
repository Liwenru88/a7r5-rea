/* 只执行 AP 外观转换叶函数；不启动菜单、Linux 或传输服务。 */
.section .startup,"ax"
.global _start
_start:
    /* 夹具包含未对齐字节日志；不改变被测函数。 */
    mrs x1,sctlr_el1
    bic x1,x1,#2
    msr sctlr_el1,x1
    isb
    ldr x0,=0x40200000
    mov sp,x0
    bl look_ap_main
1:  wfi
    b 1b
