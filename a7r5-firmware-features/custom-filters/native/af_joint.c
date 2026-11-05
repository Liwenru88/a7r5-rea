/* 本包六项矩阵展开和Gamma整数次序；不推断像素域或CP颜色模型。 */
#include "af_joint.h"
const uint8_t af_joint_cp_sha256[32]={0x18,0xb2,0x65,0xc5,0x89,0xeb,0x42,0x01,0xd3,0xb3,0x68,0x08,0x57,0xd8,0x97,0xb6,
    0x93,0xd0,0x6c,0x6d,0xd4,0x91,0xd7,0x95,0xdb,0xb3,0xa6,0x16,0xd6,0x18,0x2e,0x97};
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static int gamma_valid(const uint32_t *g) {
    if (!g || g[0] || !g[128]) return 0;
    for (unsigned i=0;i<129;++i) if (g[i]>0x3ffffu || (i && g[i]<g[i-1])) return 0;
    return 1;
}
int af_joint_valid(const AfJointRecipe *r) {
    if (!r || !gamma_valid(r->gamma)) return AF_INVALID;
    for (unsigned i=0;i<18;++i) if (r->matrix[i]<-1024 || r->matrix[i]>1024) return AF_INVALID;
    for (unsigned i=0;i<24;++i) if (r->cc1[i]<-1024 || r->cc1[i]>1024) return AF_INVALID;
    for (unsigned i=0;i<AF_GRID_BYTES;++i) if (r->grid[i]<-64 || r->grid[i]>63) return AF_INVALID;
    return AF_OK;
}
int af_joint_expand_matrix(const int16_t *input,int16_t *output) {
    int16_t result[27];
    if (!apart(input,36,output,54)) return AF_INVALID;
    for (unsigned i=0;i<18;++i) if (input[i]<-1024 || input[i]>1024) return AF_INVALID;
    for (unsigned i=0;i<3;++i) {
        int a=input[6*i],b=input[6*i+1],c=input[6*i+2],d=input[6*i+3],e=input[6*i+4],f=input[6*i+5];
        const int row[9]={a+b,-a,-b,-c,c+d,-d,-e,-f,e+f};
        for (unsigned j=0;j<9;++j) result[9*i+j]=(int16_t)row[j];
    }
    for (unsigned i=0;i<27;++i) output[i]=result[i];
    return AF_OK;
}
static int32_t asr(int32_t v,unsigned n) {
    return v>=0?(int32_t)((uint32_t)v>>n):-(int32_t)(((uint32_t)(-v)+((1u<<n)-1u))>>n);
}
/* 分子<2^30、除数<=2^18；固定32步避免Thumb引入未绑定的运行库除法。 */
static uint32_t divide(uint32_t value,uint32_t divisor){
#if defined(__arm__) || defined(AF_GAMMA_SOFT_DIV406)
    uint32_t remainder=0,answer=0;
    for(unsigned bit=32;bit;){
        --bit;remainder=(remainder<<1)|((value>>bit)&1u);
        if(remainder>=divisor){remainder-=divisor;answer|=1u<<bit;}
    }
    return answer;
#else
    return value/divisor;
#endif
}
static uint32_t gamma_point(uint32_t input,uint32_t end,const int16_t *tone){
    /* 合法y/tone下每次乘积绝对值<=2^30，完全等同原64位整数次序。 */
    int32_t y=(int32_t)input,x=(int32_t)divide(input<<12,end),v=4096-x;
    int32_t value=y+asr(y*tone[0],10);
    value+=asr(asr(asr(y*tone[1],10)*v,12)*v,12);
    value+=asr(asr(asr(y*tone[2],10)*x,12)*v,12);
    return (uint32_t)(value<0?0:value>0x3ffff?0x3ffff:value);
}
static int tone_valid(const int16_t *tone){
    if(!tone)return 0;
    for(unsigned i=0;i<3;++i)if(tone[i]<-1024||tone[i]>1024)return 0;
    return 1;
}
int af_joint_gamma_work(const uint32_t *input,const int16_t *tone,uint32_t *result,uint32_t *output) {
    if (!gamma_valid(input) || !apart(input,516,output,516) ||
        !tone_valid(tone)||!apart(tone,6,input,516)||!apart(tone,6,output,516)||
        !apart(result,516,input,516)||!apart(result,516,tone,6)||!apart(result,516,output,516)) return AF_INVALID;
    for (unsigned i=0;i<129;++i)result[i]=gamma_point(input[i],input[128],tone);
    if (!gamma_valid(result)) return AF_INVALID;
    for (unsigned i=0;i<129;++i) output[i]=result[i];
    return AF_OK;
}
int af_joint_gamma(const uint32_t *input,const int16_t *tone,uint32_t *output){
    uint32_t result[129];return af_joint_gamma_work(input,tone,result,output);
}
int af_joint_gamma_matches(const uint32_t *input,const int16_t *tone,const uint32_t *expected){
    if(!gamma_valid(input)||!tone_valid(tone)||!gamma_valid(expected))return AF_INVALID;
    for(unsigned i=0;i<129;++i)if(gamma_point(input[i],input[128],tone)!=expected[i])return AF_STALE;
    return AF_OK;
}
static uint32_t read32(const uint8_t *p) {
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static void write32(uint8_t *p,uint32_t v) {
    for (unsigned i=0;i<4;++i) p[i]=(uint8_t)(v>>(8*i));
}
int af_joint_gamma_record(const void *source,const int16_t *tone,void *destination) {
    const uint8_t *input=source;uint8_t *output=destination;uint32_t before[129],after[129];
    if (!apart(input,576,output,576) || !apart(tone,6,input,576) || !apart(tone,6,output,576)) return AF_INVALID;
    for (unsigned i=0;i<129;++i) before[i]=read32(input+4*i);
    if (af_joint_gamma(before,tone,after)!=AF_OK) return AF_INVALID;
    for (unsigned i=0;i<576;++i) output[i]=input[i];
    for (unsigned i=0;i<129;++i) write32(output+4*i,after[i]);
    write32(output+0x220,after[128]);
    return AF_OK;
}
