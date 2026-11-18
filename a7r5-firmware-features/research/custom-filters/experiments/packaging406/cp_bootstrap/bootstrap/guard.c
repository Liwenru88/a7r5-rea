/* 仅原RX尾的启动准入；新RX未校验前不执行其中任何函数。 */
#include <stdint.h>
#include "image_constants.h"
#define PHASE (*(volatile uint32_t *)AF_PHASE_ADDRESS)
extern void stock_copy(void *,const void *,uint32_t);
extern void stock_zero(void *,uint32_t);
extern void stock_dcache(void *);
extern void stock_icache(void *);
static uint32_t crc(const uint8_t *p,uint32_t n){
    /* 同包ce0354标准MSB表；初值0、无末异或，不是zlib CRC值。长度显式非零。 */
    uint32_t c=0;
    const uint32_t *table=(const uint32_t *)0xce0354u;
    do{c=table[(c>>24)^*p++]^(c<<8);}while(--n);
    return c;
}
static uint32_t page(void){
    uint32_t control,root,split;
    __asm__ volatile("mrc p15,0,%0,c1,c0,0":"=r"(control));
    __asm__ volatile("mrc p15,0,%0,c2,c0,0":"=r"(root));
    __asm__ volatile("mrc p15,0,%0,c2,c0,2":"=r"(split));
    if(!(control&1u)||(split&7u)||(root&~16383u)!=0x1a3c000u)return 0;
    uint32_t t=*(volatile uint32_t *)(0x1a3c000u+0x1au*4u);
    /* 原loader五次coarse分配中1a段为第五张；未知布局一律拒绝。 */
    if(t!=0x1a41011u)return 0;
    t=*(volatile uint32_t *)0x1a410ecu;
    /* 冷装载原默认页privRW/XN或本方案暖复用privRO/RX；未知AP/域/属性拒绝。 */
    return t==0x1a3b073u||t==0x1a3b63eu?t:0;
}
uint32_t af_boot34_prepare(void){
    PHASE=0;
    uint32_t p=page();if(!p)return 0;
    if(crc((const void *)0x1a3b000u,AF_RX_BYTES)!=AF_RX_CRC){
        if((p&512u)||crc((const void *)0x11d2000u,AF_PAYLOAD_BYTES)!=AF_PAYLOAD_CRC)return 0;
        stock_copy((void *)0x1a3b000u,(const void *)0x11d2000u,AF_RX_BYTES);
    }
    stock_zero((void *)0x1a3ab40u,AF_RW_BYTES);
    *(volatile uint32_t *)0x1a3ab40u=0xfffffffeu;
    PHASE=1;
    return 0;
}
void af_boot34_cache(void *cache){
    stock_dcache(cache);
    if(PHASE==1){stock_icache(cache);PHASE=2;}
}
