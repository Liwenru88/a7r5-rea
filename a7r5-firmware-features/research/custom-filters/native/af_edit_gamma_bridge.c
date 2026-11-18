#include "af_edit_gamma_bridge.h"
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m &&
           (x+n<=y || y+m<=x);
}
int af_edit_gamma_bridge(const uint32_t *x,const uint32_t *y,
                          const void *record,void *output) {
    uint32_t axis[129],curve[129];
    if (!apart(x,512,output,576) || !apart(y,512,output,576) ||
        !apart(record,576,output,576) || af_gamma406_axis(record,axis)!=AF_OK ||
        axis[127]!=61440 || !y[127] || y[0]) return AF_INVALID;
    for (unsigned i=0;i<128;++i) {
        unsigned target=i==127?128:i;
        if (x[i]!=32u*axis[target] || y[i]>0x3ffffu ||
            (i && (x[i]<=x[i-1] || y[i]<y[i-1]))) return AF_INVALID;
        curve[target]=y[i];
    }
    uint32_t target=axis[127]*32u,width=x[127]-x[126];
    if (!width || target<=x[126] || target>=x[127]) return AF_INVALID;
    curve[127]=y[126]+(uint32_t)(((uint64_t)(y[127]-y[126])*(target-x[126]))/width);
    return af_gamma406_replace(record,curve,output);
}
