/* 原loader拥有的primary启动入口；未知映射或坏源保持phase0。 */
#include <stdint.h>
#include "image_constants.h"
#include "layout_constants.h"
#define PHASE (*(volatile uint32_t *)0x1a3ac60u)
extern void stock_copy(void *,const void *,uint32_t);
extern void stock_zero(void *,uint32_t);
extern void stock_dcache(void *);
extern void stock_icache(void *);
static uint32_t crc(const uint8_t *p,uint32_t n){
    uint32_t c=0;
    const uint32_t *table=(const uint32_t *)0xce0354u;
    do{c=table[(c>>24)^*p++]^(c<<8);}while(--n);
    return c;
}
static int root_ok(void){
    uint32_t control,root,split;
    __asm__ volatile("mrc p15,0,%0,c1,c0,0":"=r"(control));
    __asm__ volatile("mrc p15,0,%0,c2,c0,0":"=r"(root));
    __asm__ volatile("mrc p15,0,%0,c2,c0,2":"=r"(split));
    return (control&1u)&&!split&&root==0x1a3c000u;
}
uint32_t af_carve_prepare(void){
    PHASE=0;
    /* phase1只允许建立映射，绝不授权代码执行；整载荷CRC在最终发布前检查。 */
    if(!root_ok()||*(volatile uint32_t *)0x1a3c0a8u!=0x02a10c12u)return 0;
    stock_copy((void *)AF_CARVE_RX,(const void *)AF_CARVE_COLD,AF_RX_BYTES);
    stock_zero((void *)AF_CARVE_RW,AF_RW_BYTES);
    *(volatile uint32_t *)AF_CARVE_RW=0xfffffffeu;
    PHASE=1;
    return 0;
}
void af_carve_cache(void *cache){
    stock_dcache(cache);
    if(PHASE!=1)return;
    PHASE=0;
    if(!root_ok())return;
    uint32_t table=*(volatile uint32_t *)0x1a3c0a8u;
    /* 原5f10c8从fault项新建coarse，低10位精确为1；池仍为原32KiB。 */
    if((table&0xffff83ffu)!=0x1a40001u)return;
    const volatile uint32_t *pte=(const volatile uint32_t *)(table+AF_CARVE_PTE_BIAS);
    for(uint32_t i=0;i<AF_CARVE_RX_PAGES;++i)
        if(pte[i]!=(AF_CARVE_RX+0x63eu+(i<<12)))return;
    for(uint32_t i=0;i<AF_CARVE_RW_PAGES;++i)
        if(pte[AF_CARVE_RX_PAGES+i]!=(AF_CARVE_RW+0x41fu+(i<<12)))return;
    if(crc((const void *)AF_CARVE_RX,AF_RX_BYTES)!=AF_RX_CRC)return;
    stock_icache(cache);PHASE=2;
}
