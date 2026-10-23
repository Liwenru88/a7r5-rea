typedef unsigned long u64;
static void write0(const char *s) {
    register u64 x0 __asm__("x0")=4;register const char *x1 __asm__("x1")=s;
    __asm__ volatile("hlt #0xf000":"+r"(x0):"r"(x1):"memory");
}
static void hex(char **p,unsigned v) {
    const char *h="0123456789abcdef";
    for(unsigned i=8;i;i--)*(*p)++=h[(v>>((i-1)*4))&15];
}
void look_ap_main(void) {
    write0("LOOK_AP_BEGIN\n");
    for(unsigned selector=0;selector<=16;selector++)for(unsigned base=0;base<12;base++) {
        unsigned char marker=0xa5;
        ((void(*)(unsigned,unsigned,void*))0x43550354)(selector,base,&marker);
        char s[64],*p=s;*p++='A';*p++=' ';hex(&p,selector);*p++=' ';hex(&p,base);
        *p++=' ';hex(&p,marker);*p++='\n';*p=0;write0(s);
    }
    write0("LOOK_AP_END\n");
    u64 args[2]={0x20026,0};register u64 x0 __asm__("x0")=0x20;
    register u64 *x1 __asm__("x1")=args;
    __asm__ volatile("hlt #0xf000":"+r"(x0):"r"(x1):"memory");
}
