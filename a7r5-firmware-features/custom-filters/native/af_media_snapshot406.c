#include "af_media_snapshot406.h"

typedef struct { uintptr_t offset; uint32_t words[5]; size_t count; } SourcePin;
/* 固定AP d15933ce...的原字节，getter包括末尾RET。 */
static const SourcePin pins[]={
    {0x28a3b60u,{0x9002b2e0u,0xd29a8d01u,0x912a6000u,0x8b010000u,0xd65f03c0u},5},
    {0x2e7d208u,{0xa9b97bfdu,0xf002d340u,0x91132000u,0x910003fdu,0},4},
    {0x2e7cee4u,{0xa9ba7bfdu,0x9002d360u,0x91132000u,0x910003fdu,0},4},
};

#if defined(AF_MEDIA_SNAPSHOT406_HOST_TEST)
/* 仅宿主边界验证注入，不是运行期服务注册接口。 */
extern void af_media_snapshot406_test_lock(uintptr_t);
extern const uint8_t *af_media_snapshot406_test_get(uintptr_t);
extern void af_media_snapshot406_test_unlock(uintptr_t);
static void lock_original(uintptr_t address){af_media_snapshot406_test_lock(address);}
static const uint8_t *get_original(uintptr_t address){return af_media_snapshot406_test_get(address);}
static void unlock_original(uintptr_t address){af_media_snapshot406_test_unlock(address);}
#else
static void lock_original(uintptr_t address){((void (*)(void))address)();}
static const uint8_t *get_original(uintptr_t address){return ((const uint8_t *(*)(void))address)();}
static void unlock_original(uintptr_t address){((void (*)(void))address)();}
#endif

int af_ap_media_snapshot406(uintptr_t base,size_t span,AfMediaSnapshot406 *output){
    AfMediaSnapshot406 next;
    uintptr_t out=(uintptr_t)output;
    int result=AF_STALE;
    if (!base || (base&4095u) || span!=AF_MEDIA_SNAPSHOT406_AP_SPAN ||
        base>UINTPTR_MAX-span || !output || out>UINTPTR_MAX-sizeof(*output) ||
        !(out+sizeof(*output)<=base || base+span<=out)) return AF_INVALID;
    for (size_t i=0;i<sizeof(pins)/sizeof(pins[0]);++i)
        for (size_t j=0;j<pins[i].count;++j)
            if (*(const uint32_t *)(base+pins[i].offset+4u*j)!=pins[i].words[j])return AF_STALE;
    lock_original(base+0x2e7d208u);
    const volatile uint8_t *source=get_original(base+0x28a3b60u);
    if ((uintptr_t)source==base+0x7f0cf00u){
        for (size_t i=0;i<sizeof(next.bytes);++i)next.bytes[i]=source[i];
        result=AF_OK;
    }
    unlock_original(base+0x2e7cee4u);
    if (result==AF_OK)*output=next;
    return result;
}
