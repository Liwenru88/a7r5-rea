#include "af_gamma406.h"
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static uint32_t read32(const uint8_t *p) {
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static void write32(uint8_t *p,uint32_t v) {
    for (unsigned i=0;i<4;++i) p[i]=(uint8_t)(v>>(8*i));
}
int af_gamma406_axis(const void *source,uint32_t *output) {
    /* 原CP常量0x413d8c/0x413da4；源分段宽度和起点，非129点均匀轴。 */
    static const uint16_t span[12]={32,32,64,128,256,512,1024,2048,4096,8192,16384,32768};
    static const uint16_t start[12]={0,32,64,128,256,512,1024,2048,4096,8192,16384,32768};
    const uint8_t *record=source;uint32_t axis[129]={0},previous=0;unsigned count=0;
    if (!apart(source,576,output,516)) return AF_INVALID;
    for (unsigned i=0;i<129;++i) {
        uint32_t y=read32(record+4*i);
        if (y>0x3ffffu || (i==0 && y) || (i && y<previous)) return AF_INVALID;
        previous=y;
    }
    if (!previous) return AF_INVALID;
    for (unsigned i=0;i<12;++i) {
        unsigned exponent=record[0x204+i],step,n;
        if (exponent>=16) return AF_INVALID;
        step=span[i]>>exponent;
        if (!step) return AF_INVALID;
        n=span[i]/step;
        if (n>128-count) return AF_INVALID;
        for (unsigned j=1;j<=n;++j) {
            unsigned x=start[i]+j*step;
            axis[++count]=x>65535?65535:x;
            if (axis[count]<=axis[count-1]) return AF_INVALID;
        }
    }
    if (count!=128 || axis[128]!=65535) return AF_INVALID;
    for (unsigned i=0;i<129;++i) output[i]=axis[i];
    return AF_OK;
}
int af_gamma406_locate(const uint32_t *axis,uint32_t code,AfGamma406Span *out) {
    unsigned left=0,right=128;AfGamma406Span answer;
    if (code>65535 || !apart(axis,516,out,sizeof(*out)) || axis[0] || axis[128]!=65535) return AF_INVALID;
    for (unsigned i=1;i<129;++i) if (axis[i]<=axis[i-1] || axis[i]>65535) return AF_INVALID;
    while (right-left>1) {
        unsigned middle=(left+right)/2;
        if (axis[middle]<=code) left=middle;
        else right=middle;
    }
    answer=(AfGamma406Span){left,right,code-axis[left],axis[right]-axis[left]};
    *out=answer;return AF_OK;
}
int af_gamma406_replace(const void *source,const uint32_t *curve,void *destination) {
    const uint8_t *record=source;uint8_t *output=destination;uint32_t axis[129];
    if (!apart(source,576,destination,576) || !apart(curve,516,destination,576) ||
        af_gamma406_axis(source,axis)!=AF_OK || !curve || curve[0] || !curve[128]) return AF_INVALID;
    for (unsigned i=0;i<129;++i) if (curve[i]>0x3ffffu || (i && curve[i]<curve[i-1])) return AF_INVALID;
    for (unsigned i=0;i<576;++i) output[i]=record[i];
    for (unsigned i=0;i<129;++i) write32(output+4*i,curve[i]);
    write32(output+0x220,curve[128]);return AF_OK;
}
