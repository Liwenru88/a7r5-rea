#include "af_cp406_state.h"
static int separate(const void *a,size_t na,const void *b,size_t nb) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-na && y<=UINTPTR_MAX-nb && (x+na<=y || y+nb<=x);
}
int af_cp406_write_state(const AfPreset *p,void *state,size_t bytes,uint8_t *marker) {
    static const unsigned fields[8]={0xa44,0xa46,0xa45,0xa47,0xa48,0xd2e,0xd2f,0xd30};
    static const uint8_t ordinary[10]={0,3,2,1,16,15,17,18,5,13};
    uint8_t *out=state;
    uint8_t base;
    if (af_validate(p)!=AF_OK || p->kind || bytes<AF_CP406_STATE_BYTES ||
        !separate(state,bytes,p,sizeof(*p)) || !separate(state,bytes,marker,1) ||
        !separate(marker,1,p,sizeof(*p))) return AF_INVALID;
    base=p->base<=9?ordinary[p->base]:(p->base==17?19:20);
    out[0xa40]=base;out[0xa41]=out[0xa42]=out[0xa43]=0;
    for (unsigned i=0;i<8;++i) out[fields[i]]=(uint8_t)p->params[i];
    /* 与九条原参数分派全部执行后的副作用一致；下游语义仍待实际绑定。 */
    *marker=1;
    return AF_OK;
}
