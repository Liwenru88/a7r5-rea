/* 固定数值段只借用RO存储，描述符和标量由本模块独立装配。 */
#include "af_reference_assets.h"
#include "af_sha256.h"
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "Fixed numeric reference asset requires little endian"
#endif
_Static_assert(sizeof(float)==4,"Reference float32 table width");
const uint8_t af_reference_assets_sha256[32]={
    0x2d,0xa8,0x25,0xa2,0x72,0x46,0x6e,0x38,0xc2,0xd9,0x30,0x55,0xdb,0x41,0x2d,0x4f,
    0xce,0x32,0x45,0x4a,0x86,0x4d,0x5e,0xd2,0x19,0xcc,0x82,0xa7,0x12,0xee,0x74,0x5f};
static int apart(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
static uint32_t u32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static int16_t i16(const uint8_t *p){unsigned v=(unsigned)p[0]|(unsigned)p[1]<<8;return (int16_t)(v<32768?(int)v:(int)v-65536);}
static int hash_valid(const void *raw){
    uint8_t digest[32];unsigned different=0;
    if(af_sha256(raw,AF_REFERENCE_ASSETS_BYTES,digest))return 0;
    for(unsigned i=0;i<32;++i)different|=digest[i]^af_reference_assets_sha256[i];return !different;
}
size_t af_reference_assets_owner_bytes(void){return sizeof(AfReferenceAssets);}
int af_reference_assets_bind(const void *raw,size_t bytes,AfReferenceAssets *out){
    if(bytes!=AF_REFERENCE_ASSETS_BYTES||((uintptr_t)raw&3u)||
       ((uintptr_t)out%_Alignof(AfReferenceAssets))||!apart(raw,bytes,out,sizeof(*out))||!hash_valid(raw))return AF_INVALID;
    const uint8_t *p=raw;AfReferenceAssets next={0};
    next.valid=1;next.raw=p;
    next.baseline.matrix.table=(const float *)p;next.baseline.matrix.angles=(const float *)(p+73728);
    next.baseline.matrix.table_entries=18432;next.baseline.matrix.angle_entries=512;
    next.baseline.matrix.enabled=next.baseline.matrix.luma_smooth=next.baseline.matrix.chroma_smooth=1;
    next.baseline.matrix.quadratic=1;
    next.baseline.main_gamma=(const uint16_t *)(p+75776);
    next.baseline.y_gamma=(const uint16_t *)(p+239616+65536);
    next.baseline.main_entries=65536;next.baseline.y_entries=32768;
    for(unsigned i=0;i<8;++i)next.baseline.cc1[i]=i16(p+376088+2*i);
    next.baseline.luma[0]=2432;next.baseline.luma[1]=4864;next.baseline.luma[2]=896;
    static const float area[16]={0,0,-72,54,.25f,-.53125f,.109375f,-.828125f,
        -.765625f,-.328125f,.359375f,.9375f,.234375f,.28125f,0,0};
    for(unsigned i=0;i<16;++i)next.baseline.area.coefficients[i]=area[i];
    next.baseline.area.selector=1;
    next.baseline.chroma.high_cutoff=15356;next.baseline.chroma.low_cutoff=0;
    next.baseline.chroma.high_slope=next.baseline.chroma.low_slope=512;
    next.baseline.levels.gain=1.0546875f;
    next.matrix_domain=(AfEditMatrixDomain){1,1,3,{255,255}};
    next.chroma_source.slopes[0]=512;next.chroma_source.slopes[1]=112;next.chroma_source.slopes[2]=128;
    for(unsigned i=0;i<3;++i)next.chroma_source.thresholds[i]=15360;
    next.chroma_source.low_slope=512;next.chroma_source.gain_raw=64;
    /* 最终对象地址用于自指针；尚未写输出，全部源已按固定摘要验证。 */
    next.context.baseline=&out->baseline;
    next.context.axis=(const uint32_t *)(p+370688);next.context.gamma_y=(const uint32_t *)(p+371200);
    next.context.contrast=(const int32_t *)(p+371712);next.context.matrix_payload=p+375812;
    next.context.cc1=(const int16_t *)(p+376088);next.context.matrix_domain=&out->matrix_domain;
    next.context.chroma_source=&out->chroma_source;next.context.secondary_inverse=(const int16_t *)(p+206848);
    next.context.secondary_gamma=(const int16_t *)(p+239616);
    next.context.secondary_inverse_entries=16384;next.context.secondary_entries=65536;
    next.context.main_inverse_initial_zero=65451;
    next.joint.edit=&out->context;next.joint.cp_gamma_record=p+376104;
    next.joint.matrix_raw=(const uint16_t *)(p+376680);next.joint.cc1_raw=(const uint16_t *)(p+377256);
    next.joint.matrix_weights[0]=next.joint.cc1_weights[0]=256;
    *out=next;return AF_OK;
}
int af_reference_assets_seed(const AfReferenceAssets *owner,AfJointRecipe *out){
    if(!owner||owner->valid!=1||!owner->raw||owner->context.baseline!=&owner->baseline||
       owner->joint.edit!=&owner->context||owner->joint.cp_gamma_record!=owner->raw+376104||
       !apart(owner,sizeof(*owner),out,sizeof(*out))||
       !apart(owner->raw,AF_REFERENCE_ASSETS_BYTES,out,sizeof(*out))||!hash_valid(owner->raw))return AF_INVALID;
    const uint8_t *p=owner->joint.cp_gamma_record;
    uint32_t previous=0;
    for(unsigned i=0;i<129;++i){uint32_t value=u32(p+4*i);
        if(value>0x3ffffu||(i&&value<previous)||(!i&&value)||(i==128&&!value))return AF_INVALID;
        previous=value;
    }
    for(size_t i=0;i<sizeof(*out);++i)((uint8_t *)out)[i]=0;
    for(unsigned i=0;i<129;++i)out->gamma[i]=u32(p+4*i);
    return AF_OK;
}
