#include "af_ap_lifecycle.h"
static int separate(uintptr_t a,size_t n,uintptr_t b,size_t m){
 return a<=UINTPTR_MAX-n && b<=UINTPTR_MAX-m && (a+n<=b || b+m<=a);
}
int af_ap_lifecycle_arm(AfApLifecycle *s,uintptr_t base,void *registry){
 if(!s || (uintptr_t)s%_Alignof(AfApLifecycle) || !base || (base&4095u) ||
    base>UINTPTR_MAX-0x8e84000u || !registry || ((uintptr_t)registry&7u) ||
    !separate((uintptr_t)s,sizeof(*s),(uintptr_t)registry,0x30u))return AF_INVALID;
 if(s->phase || s->depth || s->calls)return AF_BUSY;
 AfApRegistration r={1,sizeof(r),base,(uintptr_t)registry,base+0x5030590u,base+0x5046300u,0,0,104,0};
 s->registration=r;s->phase=AF_AP_LIFE_ARMED;return AF_OK;
}
void af_ap_lifecycle_dispatch(AfApLifecycle *s,AfApRegisterFn original,void *registry,const void *begin,const void *end){
 int eligible=s && s->phase==AF_AP_LIFE_ARMED && !s->depth;
 if(s){s->depth++;s->calls++;if(!eligible)s->phase=AF_AP_LIFE_FAILED;}
 if(original)original(registry,begin,end);
 if(!s)return;
 s->depth--;
 if(!original || !eligible || s->phase!=AF_AP_LIFE_ARMED || s->calls!=1 ||
    (uintptr_t)registry!=s->registration.registry || (uintptr_t)begin!=s->registration.begin ||
    (uintptr_t)end!=s->registration.end){s->phase=AF_AP_LIFE_FAILED;return;}
 /* 外层已经按原映射审核registry+28可读；原1c91f24..2c产生此计数。 */
 if(*(const uintptr_t *)((const uint8_t *)registry+0x28u)!=5591u){s->phase=AF_AP_LIFE_FAILED;return;}
 s->registration.rows=5591;s->registration.serial=1;
 s->registration.phase=AF_AP_LIFE_RECORDED;s->phase=AF_AP_LIFE_RECORDED;
}
int af_ap_lifecycle_take(AfApLifecycle *s,AfApRegistration *out){
 if(!s || !out || (uintptr_t)s%_Alignof(AfApLifecycle) || (uintptr_t)out%_Alignof(AfApRegistration) ||
    !separate((uintptr_t)s,sizeof(*s),(uintptr_t)out,sizeof(*out)))return AF_INVALID;
 if(s->phase!=AF_AP_LIFE_RECORDED || s->depth || s->calls!=1 ||
    s->registration.rows!=5591 || s->registration.serial!=1 ||
    *(const uintptr_t *)(s->registration.registry+0x28u)!=5591u)return AF_STALE;
 *out=s->registration;s->phase=AF_AP_LIFE_TAKEN;return AF_OK;
}
int af_ap_lifecycle_write(uint32_t *at,uint32_t before,uint32_t after,
                         int (*protect_page)(void *,int),void (*flush)(void *,size_t)){
 if(!at || ((uintptr_t)at&3u) || !protect_page || !flush)return AF_INVALID;
 if(*at!=before)return AF_STALE;
 void *page=(void *)((uintptr_t)at&~(uintptr_t)4095);
 if(protect_page(page,3))return AF_IO;
 *at=after;flush(at,4);
 if(!protect_page(page,5))return AF_OK;
 if(*at!=after)return AF_AP_LIFE_UNSAFE_PERMISSIONS;
 *at=before;flush(at,4);
 return protect_page(page,5)?AF_AP_LIFE_UNSAFE_PERMISSIONS:AF_IO;
}
