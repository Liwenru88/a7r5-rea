/* 每次请求执行原 AP 叶函数；主机只接续输出字节，不模拟原厂消息传输。 */
#define look_ap_main old_ap_batch_main
#include "look-reference-ap.c"
#undef look_ap_main
void look_ap_main(void) {
    volatile unsigned *request=(void*)0x40300000;
    unsigned char marker=0xa5;
    ((void(*)(unsigned,unsigned,void*))0x43550354)(request[0],request[1],&marker);
    char s[64],*p=s;*p++='A';*p++=' ';hex(&p,request[0]);*p++=' ';hex(&p,request[1]);
    *p++=' ';hex(&p,marker);*p++='\n';*p=0;write0(s);
    u64 args[2]={0x20026,0};register u64 x0 __asm__("x0")=0x20;
    register u64 *x1 __asm__("x1")=args;
    __asm__ volatile("hlt #0xf000":"+r"(x0):"r"(x1):"memory");
}
