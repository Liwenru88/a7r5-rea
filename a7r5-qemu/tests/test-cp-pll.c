/* 原厂可见的最小协议契约；不验证模拟延迟或频率等于物理芯片。 */
#include <assert.h>
#include <stdio.h>
#include "../source/qemu/a7r5-cp-edma.h"
static void write0(CPSCU *s, uint32_t value) {
    assert(cp_scu_access(s,0x100,true,&value));
}
static uint32_t read0(CPSCU *s) {
    uint32_t value=0xffffffff;
    assert(cp_scu_access(s,0x100,false,&value)); return value;
}
int main(void) {
    CPSCU s={0};
    cp_pll0_advance(&s,0);
    assert(read0(&s)==0); /* 显式虚拟未配置初态，不能读即就绪。 */
    write0(&s,0x18016b00);
    cp_pll0_advance(&s,1000000);
    assert(!(read0(&s)&0x1000000)); /* 没有输入时钟不能完成。 */
    s.pll0_reference_present=true;
    write0(&s,0);
    write0(&s,0x18000000);
    cp_pll0_advance(&s,2000000);
    assert(!(read0(&s)&0x1000000)); /* 空配置不能完成。 */
    write0(&s,0x18016b00);
    cp_pll0_advance(&s,2000000+CP_PLL0_DELAY_NS-1);
    assert(!(read0(&s)&0x1000000));
    cp_pll0_advance(&s,2000000+CP_PLL0_DELAY_NS);
    assert(read0(&s)==0x19016b00);
    /* 重复读写不得重新启动；软件也不能直接写完成状态。 */
    uint64_t deadline=s.pll0_deadline;
    write0(&s,read0(&s)); assert(s.pll0_deadline==deadline);
    write0(&s,0x01015f00); assert(read0(&s)==0x15f00);
    cp_pll0_advance(&s,4000000); assert(read0(&s)==0x15f00);
    write0(&s,0x18015f00);
    cp_pll0_advance(&s,4000000+CP_PLL0_DELAY_NS);
    assert(read0(&s)==0x19015f00);
    s.pll0_reference_present=false;
    cp_pll0_advance(&s,5000000); assert(read0(&s)==0x18015f00);
    write0(&s,0x18012345);
    cp_pll0_advance(&s,6000000); assert(!(read0(&s)&0x1000000));
    uint32_t value=0; assert(!cp_scu_access(&s,0x114,false,&value));
    assert(!cp_scu_access(&s,0x101,false,&value));
    puts("CP_PLL0_CONTRACT_OK no_unconditional_lock=1 unknown_channels_rejected=1");
    return 0;
}
