/* 私有D9页的值刷新不得再次进入原厂Creative Look写入回调。 */
typedef unsigned long uintptr_t;
extern unsigned char native12_private_page_state[];
extern uintptr_t native12_dispatch_original(uintptr_t,uintptr_t,uintptr_t);
uintptr_t native12_e4_dispatch(uintptr_t controller,uintptr_t message,uintptr_t event) {
    const unsigned char *state=native12_private_page_state;
    uintptr_t owner=*(const uintptr_t *)(state+32),manager=*(const uintptr_t *)(state+48);
    /* 所有权检查与原dispatch一致；退休页面仍不应调用原厂Look setter。 */
    if(event==0x20f0001u && controller && controller==owner && manager &&
       *(const unsigned *)(controller+0x178)==0xd9 &&
       *(const uintptr_t *)(controller+0x180)==manager)return 1;
    return native12_dispatch_original(controller,message,event);
}
/* 原入口前16字节仅保存寄存器，完整保留后继续原体。 */
#ifndef NATIVE12_E4_COMPAT_HOST
__asm__(".pushsection .text.original,\"ax\",@progbits\n"
        ".global native12_dispatch_original\n.type native12_dispatch_original,%function\n"
        "native12_dispatch_original:\n"
        ".word 0xa9bc7bfd,0xa9015ff8,0x910003fd,0xa90257f6\n"
        "b native12_dispatch_continue\n.popsection\n");
#endif
