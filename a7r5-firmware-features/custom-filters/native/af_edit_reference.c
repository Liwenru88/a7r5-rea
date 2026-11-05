/* 独立按公开整数公式实现；数值依据及原始捕获摘要见测试夹具。 */
#include "af_edit_reference.h"
#ifdef __FAST_MATH__
#error "Edit reference requires finite checks and explicit float32 rounding"
#endif
#pragma STDC FP_CONTRACT OFF
_Static_assert(sizeof(float)==4 && __FLT_RADIX__==2 && __FLT_MANT_DIG__==24 &&
               __FLT_MAX_EXP__==128,"Edit reference requires IEEE binary32");

/* AArch64显式单条FMADD，避免freestanding构建退化为libm外部符号。 */
static float rounded_fma(float a, float b, float c) {
#if defined(__aarch64__) || defined(__arm64__)
    float value;
    __asm__("fmadd %s0, %s1, %s2, %s3" : "=w"(value) : "w"(a),"w"(b),"w"(c));
    return value;
#else
    return __builtin_fmaf(a,b,c);
#endif
}
static int finite32(float value) {return __builtin_isfinite(value);}
static float clip(float value, float low, float high) {
    return value<low?low:value>high?high:value;
}

static int apart(const void *a, size_t n, const void *b, size_t m) {
    uintptr_t x=(uintptr_t)a, y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m &&
           (x+n<=y || y+m<=x);
}
static int valid_io(const void *input, size_t pixels, uint16_t *output) {
    return pixels && pixels<=AF_EDIT_REF_MAX_PIXELS &&
           apart(input,pixels*6,output,pixels*6);
}
static int64_t floor_div8192(int64_t value) {
    return value>=0?value/8192:-((-value+8191)/8192);
}
static uint16_t rgb_code(int64_t value) {
    return (uint16_t)(value<0?0:value>16383?16383:value);
}
int af_edit_ref_main_gamma(const uint16_t *table, size_t entries,
                          const uint16_t *rgb, size_t pixels, uint16_t *output) {
    if (entries!=AF_EDIT_REF_MAIN_ENTRIES || !valid_io(rgb,pixels,output) ||
        !apart(table,entries*2,output,pixels*6)) return AF_INVALID;
    for (size_t i=0;i<pixels*3;++i) if (rgb[i]>32767) return AF_INVALID;
    for (size_t i=0;i<pixels*3;++i) output[i]=table[32768u+rgb[i]];
    return AF_OK;
}
int af_edit_ref_rgb_ycc(const int16_t *rgb, size_t pixels,
                       const int16_t *coefficients, const int16_t *luma,
                       unsigned keep_unclipped, uint16_t *output) {
    if (!valid_io(rgb,pixels,output) || keep_unclipped>1 ||
        !apart(coefficients,16,output,pixels*6) ||
        !apart(luma,6,output,pixels*6)) return AF_INVALID;
    int mixed[4];float gains[4];
    for (unsigned i=0;i<4;++i) {
        unsigned v=((uint16_t)coefficients[i]>>2)&511u;
        mixed[i]=(int)v-(v>255?512:0);
        gains[i]=(float)(((uint16_t)coefficients[i+4]>>3)&255u);
    }
    for (size_t i=0;i<pixels;++i) {
        const int16_t *p=rgb+3*i;
        int dr=(int)p[0]-p[1], db=(int)p[2]-p[1];
        float cb=rounded_fma((float)dr,(float)mixed[dr>=0?1:3]/256.0f,(float)db);
        float cr=rounded_fma((float)db,(float)mixed[db>=0?0:2]/256.0f,(float)dr);
        cr=cr*0.5f*gains[cr>=0?1:3]*(1.0f/64.0f);
        cb=cb*0.5f*gains[cb>=0?0:2]*(1.0f/64.0f);
        if (!keep_unclipped) {
            cr=clip(cr,-8192.0f,8191.0f);
            cb=clip(cb,-8192.0f,8191.0f);
        }
        int64_t y=(int64_t)p[0]*luma[0]+(int64_t)p[1]*luma[1]+(int64_t)p[2]*luma[2];
        output[3*i]=(uint16_t)((uint64_t)floor_div8192(y)&65535u);
        output[3*i+1]=(uint16_t)clip(cr+32768.0f,0.0f,65535.0f);
        output[3*i+2]=(uint16_t)clip(cb+32768.0f,0.0f,65535.0f);
    }
    return AF_OK;
}
static float y_value(uint16_t input, const uint16_t *table,
                     const AfEditRefYGamma *p, int divisor) {
    float black=(float)(-(p->black_level/4))*63.998047f;
    float normalized=((float)table[input]-black)*512.0f;
    if (normalized<0) normalized=0;
    float value=rounded_fma(normalized,1.0f/(float)divisor,-(float)p->pivot);
    return rounded_fma(value,p->gain,(float)p->pivot);
}
int af_edit_ref_y_gamma(const uint16_t *table, size_t entries,
                       const AfEditRefYGamma *p,
                       const uint16_t *ycc, size_t pixels, uint16_t *output) {
    if (entries!=AF_EDIT_REF_Y_ENTRIES || !valid_io(ycc,pixels,output) ||
        !apart(table,entries*2,output,pixels*6) ||
        !apart(p,sizeof(*p),output,pixels*6) || !finite32(p->gain)) return AF_INVALID;
    int divisor=512-(int)p->white_level+p->black_level/4;
    if (!divisor) return AF_INVALID;
    /* 预检最后一个像素失败时也不能发布先前像素。 */
    for (size_t i=0;i<pixels;++i)
        if (ycc[3*i]>32767 || !finite32(y_value(ycc[3*i],table,p,divisor))) return AF_INVALID;
    for (size_t i=0;i<pixels;++i) {
        float value=y_value(ycc[3*i],table,p,divisor);
        output[3*i]=(uint16_t)clip(value,0.0f,16383.0f);
        output[3*i+1]=ycc[3*i+1];output[3*i+2]=ycc[3*i+2];
    }
    return AF_OK;
}
int af_edit_ref_ycc_rgb(const uint16_t *ycc, size_t pixels, uint16_t *output) {
    if (!valid_io(ycc,pixels,output)) return AF_INVALID;
    for (size_t i=0;i<pixels;++i) {
        int64_t y=(int64_t)ycc[3*i]*10000, cr=(int)ycc[3*i+1]-32768,
                cb=(int)ycc[3*i+2]-32768;
        output[3*i]=rgb_code((y+cr*14020)/10000);
        output[3*i+1]=rgb_code((y-cr*7141-cb*3441)/10000);
        output[3*i+2]=rgb_code((y+cb*17720)/10000);
    }
    return AF_OK;
}

static float absolute(float value) {return value<0?-value:value;}
static size_t column(size_t x, int offset, size_t width) {
    if (offset<0 && x<(size_t)-offset) return 0;
    size_t value=offset<0?x-(size_t)-offset:x+(size_t)offset;
    return value>=width?width-1:value;
}
static float smooth(const uint16_t *row, size_t x, size_t width, unsigned channel) {
    float adjacent=(float)row[3*column(x,-1,width)+channel]+row[3*column(x,1,width)+channel];
    float value=rounded_fma((float)row[3*x+channel],14.0f,
                            (float)row[3*column(x,-2,width)+channel]);
    value=value+(float)row[3*column(x,2,width)+channel];
    return rounded_fma(adjacent,8.0f,value)*(1.0f/32.0f);
}
static int matrix_pixel(const AfEditRefMatrix *p, const uint16_t *row,
                         size_t x, size_t width, uint16_t out[3]) {
    float rgb[3],filtered[3],light[3],color[3];
    for (unsigned c=0;c<3;++c) {
        rgb[c]=(float)row[3*x+c];
        filtered[c]=(p->luma_smooth || p->chroma_smooth)?smooth(row,x,width,c):rgb[c];
        light[c]=p->luma_smooth?filtered[c]:rgb[c];
        color[c]=p->chroma_smooth?filtered[c]:rgb[c];
    }
    float y=light[0]*109.0f;
    y=rounded_fma(light[1],366.0f,y);y=rounded_fma(light[2],37.0f,y)*(1.0f/512.0f);
    float dr=color[0]-y, db=color[2]-y;
    if (p->scale_chroma) {dr=dr*0.875f;db=db*0.5f;}
    float ar=absolute(dr), ab=absolute(db), minor=ar<ab?ar:ab, major=ar>ab?ar:ab;
    float ratio=(minor*512.0f)/(major==0?1.0f:major);
    unsigned index=(unsigned)(ratio+0.5f);if (index>511) index=511;
    int base=ar<=ab?(dr<0?(db<0?512:-1024):(db<0?-512:0)):
                      (dr<0?(db<0?-768:768):(db<0?256:-256));
    unsigned sector=(unsigned)absolute(p->angles[index]+(float)base);
    if (sector>1023) sector=1023;
    const float *table=p->table+18*sector;
    for (unsigned c=0;c<3;++c) {
        const float *q=table+3*c;
        float value=rounded_fma(q[1],rgb[1],q[0]*rgb[0]);
        value=rounded_fma(q[2],rgb[2],value);
        if (p->quadratic) {
            q=table+9+3*c;
            float nonlinear=rounded_fma(q[1],rgb[1]*rgb[1],q[0]*(rgb[0]*rgb[0]));
            nonlinear=rounded_fma(q[2],rgb[2]*rgb[2],nonlinear)*(1.0f/16384.0f);
            float summed=nonlinear+value;
            if (!finite32(nonlinear) || !finite32(summed)) return AF_INVALID;
            if (nonlinear>=0) {
                if (nonlinear>=p->thresholds[c]) value=summed-p->thresholds[c];
                else if (nonlinear<=-p->thresholds[c]) value=summed+p->thresholds[c];
            }
        }
        if (!finite32(value)) return AF_INVALID;
        out[c]=(uint16_t)clip(value,0,16383);
    }
    return AF_OK;
}
int af_edit_ref_matrix16(const AfEditRefMatrix *p, const uint16_t *rgb,
                         size_t width, size_t height, uint16_t *output) {
    if (!width || width>AF_EDIT_REF_MAX_PIXELS || !height || height>AF_EDIT_REF_MAX_PIXELS/width)
        return AF_INVALID;
    size_t pixels=width*height;
    if (!valid_io(rgb,pixels,output) || !apart(p,sizeof(*p),output,pixels*6) ||
        p->enabled>1 || p->luma_smooth>1 || p->chroma_smooth>1 || p->scale_chroma>1 || p->quadratic>1)
        return AF_INVALID;
    if (!p->enabled) {
        for (size_t i=0;i<pixels*3;++i) output[i]=rgb[i];
        return AF_OK;
    }
    if (((p->luma_smooth || p->chroma_smooth) && width<5) ||
        p->table_entries!=1024u*18u || p->angle_entries!=512 ||
        !apart(p->table,p->table_entries*4,output,pixels*6) ||
        !apart(p->angles,p->angle_entries*4,output,pixels*6)) return AF_INVALID;
    for (size_t i=0;i<p->table_entries;++i) if (!finite32(p->table[i])) return AF_INVALID;
    for (size_t i=0;i<p->angle_entries;++i)
        if (!finite32(p->angles[i]) || p->angles[i]<0 || p->angles[i]>1023) return AF_INVALID;
    for (unsigned i=0;i<3;++i) if (!finite32(p->thresholds[i])) return AF_INVALID;
    uint16_t value[3];
    for (size_t y=0;y<height;++y) for (size_t x=0;x<width;++x)
        if (matrix_pixel(p,rgb+3*y*width,x,width,value)!=AF_OK) return AF_INVALID;
    for (size_t y=0;y<height;++y) for (size_t x=0;x<width;++x) {
        (void)matrix_pixel(p,rgb+3*y*width,x,width,value);
        for (unsigned c=0;c<3;++c) output[3*(y*width+x)+c]=value[c];
    }
    return AF_OK;
}
static int area_pixel(const AfEditRefArea *p, const uint16_t input[3], uint16_t out[3]) {
    const float *c=p->coefficients;
    float cr=(float)((int)input[1]-32768),cb=(float)((int)input[2]-32768);
    float x=c[0]+cr,y=c[1]+cb;
    float a=rounded_fma(y,c[6],x*c[4]),b=rounded_fma(c[7],y,c[5]*x);
    if (!finite32(a) || !finite32(b)) return AF_INVALID;
    a=a<0?0:a;b=b<0?0:b;float u=a<b?a:b;
    x=c[2]+cr;y=c[3]+cb;
    a=rounded_fma(y,c[10],x*c[8]);b=rounded_fma(c[11],y,c[9]*x);
    if (!finite32(a) || !finite32(b)) return AF_INVALID;
    a=a<0?0:a;b=b<0?0:b;float v=a<b?a:b;
    if (p->selector) {u=u<v?u:v;v=0;}
    out[0]=input[0];
    for (unsigned channel=1;channel<3;++channel) {
        unsigned k=11+channel;
        float first=u*c[k],second=v*c[k+2];
        double value=(double)(channel==1?cr:cb)+32768.0+(double)first;
        value=value+(double)second;
        if (!__builtin_isfinite(value) || value< -9223372036854775808.0 || value>=9223372036854775808.0)
            return AF_INVALID;
        out[channel]=(uint16_t)((uint64_t)(int64_t)value&65535u);
    }
    return AF_OK;
}
int af_edit_ref_area(const AfEditRefArea *p, const uint16_t *ycc,
                     size_t pixels, uint16_t *output) {
    if (!valid_io(ycc,pixels,output) || !apart(p,sizeof(*p),output,pixels*6) || p->selector>1)
        return AF_INVALID;
    for (unsigned i=0;i<16;++i) if (!finite32(p->coefficients[i])) return AF_INVALID;
    uint16_t value[3];
    for (size_t i=0;i<pixels;++i) if (area_pixel(p,ycc+3*i,value)!=AF_OK) return AF_INVALID;
    for (size_t i=0;i<pixels;++i) {
        (void)area_pixel(p,ycc+3*i,value);
        for (unsigned c=0;c<3;++c) output[3*i+c]=value[c];
    }
    return AF_OK;
}
int af_edit_ref_chroma_controls(const AfEditRefChromaSource *s,
                                const AfEditRefChromaTables *t, AfEditRefChroma *output) {
    if (!apart(s,sizeof(*s),output,sizeof(*output)) || !apart(t,sizeof(*t),output,sizeof(*output)) ||
        t->inverse_secondary_entries!=16384 || t->inverse_main_entries!=65536 ||
        t->main_entries!=65536 || t->secondary_entries!=65536 || s->gain_raw<=0 ||
        !apart(t->inverse_secondary,32768,output,sizeof(*output)) ||
        !apart(t->inverse_main,131072,output,sizeof(*output)) ||
        !apart(t->main_gamma,131072,output,sizeof(*output)) ||
        !apart(t->secondary_gamma,131072,output,sizeof(*output))) return AF_INVALID;
    double exposure=(double)s->exposure_300/300.0,gain=(double)s->gain_raw/64.0;
    int slope=s->slopes[0],threshold=s->thresholds[0];
    if (exposure>=-2 && exposure< -1) {
        slope=(int)((double)s->slopes[2]+((double)s->slopes[1]-s->slopes[2])*(exposure+2));
        threshold=(int)((double)s->thresholds[2]+((double)s->thresholds[1]-s->thresholds[2])*(exposure+2));
    } else if (exposure>=-1 && exposure<0) {
        slope=(int)((double)s->slopes[1]+((double)s->slopes[0]-s->slopes[1])*(exposure+1));
        threshold=(int)((double)s->thresholds[1]+((double)s->thresholds[0]-s->thresholds[1])*(exposure+1));
    }
    if (threshold<0) return AF_INVALID;
    int inverse_secondary=t->inverse_secondary[threshold>16383?16383:threshold];
    int inverse_main=t->inverse_main[inverse_secondary+32768];
    double raw_code=gain*inverse_main;
    if (raw_code< -32768) return AF_INVALID;
    int code=raw_code>32767?32767:(int)raw_code;
    int gamma=t->main_gamma[32768+code];
    int cutoff=t->secondary_gamma[32768+gamma];
    double adjustment=exposure>=-1 && exposure<=0?-exposure:
                      exposure>=-2 && exposure<=-1?exposure+2:0;
    AfEditRefChroma result;
    result.high_cutoff=cutoff+(int)(adjustment*-1200);
    result.low_cutoff=threshold?(int)((double)cutoff*s->low_threshold/threshold):0;
    result.high_slope=(int)((double)slope/gain)+(int)(adjustment*150);
    result.low_slope=(int)((double)s->low_slope/gain);
    *output=result;return AF_OK;
}
static int64_t floor_div4096(int64_t value) {
    return value>=0?value/4096:-((-value+4095)/4096);
}
int af_edit_ref_chroma(const AfEditRefChroma *p, const uint16_t *ycc,
                       size_t pixels, uint16_t *output) {
    if (!valid_io(ycc,pixels,output) || !apart(p,sizeof(*p),output,pixels*6)) return AF_INVALID;
    for (size_t i=0;i<pixels;++i) {
        int y=ycc[3*i]<32768?(int)ycc[3*i]:(int)ycc[3*i]-65536;
        int64_t amount=0;
        if (y<p->low_cutoff) amount=((int64_t)p->low_cutoff-y)*p->low_slope;
        else if (y>p->high_cutoff) amount=((int64_t)y-p->high_cutoff)*p->high_slope;
        int64_t factor=255-floor_div4096(amount);
        factor=factor<0?0:factor>255?255:factor;
        output[3*i]=(uint16_t)(y<0?0:y);
        for (unsigned c=1;c<3;++c) {
            int64_t chroma=((int)ycc[3*i+c]-32768)*factor;
            output[3*i+c]=(uint16_t)((chroma/256+32768)&65535);
        }
    }
    return AF_OK;
}
