/* 来源：锁定AP的原getter地址叶、正规化表及原初始化的模型锁调用序。 */
#include "af_factory406.h"
static int separate(const void *a,size_t na,const void *b,size_t nb) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-na && y<=UINTPTR_MAX-nb && (x+na<=y || y+nb<=x);
}
static int index_of(uint32_t selector) {
    return selector<=9?(int)selector:selector==17?16:selector==18?17:-1;
}
int af_factory406_snapshot(uint32_t selector,const uint32_t *bases,
                          const int32_t *const parameters[AF_PARAMETERS],AfPreset *output) {
    AfPreset next={0};int index=index_of(selector);
    uint32_t expected=selector<=9?selector:selector==17?10:11;
    if (index<0 || !bases || !parameters || !output ||
        (uintptr_t)bases%_Alignof(uint32_t) || (uintptr_t)parameters%_Alignof(const int32_t *) ||
        !separate(bases,AF_FACTORY406_ROWS*sizeof(*bases),output,sizeof(*output)) ||
        !separate(parameters,AF_PARAMETERS*sizeof(*parameters),output,sizeof(*output))) return AF_INVALID;
    for (unsigned i=0;i<AF_PARAMETERS;++i) {
        if (!parameters[i] || (uintptr_t)parameters[i]%_Alignof(int32_t) ||
            !separate(parameters[i],AF_FACTORY406_ROWS*sizeof(int32_t),output,sizeof(*output))) return AF_INVALID;
    }
    /* 不将基底数组损坏或旧槽误路由静默改成selector。 */
    if (bases[index]!=expected) return AF_STALE;
    next.base=(uint8_t)selector;
    for (unsigned i=0;i<AF_PARAMETERS;++i) {
        int32_t value=parameters[i][index];
        if (value<-128 || value>127) return AF_INVALID;
        next.params[i]=(int8_t)value;
    }
    if (af_validate(&next)!=AF_OK) return AF_INVALID;
    *output=next;
    return AF_OK;
}

/* 原getter均为固定地址计算的5指令叶，不含缓存/分配/回调。 */
typedef struct { uint32_t address,words[5]; } Getter;
static const Getter getters[]={
    {0x28ae4b0u,{0xb002b280u,0x912a6000u,0x91408000u,0x91354000u,0xd65f03c0u}},
    {0x28c54ccu,{0xd002b1c0u,0x912a6000u,0x91417c00u,0x9102e000u,0xd65f03c0u}},
    {0x28c5544u,{0xd002b1c0u,0x912a6000u,0x91417c00u,0x91280000u,0xd65f03c0u}},
    {0x28c556cu,{0xd002b1c0u,0x912a6000u,0x91417c00u,0x912fe000u,0xd65f03c0u}},
    {0x28c5594u,{0xd002b1c0u,0x912a6000u,0x91417c00u,0x9137c000u,0xd65f03c0u}},
    {0x28c55bcu,{0xd002b1c0u,0x912a6000u,0x91417c00u,0x913fa000u,0xd65f03c0u}},
    {0x28c55e4u,{0xd002b1c0u,0x912a6000u,0x91418000u,0x91078000u,0xd65f03c0u}},
    {0x28c560cu,{0xd002b1c0u,0x912a6000u,0x91418000u,0x910f6000u,0xd65f03c0u}},
    {0x28c5634u,{0xd002b1c0u,0x912a6000u,0x91418000u,0x91174000u,0xd65f03c0u}},
    {0x28c565cu,{0xd002b1c0u,0x912a6000u,0x91418000u,0x911f2000u,0xd65f03c0u}},
};
int af_ap_factory406_snapshot(uintptr_t base,uint32_t selector,AfPreset *output) {
    static const uint32_t offsets[AF_PARAMETERS]={
        0x7f5f498u,0x7f5f690u,0x7f5f888u,0x7f5fa80u,
        0x7f5fc78u,0x7f5fe70u,0x7f60068u,0x7f60260u
    };
    const uintptr_t span=0x8e84000u;
    const int32_t *parameters[AF_PARAMETERS];AfPreset next;int result;
    if (!base || (base&4095u) || base>UINTPTR_MAX-span || index_of(selector)<0 ||
        !separate((const void *)base,span,output,sizeof(*output))) return AF_INVALID;
    /* 调用者的完整来源审计仍为前提；入口检查避免使用已覆写的地址叶。 */
    for (unsigned i=0;i<sizeof(getters)/sizeof(getters[0]);++i)
        for (unsigned j=0;j<5;++j)
            if (*(const uint32_t *)(base+getters[i].address+4u*j)!=getters[i].words[j]) return AF_STALE;
    if (*(const uint32_t *)(base+0x2e7d208u)!=0xa9b97bfdu ||
        *(const uint32_t *)(base+0x2e7cee4u)!=0xa9ba7bfdu) return AF_STALE;
    for (unsigned i=0;i<AF_PARAMETERS;++i) parameters[i]=(const int32_t *)(base+offsets[i]);
    /* 两个原函数入口均在读取参数前覆盖x0，按原成对调用约定复用。 */
    ((void (*)(void))(base+0x2e7d208u))();
    if (*(const volatile uint32_t *)(base+0x7f207e8u)!=selector) result=AF_STALE;
    else {
        result=af_factory406_snapshot(selector,(const uint32_t *)(base+0x7f5eb50u),parameters,&next);
        if (*(const volatile uint32_t *)(base+0x7f207e8u)!=selector) result=AF_STALE;
    }
    ((void (*)(void))(base+0x2e7cee4u))();
    if (result==AF_OK) *output=next;
    return result;
}
