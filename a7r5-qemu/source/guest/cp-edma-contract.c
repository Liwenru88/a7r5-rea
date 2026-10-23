/* 独立外设验收程序，不加载 CP、不生成应用回复。 */
typedef unsigned int u32;
#define REG(a) (*(volatile u32 *)(a))
#define DMA 0xf6780000U
#define SIDE 0xf11e0274U
#define GIC 0xf13a1000U
static volatile u32 *const result = (volatile u32 *)0x03e00000;

static void put(const char *s)
{
    while (*s) {
        while (REG(0xf1000018U) & 0x20) { }
        REG(0xf1000000U) = *s++;
    }
}
static void check(int ok, u32 stage)
{
    if (!ok) {
        result[1] = stage;
        put("CP_EDMA_NATIVE_FAILED\n");
        for (;;) { __asm__ volatile("wfi"); }
    }
}
static u32 pending(void)
{
    return REG(GIC+0x230) & (1U<<19); /* 原厂 DMA INTID403。 */
}
void cp_probe_main(void)
{
    result[0] = 0xedaa0001; result[1] = 0;
    result[2] = result[3] = result[4] = result[5] = result[6] = 0;
    volatile unsigned char *src = (void *)0x03000000;
    volatile unsigned char *dst = (void *)0x03001000;
    for (u32 i=0;i<64;i++) { src[i] = i*7+13; dst[i] = 0; }
    REG(SIDE) = 0xffff;
    check(REG(SIDE)==0xffff,1);
    REG(GIC+0) = 1;
    REG(GIC+0x130) = 1U<<19;
    for (u32 n=0;n<5;n++) {
        u32 base=0xf1012000+n*0x1000, bit=1U<<(13+n);
        REG(0xf1388054)=1U<<(18+n);
        REG(0xf1388358)=1U<<(24+n);
        check(REG(base+0xfc)==0x44570140,150+n);
        REG(base+0x6c)=0;
        check(!(REG(base+0x9c)&1),160+n);
        REG(base+0x30)=64; REG(base+4)=0x7f;
        REG(GIC+0x134)=bit;
        REG(base+0x6c)=1;
        check(REG(base+0x9c)&1,170+n);
        REG(base+0x10)=0x2aa;
        check((REG(base+0x34)&64) && (REG(base+0x80)&1),180+n);
        check(REG(GIC+0x234)&bit,190+n);
        (void)REG(base+0x54);
        REG(GIC+0x2b4)=bit;
        check(!(REG(base+0x34)&64) && !(REG(GIC+0x234)&bit),200+n);
        REG(base+0x6c)=0; REG(0xf1388058)=1U<<(18+n);
        result[6]++;
    }
    for (u32 dir=0;dir<2;dir++) {
        REG(DMA+(dir?0x2c:0xc)) = 1;
        for (u32 ch=0;ch<8;ch++) {
            u32 base=DMA+0x200+ch*0x200+dir*0x100;
            REG(base)=8; REG(base+4)=0; REG(base+8)=64;
            REG(base+0xc)=(u32)src; REG(base+0x10)=0;
            REG(base+0x14)=(u32)dst; REG(base+0x18)=0;
            REG(DMA+(dir?0x30:0x10))=ch;
            check(REG(DMA+(dir?0xa0:0x4c))==(1U<<ch),10+dir*8+ch);
            for (u32 i=0;i<64;i++) { check(src[i]==dst[i],30+dir*8+ch); }
            check(pending()!=0,50+dir*8+ch); result[3]++;
            REG(DMA+(dir?0xa8:0x54))=0xffffffff;
            REG(GIC+0x2b0)=1U<<19;
            check(!pending(),70+dir*8+ch);
            REG(DMA+(dir?0xac:0x58))=1U<<ch;
            REG(DMA+(dir?0xa8:0x54))=0;
            REG(GIC+0x2b0)=1U<<19;
            check(!pending(),90+dir*8+ch);
            result[2]++;
            for (u32 i=0;i<64;i++) { dst[i]=0; }
        }
    }
    volatile u32 *list = (void *)0x03002000;
    for (u32 i=0;i<18;i++) { list[i]=0; }
    list[0]=1; list[1]=32; list[2]=(u32)src; list[4]=(u32)dst;
    list[6]=9; list[7]=32; list[8]=(u32)(src+32); list[10]=(u32)(dst+32);
    list[12]=7; list[14]=(u32)list;
    REG(DMA+0x200)=0x300; REG(DMA+0x208)=0;
    REG(DMA+0x21c)=(u32)list; REG(DMA+0x220)=0;
    REG(DMA+0x10)=0;
    check(REG(DMA+0x4c)==1,115);
    for (u32 i=0;i<64;i++) { check(src[i]==dst[i],116); }
    check(pending()!=0,117); result[3]++;
    REG(DMA+0x58)=1; REG(GIC+0x2b0)=1U<<19;
    REG(DMA+0x10)=0; /* 没有新的生产位，不能再次完成。 */
    check(REG(DMA+0x4c)==0 && !pending(),118);
    result[5]=2;
    for (u32 i=0;i<64;i++) { dst[i]=0; }
    /* 高地址并没有 AP 对端，必须 abort，目的 RAM 不得被改写。 */
    REG(DMA+0x200)=8; REG(DMA+0x208)=64;
    REG(DMA+0x20c)=0; REG(DMA+0x210)=1;
    REG(DMA+0x10)=0;
    check(REG(DMA+0x4c)==0x10000,110);
    for (u32 i=0;i<64;i++) { check(dst[i]==0,111); }
    result[4]=1;
    result[1]=0xffffffff;
    put("CP_EDMA_NATIVE_OK\n");
    for (;;) { __asm__ volatile("wfi"); }
}
void cp_exception_main(void)
{
    result[1]=0xeeeeeeee;
    put("CP_EDMA_NATIVE_EXCEPTION\n");
    for (;;) { __asm__ volatile("wfi"); }
}
