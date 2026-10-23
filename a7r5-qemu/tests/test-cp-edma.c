/* 直接编译模型同一份代码，检查实际字节及拒绝路径。 */
#include <assert.h>
#include <stdio.h>
#include "../source/qemu/a7r5-cp-edma.h"
static uint8_t ram[4096];
static unsigned calls;
static bool read_desc(void *opaque, uint64_t src, void *buf, uint32_t len)
{
    assert(opaque==ram);
    if (src>sizeof(ram) || len>sizeof(ram)-src) { return false; }
    memcpy(buf,ram+src,len);
    return true;
}
static void word(unsigned address,uint32_t value)
{
    for (unsigned i=0;i<4;i++) { ram[address+i]=value>>(i*8); }
}
static bool copy(void *opaque, uint64_t src, uint64_t dst, uint32_t len)
{
    assert(opaque == ram);
    calls++;
    if (src > sizeof(ram) || dst > sizeof(ram) ||
        len > sizeof(ram)-src || len > sizeof(ram)-dst) {
        return false;
    }
    memmove(ram + dst, ram + src, len);
    return true;
}
static void wr(CPEDMA *s, unsigned off, uint32_t v)
{
    assert(cp_edma_access(s, off, true, &v));
}
static uint32_t rd(CPEDMA *s, unsigned off)
{
    uint32_t v = 0xa5;
    assert(cp_edma_access(s, off, false, &v));
    return v;
}
static void submit(CPEDMA *s, unsigned dir, unsigned ch, uint64_t src, uint64_t dst, uint32_t len, uint32_t mode)
{
    unsigned b = 0x200 + ch*0x200 + dir*0x100;
    wr(s,b,mode); wr(s,b+8,len); wr(s,b+0xc,src); wr(s,b+0x10,src>>32);
    wr(s,b+0x14,dst); wr(s,b+0x18,dst>>32); wr(s,dir?0x30:0x10,ch);
}
int main(void)
{
    CPEDMA s;
    uint32_t v;
    cp_edma_init(&s, copy, read_desc, ram);
    assert(!cp_edma_irq(&s));
    for (unsigned i=0;i<128;i++) ram[i] = i ^ 0xa7;
    v=0xffff; assert(cp_edma_side_access(&s,0x20274,true,&v));
    /* 引擎未开：不搬运，不给成功完成。 */
    submit(&s,0,0,0,512,128,8);
    assert(!s.copies && s.aborts==1 && calls==0 && rd(&s,0x4c)==0x10000);
    assert((rd(&s,0x200)&0x60)==0x40);
    wr(&s,0x58,0xffffffff); assert(!cp_edma_irq(&s));
    for (unsigned dir=0;dir<2;dir++) {
        wr(&s,dir?0x2c:0xc,1);
        for (unsigned ch=0;ch<8;ch++) {
            submit(&s,dir,ch,0,512+ch*128,128,8);
            assert(!memcmp(ram,ram+512+ch*128,128));
            assert(rd(&s,dir?0xa0:0x4c)==(1U<<ch));
            assert(cp_edma_irq(&s));
            wr(&s,dir?0xa8:0x54,0xffffffff); assert(!cp_edma_irq(&s));
            wr(&s,dir?0xa8:0x54,0); assert(cp_edma_irq(&s));
            wr(&s,dir?0xac:0x58,1U<<ch); assert(!cp_edma_irq(&s));
        }
    }
    assert(s.copies==16 && s.bytes==2048);
    /* 未连接的 PCIe 高地址、超长、空任务、未知模式均不能冒充已完成。 */
    submit(&s,0,0,0x100000000ULL,0,4,8);
    submit(&s,0,1,0,0,0,8);
    submit(&s,0,2,0,0,17*1024*1024,8);
    submit(&s,0,3,0,512,4,0x400);
    assert(s.copies==16 && s.aborts==5 && rd(&s,0x4c)==0xf0000);
    assert(rd(&s,0x5c)==15);
    wr(&s,0x58,0x10000); assert(rd(&s,0x4c)==0xe0000 && rd(&s,0x5c)==14);
    v=0; assert(!cp_edma_access(&s,0x114,false,&v));
    assert(cp_edma_access(&s,0x204,true,&v)); /* 已定义 control2。 */
    assert(!cp_edma_access(&s,0x225,true,&v));
    assert(!cp_edma_access(&s,0x4c,true,&v));
    assert(!cp_edma_side_access(&s,0x201b8,false,&v)); /* 不伪造 LINK_UP。 */
    v=1; assert(!cp_edma_side_access(&s,0x20274,true,&v));
    /* CB/TCB 链接：最后一项转换 cycle 后回到旧生产位，等待新数据。 */
    wr(&s,0x58,0xffffffff);
    word(2048,1); word(2052,32); word(2056,0); word(2064,2560);
    word(2072,9); word(2076,32); word(2080,32); word(2088,2592);
    word(2096,7); word(2104,2048);
    wr(&s,0x21c,2048); wr(&s,0x220,0); wr(&s,0x200,0x300); wr(&s,0x10,0);
    assert(s.copies==18 && !memcmp(ram,ram+2560,64));
    assert(rd(&s,0x4c)==1 && (rd(&s,0x200)&0x160)==0x20);
    wr(&s,0x58,1); wr(&s,0x10,0);
    assert(s.copies==18 && rd(&s,0x4c)==0); /* 无新生产位，没有伪完成。 */
    /* 自循环的有效链表指针必须有界拒绝，不能发成功中断。 */
    word(2048,5); word(2056,2048);
    wr(&s,0x200,0x300); wr(&s,0x10,0);
    assert(s.aborts==6 && rd(&s,0x4c)==0x10000);
    /* 先发生的真实片段完成不能被后续 abort 擦掉；两类位分别 W1C。 */
    wr(&s,0x58,0xffffffff);
    for (unsigned i=0;i<48;i++) { ram[2048+i]=0; }
    word(2048,9); word(2052,32); word(2056,0); word(2064,2560);
    word(2072,1); word(2076,32); word(2084,1); word(2088,2592);
    wr(&s,0x21c,2048); wr(&s,0x200,0x300); wr(&s,0x10,0);
    assert(s.copies==19 && s.aborts==7 && rd(&s,0x4c)==0x10001);
    wr(&s,0x58,1); assert(rd(&s,0x4c)==0x10000);
    CPGPIO gpio={0};
    v=8; assert(cp_gpio_access(&gpio,0x44,true,&v));
    v=0; assert(cp_gpio_access(&gpio,0x10,false,&v) && v==0);
    v=8; assert(cp_gpio_access(&gpio,4,true,&v));
    assert(cp_gpio_access(&gpio,0x10,false,&v) && v==8);
    v=8; assert(cp_gpio_access(&gpio,0x48,true,&v));
    assert(cp_gpio_access(&gpio,0x40,false,&v) && v==0);
    v=4; gpio.input=4;
    assert(cp_gpio_access(&gpio,0x10,false,&v) && v==4);
    assert(!cp_gpio_access(&gpio,0x10,true,&v));
    assert(!cp_gpio_access(&gpio,0x50,true,&v));
    CPSCU scu={.i2c_reset=0x1fU<<24};
    for (unsigned n=0;n<5;n++) {
        assert(!cp_scu_i2c_enabled(&scu,n));
        v=1U<<(18+n); assert(cp_scu_access(&scu,0x54,true,&v));
        assert(!cp_scu_i2c_enabled(&scu,n));
        v=1U<<(24+n); assert(cp_scu_access(&scu,0x358,true,&v));
        assert(cp_scu_i2c_enabled(&scu,n));
        v=1U<<(18+n); assert(cp_scu_access(&scu,0x58,true,&v));
        assert(!cp_scu_i2c_enabled(&scu,n));
    }
    v=1; assert(!cp_scu_access(&scu,0x54,true,&v));
    assert(!cp_scu_access(&scu,0x60,false,&v));
    v=0x101; assert(cp_scu_access(&scu,0xf4c,true,&v));
    for (unsigned n=0;n<4;n++) {
        v=0; assert(cp_scu_access(&scu,0xf48,false,&v) && v==0x101);
    }
    v=1; assert(cp_scu_access(&scu,0xf50,true,&v));
    assert(scu.dfs_control==0x100); /* 请求位保持，不能伪造转换完成。 */
    assert(!cp_scu_access(&scu,0xf58,false,&v));
    v=0x20000; assert(cp_scu_access(&scu,0x234,true,&v));
    v=0; assert(cp_scu_access(&scu,0x234,false,&v) && v==0x20000);
    v=0x10000; assert(cp_scu_access(&scu,0x238,true,&v));
    assert(scu.clksel[3]==0x20000);
    puts("CP_EDMA_CONTRACT_OK directions=2 channels=8 real_copy=16 no_link_or_message_synthesis=1");
    return 0;
}
