#include "af_edit_matrix_table.h"
#ifdef __FAST_MATH__
#error "Edit matrix reference requires explicit float rounding"
#endif
#pragma STDC FP_CONTRACT OFF
_Static_assert(sizeof(float)==4 && __FLT_RADIX__==2 && __FLT_MANT_DIG__==24 &&
               __FLT_MAX_EXP__==128,"Edit matrix reference requires IEEE binary32");
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static uint16_t h(const uint8_t *p) {return (uint16_t)((uint16_t)p[0]|(uint16_t)p[1]<<8);}
static uint32_t w(const uint8_t *p) {
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static void put_h(uint8_t *p,uint16_t value) {
    p[0]=(uint8_t)value;p[1]=(uint8_t)(value>>8);
}
static void put_f(uint8_t *p,float value) {
    union {float f;uint32_t u;} bits;bits.f=value;
    for (unsigned i=0;i<4;++i) p[i]=(uint8_t)(bits.u>>(8*i));
}
static float f(const uint8_t *p) {
    union {float f;uint32_t u;} bits;bits.u=w(p);return bits.f;
}
static float coefficient(uint16_t value) {
    if (value&0x8000u) return -(float)((((uint32_t)value>>2)&0x3ffeu)^0x3fffu)*(1.0f/1024.0f);
    return (float)(((uint32_t)value>>2)&0x3fffu)*(1.0f/1024.0f);
}
int af_edit_matrix_table(const uint8_t *payload,const AfEditMatrixDomain *domain,
                          AfEditMatrixWork *work,uint8_t *config,float *table,
                          AfGridProgress progress,void *context) {
    const size_t table_bytes=AF_EDIT_MATRIX_TABLE_ENTRIES*4u;
    if (!apart(payload,276,work,sizeof(*work)) || !apart(payload,276,config,552) ||
        !apart(payload,276,table,table_bytes) || !apart(domain,sizeof(*domain),work,sizeof(*work)) ||
        !apart(domain,sizeof(*domain),config,552) || !apart(domain,sizeof(*domain),table,table_bytes) ||
        !apart(work,sizeof(*work),config,552) || !apart(work,sizeof(*work),table,table_bytes) ||
        !apart(config,552,table,table_bytes) || domain->schema!=1 ||
        domain->calibration_identity!=1 || domain->output_gamut_mode!=3) return AF_INVALID;

    uint32_t words[69];uint16_t angles[16];
    for (unsigned i=0;i<69;++i) words[i]=w(payload+4*i);
    angles[0]=(uint16_t)((words[0]>>11)&1023u);angles[1]=(uint16_t)(words[0]&1023u);
    for (unsigned i=1;i<5;++i) {
        angles[2+3*(i-1)]=(uint16_t)(words[i]>>22);
        angles[3+3*(i-1)]=(uint16_t)((words[i]>>11)&1023u);
        angles[4+3*(i-1)]=(uint16_t)(words[i]&1023u);
    }
    angles[14]=(uint16_t)(words[5]>>22);angles[15]=(uint16_t)((words[5]>>11)&1023u);
    for (unsigned i=1;i<16;++i) if (angles[i]<=angles[i-1]) return AF_INVALID;
    float diagonal[3]={coefficient((uint16_t)(words[62]>>16)),coefficient((uint16_t)words[62]),
                       coefficient((uint16_t)(words[63]>>16))};
    if (diagonal[0]!=diagonal[2]) return AF_INVALID;
    if (progress && progress(context,0,1024)) return AF_GRID_CANCELLED;

    uint8_t *cfg=work->config;
    put_h(cfg,(uint16_t)((words[0]>>24)&1u));put_h(cfg+2,(uint16_t)((words[0]>>25)&1u));
    put_h(cfg+4,(uint16_t)((words[0]>>23)&1u));
    for (unsigned i=0;i<16;++i) put_h(cfg+6+2*i,angles[i]);
    unsigned mode=(words[0]>>26)&3u;put_h(cfg+0x26,(uint16_t)mode);
    for (unsigned i=0;i<96;++i) put_f(cfg+0x28+4*i,coefficient(h(payload+24+2*(i^1u))));
    for (unsigned i=0;i<16;++i) {
        uint16_t norm=(uint16_t)((words[54+i/2]>>(i%2?2:18))&4095u);
        put_h(cfg+0x1e8+2*i,norm);
    }
    for (unsigned i=0;i<3;++i) put_f(cfg+0x208+4*i,diagonal[i]);
    uint8_t scales[16];scales[0]=(uint8_t)(words[63]>>8);scales[1]=(uint8_t)words[63];
    for (unsigned i=0;i<12;++i) scales[i+2]=(uint8_t)(words[64+i/4]>>(24-8*(i%4)));
    scales[14]=(uint8_t)(words[67]>>24);scales[15]=(uint8_t)(words[67]>>16);
    for (unsigned i=0;i<16;++i) put_f(cfg+0x1a8+4*i,(float)scales[i]*(1.0f/128.0f));
    put_f(cfg+0x214,(float)(words[67]&65535u)*(1.0f/32.0f));
    put_f(cfg+0x218,(float)(words[68]>>16)*(1.0f/32.0f));
    put_f(cfg+0x21c,(float)(words[68]&65535u)*(1.0f/32.0f));
    put_h(cfg+0x220,(uint16_t)(words[0]>>31));put_h(cfg+0x222,(uint16_t)((words[0]>>30)&1u));
    put_h(cfg+0x224,(uint16_t)((words[0]>>28)&3u));
    cfg[0x226]=domain->trailing_padding[0];cfg[0x227]=domain->trailing_padding[1];

    double factor=1.0/(4096.0*(double)(2u<<mode));
    for (unsigned sector=0;sector<1024;++sector) {
        unsigned right=0;while (right<16 && angles[right]<=sector) ++right;
        unsigned left=(right+15)%16;right%=16;
        unsigned a=angles[left],b=angles[right];if (b<=a) b+=1024;
        unsigned t=sector>=a?sector:sector+1024;
        double norm=(double)h(cfg+0x1e8+2*left);
        double wl=(double)(b-t)*norm*factor,wr=(double)(t-a)*norm*factor;
        double sl=(double)f(cfg+0x1a8+4*left),sr=(double)f(cfg+0x1a8+4*right);
        double q[6],negative[6],z[6];
        for (unsigned row=0;row<6;++row) {
            double cl=(double)f(cfg+0x28+4*(16*row+left));
            double cr=(double)f(cfg+0x28+4*(16*row+right));
            q[row]=cl*wl+cr*wr;
            /* 负矩阵项在端点先取负，保留相消处的原始零符号。 */
            negative[row]=(-cl)*wl+(-cr)*wr;
            z[row]=(cl*sl)*wl+(cr*sr)*wr;
        }
        double linear[9]={q[0]+q[1]+diagonal[0],negative[0],negative[1],negative[2],
                          q[2]+q[3]+diagonal[1],negative[3],negative[4],negative[5],q[4]+q[5]+diagonal[0]};
        double quadratic[9]={-z[0]-z[1],z[0],z[1],z[2],-z[2]-z[3],z[3],z[4],z[5],-z[4]-z[5]};
        for (unsigned i=0;i<9;++i) {
            work->table[18*sector+i]=(float)linear[i];
            work->table[18*sector+9+i]=(float)quadratic[i];
        }
        unsigned completed=sector+1;
        if (!(completed&31u) && progress && progress(context,completed,1024)) return AF_GRID_CANCELLED;
    }
    for (unsigned i=0;i<552;++i) config[i]=cfg[i];
    for (unsigned i=0;i<AF_EDIT_MATRIX_TABLE_ENTRIES;++i) table[i]=work->table[i];
    return AF_OK;
}
