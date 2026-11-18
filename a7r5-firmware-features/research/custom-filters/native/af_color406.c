#include "af_color406.h"
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static int16_t half(int32_t value) {
    uint32_t v=(uint32_t)value&65535u;
    return (int16_t)(v<32768?(int32_t)v:(int32_t)v-65536);
}
int af_color406_matrix(const uint16_t *raw,const uint16_t *cal,int16_t *out) {
    if (!apart(raw,36,cal,6) || !apart(raw,36,out,54) || !apart(cal,6,out,54)) return AF_INVALID;
    for (unsigned e=0;e<3;++e) {
        const uint16_t *p=raw+e*6;int16_t *q=out+e*9;
        int32_t a=p[0],b=p[1],c=p[2],d=p[3],f=p[4],g=p[5];
        q[0]=half(cal[0]+a+b);q[1]=half(-a);q[2]=half(-b);
        q[3]=half(-c);q[4]=half(cal[1]+c+d);q[5]=half(-d);
        q[6]=half(-f);q[7]=half(-g);q[8]=half(cal[2]+f+g);
    }
    return AF_OK;
}
int af_color406_primary(const uint16_t *raw,const int16_t *adjust,int16_t *out) {
    if (!apart(raw,48,adjust,16) || !apart(raw,48,out,48) || !apart(adjust,16,out,48)) return AF_INVALID;
    for (unsigned i=0;i<8;++i) {
        int32_t base=(int32_t)raw[i]+adjust[i];
        out[i]=half(base);out[8+i]=half(base+raw[8+i]);out[16+i]=half(base+raw[16+i]);
    }
    return AF_OK;
}
int af_color406_secondary(const uint16_t *raw,const int16_t *adjust,const uint16_t *metadata,int16_t *out) {
    if (!apart(raw,16,adjust,16) || !apart(raw,16,metadata,16) || !apart(adjust,16,metadata,16) ||
        !apart(raw,16,out,32) || !apart(adjust,16,out,32) || !apart(metadata,16,out,32)) return AF_INVALID;
    for (unsigned i=0;i<8;++i) {out[i]=half((int32_t)raw[i]+adjust[i]);out[8+i]=half(metadata[i]);}
    return AF_OK;
}
int af_color406_add(const int16_t *source,const int16_t *delta,uint32_t count,int16_t *out) {
    size_t bytes=(size_t)count*2;
    if ((count!=8 && count!=24 && count!=27) || !apart(source,bytes,delta,bytes) ||
        !apart(source,bytes,out,bytes) || !apart(delta,bytes,out,bytes)) return AF_INVALID;
    for (unsigned i=0;i<count;++i) out[i]=half((int32_t)source[i]+delta[i]);
    return AF_OK;
}
static int32_t floor_q8(int32_t value) {return value>=0?value/256:-((-value+255)/256);}
int af_color406_blend(const int16_t *e,const uint16_t *w,int16_t *out) {
    if (!apart(e,48,w,8) || !apart(e,48,out,16) || !apart(w,8,out,16)) return AF_INVALID;
    for (unsigned i=0;i<4;++i) if (w[i]>256) return AF_INVALID;
    if ((uint32_t)w[1]+w[2]>256) return AF_INVALID;
    for (unsigned i=0;i<8;++i) {
        int32_t a=e[i],b=e[i+8],c=e[i+16];
        int32_t first=half(a+floor_q8((b-a)*w[0]));
        int32_t second=half(a+floor_q8((b-a)*w[1]+(c-a)*w[2]));
        int32_t v=first*(256-w[3])+second*w[3];
        out[i]=half((v+(v>0?128:-128))/256);
    }
    return AF_OK;
}
int af_color406_adjust(const uint8_t *raw,int16_t *out) {
    if (!apart(raw,8,out,16)) return AF_INVALID;
    for (unsigned i=0;i<8;++i) out[i]=(int16_t)(i<4 && raw[i]>=128?(int)raw[i]-256:raw[i]);
    return AF_OK;
}
static int32_t round_q8(int32_t value) {return value>=0?(value+128)/256:-((-value+128)/256);}
static int16_t saturated(int32_t value) {return (int16_t)(value< -32768?-32768:value>32767?32767:value);}
int af_color406_matrix_blend(const int16_t *e,const uint16_t *w,int16_t *out) {
    if (!apart(e,54,w,8) || !apart(e,54,out,18) || !apart(w,8,out,18)) return AF_INVALID;
    for (unsigned i=0;i<4;++i) if (w[i]>256) return AF_INVALID;
    if ((uint32_t)w[1]+w[2]>256) return AF_INVALID;
    for (unsigned i=0;i<9;++i) {
        int32_t a=e[i],b=e[i+9],c=e[i+18];
        int32_t first=saturated(a+round_q8((b-a)*w[0]));
        int32_t second=saturated(a+round_q8((b-a)*w[1]+(c-a)*w[2]));
        out[i]=saturated(round_q8(first*(256-w[3])+second*w[3]));
    }
    return AF_OK;
}
