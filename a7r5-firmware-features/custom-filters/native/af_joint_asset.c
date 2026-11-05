#include "af_joint_asset.h"
#include "af_sha256.h"
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static uint32_t read32(const uint8_t *p) {
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static void write32(uint8_t *p,uint32_t n) {for (unsigned i=0;i<4;++i) p[i]=(uint8_t)(n>>(i*8));}
static void write16(uint8_t *p,int16_t n) {p[0]=(uint8_t)n;p[1]=(uint8_t)((uint16_t)n>>8);}
static int16_t read16(const uint8_t *p) {
    unsigned n=(unsigned)p[0]|(unsigned)p[1]<<8;
    return (int16_t)(n<32768?(int)n:(int)n-65536);
}
static int valid(const AfJointAsset *a) {
    unsigned any=0;
    if (!a || a->base>=32 || !(0x603ffu&(1u<<a->base)) || af_joint_valid(&a->recipe)!=AF_OK) return 0;
    for (unsigned i=0;i<32;++i) any|=a->model_sha256[i];
#ifndef AF_JOINT_ASSET_LEGACY_ONLY406
    if(a->matrix_mode>1|| (a->matrix_mode&&a->native_mode!=1))return 0;
    for(unsigned i=0;i<288;++i)
        if(a->matrix_mode?(a->sector_matrix[i]<-1024||a->sector_matrix[i]>1024):a->sector_matrix[i]!=0)return 0;
    if(a->matrix_mode)for(unsigned i=0;i<18;++i)if(a->recipe.matrix[i])return 0;
#endif
#ifdef AF_JOINT_ASSET_LEGACY_ONLY406
    if(a->native_mode)return 0;
#else
    if(a->native_mode==1){
        if(af_joint_gamma_matches(a->native_seed,a->native_tone,a->recipe.gamma)!=AF_OK)return 0;
    }else if(!a->native_mode){
        for(unsigned i=0;i<3;++i)if(a->native_tone[i])return 0;
        for(unsigned i=0;i<129;++i)if(a->native_seed[i])return 0;
    }else return 0;
#endif
    return any!=0;
}
#ifndef AF_JOINT_ASSET_LEGACY_ONLY406
static void pack_seed(const uint32_t *seed,uint8_t *out){
    for(unsigned i=0;i<129;++i){
        unsigned bit=i*18u,at=bit>>3;uint32_t word=seed[i]<<(bit&7u);
        out[at]|=(uint8_t)word;out[at+1]|=(uint8_t)(word>>8);out[at+2]|=(uint8_t)(word>>16);
    }
}
static void unpack_seed(const uint8_t *in,uint32_t *seed){
    for(unsigned i=0;i<129;++i){
        unsigned bit=i*18u,at=bit>>3;
        uint32_t word=(uint32_t)in[at]|(uint32_t)in[at+1]<<8|(uint32_t)in[at+2]<<16;
        seed[i]=(word>>(bit&7u))&0x3ffffu;
    }
}
#endif
int af_joint_asset_encode(const AfJointAsset *a,void *output,size_t cap,size_t *written) {
    uint8_t *p=output,*b;uint8_t digest[32];
    const size_t bytes=af_joint_asset_size(a);
    if (!valid(a) || cap<bytes ||
        !apart(a,sizeof(*a),output,cap) || !apart(written,sizeof(*written),a,sizeof(*a)) ||
        !apart(written,sizeof(*written),output,cap)) return AF_INVALID;
    for (unsigned i=0;i<AF_JOINT_ASSET_HEADER;++i) p[i]=0;
#ifdef AF_JOINT_ASSET_LEGACY_ONLY406
    const unsigned native=0,sector=0;
#else
    const unsigned native=a->native_mode;
    const unsigned sector=a->matrix_mode;
#endif
    p[0]='A';p[1]='J';p[2]='R';p[3]=sector?'3':native?'2':'1';p[4]=(uint8_t)(sector?3:native?2:1);p[6]=128;
    write32(p+8,(uint32_t)bytes-128u);write32(p+12,sector?15:native?7:3);write32(p+16,a->base);write32(p+20,1);write32(p+24,15);
    for (unsigned i=0;i<32;++i) {p[32+i]=af_joint_cp_sha256[i];p[64+i]=a->model_sha256[i];}
    b=p+AF_JOINT_ASSET_HEADER;
#ifndef AF_JOINT_ASSET_LEGACY_ONLY406
    if(native){
        uint8_t seed_bytes[516];
        for(unsigned i=0;i<516;++i)b[i]=0;
        pack_seed(a->native_seed,b);
        for(unsigned i=0;i<3;++i)write16(b+292+2*i,a->native_tone[i]);
        for(unsigned i=0;i<129;++i)write32(seed_bytes+4*i,a->native_seed[i]);
        (void)af_sha256(seed_bytes,sizeof(seed_bytes),digest);
        for(unsigned i=0;i<32;++i)b[300+i]=digest[i];
        write32(b+332,1);
    }else
#endif
    for (unsigned i=0;i<129;++i) write32(b+4*i,a->recipe.gamma[i]);
    unsigned count=sector?288u:18u,cc=516u+2u*count;
    for (unsigned i=0;i<count;++i) {
#ifdef AF_JOINT_ASSET_LEGACY_ONLY406
        write16(b+516+2*i,a->recipe.matrix[i]);
#else
        write16(b+516+2*i,sector?a->sector_matrix[i]:a->recipe.matrix[i]);
#endif
    }
    for (unsigned i=0;i<24;++i) write16(b+cc+2*i,a->recipe.cc1[i]);
    for (unsigned i=0;i<1215;++i) b[cc+48+i]=(uint8_t)a->recipe.grid[i];
    (void)af_sha256(p,bytes,digest);
    for (unsigned i=0;i<32;++i) p[96+i]=digest[i];
    *written=bytes;return AF_OK;
}
int af_joint_asset_decode_work(const void *raw,size_t bytes,AfJointAssetDecodeWork *work,AfJointAsset *output) {
    const uint8_t *p=raw,*b;uint8_t digest[32];
    if (!af_joint_asset_size_valid(bytes) || !apart(raw,bytes,output,sizeof(*output)) ||
        !apart(raw,bytes,work,sizeof(*work)) || !apart(work,sizeof(*work),output,sizeof(*output)) ||
        p[0]!='A' || p[1]!='J' || p[2]!='R') return AF_INVALID;
#ifdef AF_JOINT_ASSET_LEGACY_ONLY406
    const unsigned native=0,sector=0;
#else
    const unsigned sector=p[3]=='3'&&p[4]==3;
    const unsigned native=sector||(p[3]=='2'&&p[4]==2);
#endif
    if ((!native&&(p[3]!='1'||p[4]!=1)) || p[5] || p[6]!=128 || p[7] ||
        read32(p+12)!=(sector?15u:native?7u:3u) || read32(p+20)!=1 || read32(p+24)!=15)
        return AF_JOINT_ASSET_UNSUPPORTED;
    if (bytes!=(sector?AF_JOINT_SECTOR_BYTES:AF_JOINT_ASSET_BYTES)||read32(p+8)!=bytes-128u || read32(p+28)) return AF_INVALID;
    b=p+AF_JOINT_ASSET_HEADER;
    for (unsigned i=0;i<bytes;++i) work->checked[i]=(i>=96 && i<128)?0:p[i];
    (void)af_sha256(work->checked,bytes,digest);
    for (unsigned i=0;i<32;++i) if (p[32+i]!=af_joint_cp_sha256[i] || p[96+i]!=digest[i]) return AF_INVALID;
    AfJointAsset *a=&work->candidate;
    for (size_t i=0;i<sizeof(*a);++i) ((uint8_t *)a)[i]=0;
    a->base=read32(p+16);
    for (unsigned i=0;i<32;++i) a->model_sha256[i]=p[64+i];
#ifndef AF_JOINT_ASSET_LEGACY_ONLY406
    if(native){
        if((b[290]&0xfcu)||b[291]||b[298]||b[299]||read32(b+332)!=1)return AF_INVALID;
        for(unsigned i=336;i<516;++i)if(b[i])return AF_INVALID;
        a->native_mode=1;unpack_seed(b,a->native_seed);
        for(unsigned i=0;i<3;++i)a->native_tone[i]=read16(b+292+2*i);
        /* 外层SHA已完成；复用驻留checked验证显式小端seed摘要。 */
        for(unsigned i=0;i<129;++i)write32(work->checked+4*i,a->native_seed[i]);
        (void)af_sha256(work->checked,516,digest);
        for(unsigned i=0;i<32;++i)if(digest[i]!=b[300+i])return AF_INVALID;
        if(af_joint_gamma_work(a->native_seed,a->native_tone,work->gamma_scratch,a->recipe.gamma)!=AF_OK)return AF_INVALID;
    }else
#endif
    for (unsigned i=0;i<129;++i) a->recipe.gamma[i]=read32(b+4*i);
#ifndef AF_JOINT_ASSET_LEGACY_ONLY406
    a->matrix_mode=sector;
#endif
    unsigned count=sector?288u:18u,cc=516u+2u*count;
    for (unsigned i=0;i<count;++i){
#ifndef AF_JOINT_ASSET_LEGACY_ONLY406
        if(sector)a->sector_matrix[i]=read16(b+516+2*i);else
#endif
        a->recipe.matrix[i]=read16(b+516+2*i);
    }
    for (unsigned i=0;i<24;++i) a->recipe.cc1[i]=read16(b+cc+2*i);
    for (unsigned i=0;i<1215;++i) a->recipe.grid[i]=(int8_t)(b[cc+48+i]<128?(int)b[cc+48+i]:(int)b[cc+48+i]-256);
    if (!valid(a)) return AF_INVALID;
    *output=*a;return AF_OK;
}
int af_joint_asset_decode(const void *raw,size_t bytes,AfJointAsset *output) {
    AfJointAssetDecodeWork work;
    return af_joint_asset_decode_work(raw,bytes,&work,output);
}
