#include "af_edit_gamma_table.h"
#ifdef __FAST_MATH__
#error "Edit gamma construction requires explicit float32 operation order"
#endif
#pragma STDC FP_CONTRACT OFF
_Static_assert(sizeof(float)==4 && __FLT_RADIX__==2 && __FLT_MANT_DIG__==24 &&
               __FLT_MAX_EXP__==128,"Edit gamma construction requires IEEE binary32");

static int apart(const void *a, size_t n, const void *b, size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m &&
           (x+n<=y || y+m<=x);
}
int af_edit_gamma_table(const uint32_t *axis, const uint32_t *values,
                         const int32_t *contrast, AfEditGammaWork *work,
                         uint16_t *output, AfGridProgress progress, void *context) {
    const size_t bytes=AF_EDIT_GAMMA_TABLE_ENTRIES*2u;
    if (!apart(axis,512,work,sizeof(*work)) || !apart(axis,512,output,bytes) ||
        !apart(values,512,work,sizeof(*work)) || !apart(values,512,output,bytes) ||
        !apart(contrast,4100,work,sizeof(*work)) || !apart(contrast,4100,output,bytes) ||
        !apart(work,sizeof(*work),output,bytes) || axis[0] || values[0]) return AF_INVALID;
    for (unsigned i=0;i<128;++i)
        if (axis[i]>INT32_MAX || values[i]>262143 ||
            (i && (axis[i]<=axis[i-1] || values[i]<values[i-1]))) return AF_INVALID;
    for (unsigned i=0;i<1025;++i) if (contrast[i]<0) return AF_INVALID;
    if (progress && progress(context,0,65536)) return AF_GRID_CANCELLED;

    unsigned right=0;
    work->table[32768]=0;
    for (unsigned index=1;index<32768;++index) {
        uint32_t sample=index*128u;
        while (right<128 && axis[right]<=sample) ++right;
        unsigned left=right?right-1:0,upper=right<128?right:127;
        uint32_t width=axis[upper]-axis[left];
        float value=(float)values[left]-(float)values[upper];
        value=value*(float)((int64_t)axis[upper]-sample);
        value=value/(float)(width?width:1);
        value=value+(float)values[upper];
        if (!width) value=(float)values[left];
        if (!__builtin_isfinite(value) || value<0 || value>=262144.0f) return AF_INVALID;
        uint32_t integer=(uint32_t)value,shifted=integer>>2;
        unsigned at=integer>>8;if (at>1023) at=1023;
        unsigned next=at<1023?at+1:1023;
        float low=(float)contrast[at],high=(float)contrast[next];
        float fraction=(float)((int64_t)shifted-(int64_t)(integer>>8)*64)*(1.0f/64.0f);
        /* 差先按float32舍入，乘加按完整精度完成后一次舍入到float32。 */
        float mapped=(float)((double)(high-low)*(double)fraction+(double)low);
        if (!__builtin_isfinite(mapped) || mapped<0 || mapped>=4294967296.0f) return AF_INVALID;
        shifted=(uint32_t)mapped;
        work->table[32768+index]=(uint16_t)(shifted>>2);
        if (!(index&2047u) && progress && progress(context,index,65536)) return AF_GRID_CANCELLED;
    }
    if (progress && progress(context,32768,65536)) return AF_GRID_CANCELLED;
    for (unsigned i=0;i<32768;++i) {
        work->table[i]=(uint16_t)(-(int32_t)work->table[65535-i]);
        unsigned completed=32769+i;
        if (!(completed&2047u) && progress && progress(context,completed,65536)) return AF_GRID_CANCELLED;
    }
    for (unsigned i=0;i<65536;++i) output[i]=work->table[i];
    return AF_OK;
}
static int inverse_valid(const int16_t *gamma, AfEditGammaWork *work,
                          uint16_t *output, size_t count) {
    if (!apart(gamma,131072,work,sizeof(*work)) || !apart(gamma,131072,output,count*2) ||
        !apart(work,sizeof(*work),output,count*2)) return 0;
    for (unsigned i=32769;i<65536;++i) if (gamma[i]<gamma[i-1]) return 0;
    return 1;
}
int af_edit_gamma_main_inverse(const int16_t *gamma, uint16_t initial_zero,
                               AfEditGammaWork *work, uint16_t *output,
                               AfGridProgress progress, void *context) {
    if (!inverse_valid(gamma,work,output,65536)) return AF_INVALID;
    if (progress && progress(context,0,65536)) return AF_GRID_CANCELLED;
    work->table[0]=initial_zero;
    unsigned next=0;
    for (unsigned level=0;level<32768;++level) {
        while (next<32767 && gamma[32769+next]<(int)level) ++next;
        work->table[32768+level]=(uint16_t)next;
        /* 原负半表覆盖中心项；非零/负值首段也保持同一先后次序。 */
        work->table[32768-level]=(uint16_t)(-(int32_t)next);
        unsigned completed=2*(level+1);
        if (!(completed&2047u) && progress && progress(context,completed,65536))
            return AF_GRID_CANCELLED;
    }
    for (unsigned i=0;i<65536;++i) output[i]=work->table[i];
    return AF_OK;
}
int af_edit_gamma_secondary_inverse(const int16_t *gamma, AfEditGammaWork *work,
                                    uint16_t *output, AfGridProgress progress, void *context) {
    if (!inverse_valid(gamma,work,output,16384)) return AF_INVALID;
    if (progress && progress(context,0,16384)) return AF_GRID_CANCELLED;
    unsigned next=0;
    for (unsigned level=0;level<16384;++level) {
        while (next<32767 && gamma[32769+next]<(int)level) ++next;
        work->table[level]=(uint16_t)next;
        unsigned completed=level+1;
        if (!(completed&1023u) && progress && progress(context,completed,16384))
            return AF_GRID_CANCELLED;
    }
    for (unsigned i=0;i<16384;++i) output[i]=work->table[i];
    return AF_OK;
}
