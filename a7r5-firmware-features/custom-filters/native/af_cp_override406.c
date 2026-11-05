#include "af_cp_override406.h"
#ifdef AF_CP_NATIVE406
#include "af_cp_native406.h"
#include "af_cp_jobs406.h"
#ifdef AF_CP_CAPTURE406
#include "af_cp_capture406.h"
#endif
#endif
#ifdef AF_CP_CAPTURE_INPUT406
#include "af_cp_input406.h"
#ifdef AF_CP_CAPTURE_COPIES406
#include "af_cp_copy406.h"
#endif
static AfCpInput406 input_state;
AfCpInput406 *af_cp_override406_input_state(void){return &input_state;}
#endif

static const unsigned fields[8]={0xa44,0xa46,0xa45,0xa47,0xa48,0xd2e,0xd2f,0xd30};
static const uint8_t ordinary[10]={0,3,2,1,16,15,17,18,5,13};
static int valid_range(const void *p,size_t n) {
    return p && n && (uintptr_t)p<=UINTPTR_MAX-n;
}
static int separate(const void *a,size_t na,const void *b,size_t nb) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return valid_range(a,na) && valid_range(b,nb) && (x+na<=y || y+nb<=x);
}
static uint8_t wire_base(const AfPreset *p) {
    return p->base<=9?ordinary[p->base]:(p->base==17?19:20);
}
static int valid_preset(const AfPreset *p) {
    return valid_range(p,sizeof(*p)) && af_validate(p)==AF_OK && !p->kind;
}
static int valid_state(const AfCpOverride406 *s) {
    if (!valid_range(s,sizeof(*s))) return 0;
    if (s->mode==AF_CP_OVERRIDE_NATIVE) return s->slot==0;
    return s->version && ((s->mode==AF_CP_OVERRIDE_USER && s->slot>=1 && s->slot<=AF_USERS && valid_preset(&s->preset)) ||
           (s->mode==AF_CP_OVERRIDE_FACTORY_PENDING && s->slot==0 && valid_preset(&s->preset)));
}
static void copy_preset(AfPreset *out,const AfPreset *in) {
    uint8_t *a=(uint8_t *)out;const uint8_t *b=(const uint8_t *)in;
    for (size_t i=0;i<sizeof(*out);++i) a[i]=b[i];
}
int af_cp_override406_publish_locked(AfCpOverride406 *s,uint64_t version,uint32_t slot,const AfPreset *p,uint8_t *marker) {
    if (!version || slot>AF_USERS || !valid_preset(p) || !valid_state(s) ||
        !separate(s,sizeof(*s),p,sizeof(*p)) || !separate(s,sizeof(*s),marker,1) ||
        !separate(p,sizeof(*p),marker,1)) return AF_INVALID;
    if(version<=s->version)return AF_STALE;
    copy_preset(&s->preset,p);s->slot=slot;s->version=version;
    s->mode=slot?AF_CP_OVERRIDE_USER:AF_CP_OVERRIDE_FACTORY_PENDING;
    *marker=1;
    return AF_OK;
}
int af_cp_override406_release_locked(AfCpOverride406 *s,uint64_t version,uint8_t *marker) {
    if (!version || !valid_state(s) || !separate(s,sizeof(*s),marker,1)) return AF_INVALID;
    if(version<=s->version)return AF_STALE;
    s->mode=AF_CP_OVERRIDE_NATIVE;s->slot=0;s->version=version;*marker=1;
    return AF_OK;
}
static int native_matches(const uint8_t *native,const AfPreset *p) {
    if (native[0xa40]!=wire_base(p) || native[0xa41] || native[0xa42] || native[0xa43]) return 0;
    for (unsigned i=0;i<8;++i) if (native[fields[i]]!=(uint8_t)p->params[i]) return 0;
    return 1;
}
int af_cp_override406_snapshot_locked(AfCpOverride406 *s,const void *native_state,void *destination,size_t bytes) {
    uint8_t *dst=destination;
    if (bytes!=AF_CP406_STATE_BYTES || !valid_state(s) ||
        !separate(s,sizeof(*s),native_state,bytes) || !separate(s,sizeof(*s),dst,bytes) ||
        !separate(native_state,bytes,dst,bytes)) return AF_INVALID;
    if (s->mode==AF_CP_OVERRIDE_NATIVE) return AF_OK;
    if (s->mode==AF_CP_OVERRIDE_FACTORY_PENDING && native_matches(native_state,&s->preset)) {
        s->mode=AF_CP_OVERRIDE_NATIVE;s->slot=0;
        return AF_OK;
    }
    dst[0xa40]=wire_base(&s->preset);dst[0xa41]=dst[0xa42]=dst[0xa43]=0;
    for (unsigned i=0;i<8;++i) dst[fields[i]]=(uint8_t)s->preset.params[i];
    return AF_OK;
}
#ifdef AF_CP_CAPTURE_INPUT406
int af_cp_override406_snapshot_copy_locked(AfCpOverride406 *s,const void *native_state,void *destination,size_t bytes,
    AfCpInput406 *input,uint32_t logical_destination,AfCpSnapshotCopy406 copy) {
    if(!copy || bytes!=AF_CP406_STATE_BYTES ||
       !separate(native_state,bytes,destination,bytes) ||
       (s&&(!separate(s,sizeof(*s),native_state,bytes) || !separate(s,sizeof(*s),destination,bytes) ||
            !separate(input,sizeof(*input),s,sizeof(*s)))) ||
       !separate(input,sizeof(*input),native_state,bytes) || !separate(input,sizeof(*input),destination,bytes))return AF_INVALID;
    AfCpInput406Write write;
    int begin=af_cp_input406_snapshot_begin(input,logical_destination,bytes,&write);
    /* 即使追踪记录耗尽/忙，原复制仍完成；不得留下半份原厂输入。 */
    copy(destination,native_state,bytes);
    int result=s?af_cp_override406_snapshot_locked(s,native_state,destination,bytes):AF_IO;
    if(begin==AF_OK){
        const AfPreset *expected=!s||s->mode==AF_CP_OVERRIDE_NATIVE?0:&s->preset;
        int end=af_cp_input406_snapshot_end(input,&write,s?s->version:0,s?s->slot:0,
            result==AF_OK?s->mode:UINT32_MAX,expected,destination,bytes);
        if(result==AF_OK)result=end;
    }else if(result==AF_OK)result=begin;
    return result;
}
#endif

/* 原CP18b265的898548..8985be；8B绝对gate只替换复制后的MOVW/MOVT。 */
static const uint8_t snapshot_code[118]={
    0xf0,0xb5,0x03,0xaf,0x4d,0xf8,0x04,0xbd,0x06,0x46,0x24,0x20,0x20,0xf5,0x00,0xed,
    0xf8,0xb9,0x4a,0xf6,0x10,0x21,0x30,0x46,0x40,0xf6,0xbc,0x52,0xc0,0xf2,0x57,0x11,
    0x5c,0xf5,0x28,0xee,0x4b,0xf2,0xd0,0x70,0xc0,0xf2,0x57,0x10,0xc1,0x68,0x69,0xb9,
    0x4b,0xf2,0xe0,0x7c,0xc0,0xf2,0x57,0x1c,0xdc,0xf8,0x0c,0x20,0x32,0xb1,0x62,0x46,
    0x92,0xe8,0x3a,0x00,0x3a,0xc0,0x00,0x20,0xcc,0xf8,0x0c,0x00,0x24,0x20,0x20,0xf5,
    0xbc,0xe9,0xd2,0xf1,0x60,0xfe,0x58,0xb9,0xd6,0xf8,0x20,0x02,0x03,0x28,0x07,0xd1,
    0xd6,0xf8,0x68,0x07,0x03,0x38,0x01,0x28,0x02,0xd8,0x02,0x20,0xc6,0xf8,0x68,0x07,
    0x5d,0xf8,0x04,0xbb,0xf0,0xbd,
};
int af_cp_override406_hook_matches(const void *code,size_t bytes,uint32_t gate) {
    const uint8_t *p=code;
    if (bytes!=sizeof(snapshot_code) || !valid_range(p,bytes) || !(gate&1u)) return 0;
#if defined(AF_CP_CARVE_BRANCH406) || defined(AF_CP_CAPTURE_INPUT406)
    /* 新分支只覆盖完整MOVW；原MOVT和其他114B必须保持，不接受旧绝对gate。 */
#ifdef AF_CP_CAPTURE_INPUT406
    uint32_t delta=(gate&~1u)-(0x898568u+4u);
#else
    uint32_t delta=(gate&~1u)-(0x89856cu+4u);
#endif
    if((delta&1u) || delta+0x1000000u>=0x2000000u)return 0;
    uint32_t sign=(delta>>24)&1u;
    uint32_t upper=0xf000u|(sign<<10)|((delta>>12)&0x3ffu);
    uint32_t lower=
#ifdef AF_CP_CAPTURE_COPIES406
        0xd000u|
#else
        0x9000u|
#endif
        ((~((delta>>23)^sign)&1u)<<13)|
        ((~((delta>>22)^sign)&1u)<<11)|((delta>>1)&0x7ffu);
    uint32_t branch=upper|(lower<<16);
#endif
    for (size_t i=0;i<bytes;++i) {
        uint8_t expected=snapshot_code[i];
#ifdef AF_CP_CAPTURE_INPUT406
        if(i>=32 && i<36)expected=(uint8_t)(branch>>(8*(i-32)));
#elif defined(AF_CP_CARVE_BRANCH406)
        if(i>=36 && i<40)expected=(uint8_t)(branch>>(8*(i-36)));
#else
        if (i>=36 && i<40) {
            static const uint8_t jump[4]={0xdf,0xf8,0,0xf0};expected=jump[i-36];
        } else if (i>=40 && i<44) expected=(uint8_t)(gate>>(8*(i-40)));
#endif
        if (p[i]!=expected) return 0;
    }
    return 1;
}

#if defined(__arm__) && defined(AF_SNAPSHOT_OVERLAY406)
static AfCpOverride406 active;
static uint32_t fault;
int af_cp_override406_faulted(void){return __atomic_load_n(&fault,__ATOMIC_SEQ_CST)!=0;}
void af_cp_override406_close(void){__atomic_store_n(&fault,1,__ATOMIC_SEQ_CST);}
typedef int (*NativeLock)(uint32_t);
static int lock_original(void) { return ((NativeLock)(uintptr_t)0x5b8d6cu)(0x24); }
static int unlock_original(void) { return ((NativeLock)(uintptr_t)0x5b8910u)(0x24); }
#ifdef AF_CP_SNAPSHOT_ENTRY406
#if !(AF_CP_SNAPSHOT_ENTRY406 & 1u) || AF_CP_SNAPSHOT_ENTRY406 < 0xbef9e9u || AF_CP_SNAPSHOT_ENTRY406 >= 0xbefb80u
#error "snapshot entry must be the paired Thumb fallback in the verified original RX tail"
#endif
#define SNAPSHOT_ENTRY406 ((uint32_t)AF_CP_SNAPSHOT_ENTRY406)
#else
#define SNAPSHOT_ENTRY406 ((uint32_t)(uintptr_t)&af_cp_override406_snapshot_gate)
#endif
static int installed(void) {
    return !__atomic_load_n(&fault,__ATOMIC_SEQ_CST) && af_cp_override406_hook_matches((const void *)(uintptr_t)0x898548u,
        sizeof(snapshot_code),SNAPSHOT_ENTRY406);
}
int af_cp_override406_ready(void) {
    if (!installed() || ((NativeLock)(uintptr_t)0x5b8f58u)(0x24)!=0) return 0;
    if (unlock_original()!=0) { __atomic_store_n(&fault,1,__ATOMIC_SEQ_CST);return 0; }
    return 1;
}
int af_cp_override406_prepare(uint64_t version,uint32_t slot,const AfPreset *preset) {
    if (!version || slot>AF_USERS || !valid_preset(preset)) return AF_INVALID;
    if (!installed() || lock_original()!=0) return AF_IO;
    int result=__atomic_load_n(&fault,__ATOMIC_SEQ_CST)?AF_IO:
        af_cp_override406_publish_locked(&active,version,slot,preset,(uint8_t *)(uintptr_t)0x19c999du);
#ifdef AF_CP_NATIVE406
    if(result==AF_OK&&af_cp_native_bank406_clear_active_locked(af_cp_native406_banks())!=AF_OK){
        af_cp_override406_close();result=AF_IO;
    }
#endif
    __asm__ volatile("dmb sy" ::: "memory");
    if (unlock_original()!=0) { __atomic_store_n(&fault,1,__ATOMIC_SEQ_CST);return AF_IO; }
    return result;
}
int af_cp_override406_release(uint64_t version) {
    if(!version)return AF_INVALID;
    if (!installed() || lock_original()!=0) return AF_IO;
    int result=__atomic_load_n(&fault,__ATOMIC_SEQ_CST)?AF_IO:
        af_cp_override406_release_locked(&active,version,(uint8_t *)(uintptr_t)0x19c999du);
#ifdef AF_CP_NATIVE406
    if(result==AF_OK&&af_cp_native_bank406_clear_active_locked(af_cp_native406_banks())!=AF_OK){
        af_cp_override406_close();result=AF_IO;
    }
#endif
    __asm__ volatile("dmb sy" ::: "memory");
    if (unlock_original()!=0) { __atomic_store_n(&fault,1,__ATOMIC_SEQ_CST);return AF_IO; }
    return result;
}
#ifdef AF_CP_NATIVE406
int af_cp_override406_prepare_joint(uint64_t version,uint32_t slot,const AfPreset *preset,const AfJointAsset *asset){
    if(!af_cp_native406_ready())return AF_IO;
    if(!installed()||lock_original()!=0)return AF_IO;
    int result=af_cp_override406_faulted()?AF_IO:
        af_cp_native_bank406_accept_locked(af_cp_native406_banks(),&active,version,slot,preset,asset,
            (uint8_t *)(uintptr_t)0x19c999du);
    __asm__ volatile("dmb sy" ::: "memory");
    if(unlock_original()!=0){af_cp_override406_close();return AF_IO;}
    return result;
}
void af_cp_native406_c4_target(void *dst,const void *source,size_t bytes,uint32_t lr){
    AfCpSnapshotCopy406 copy=(AfCpSnapshotCopy406)(uintptr_t)0x5f51bcu;
    if(!af_cp_native406_ready()||!installed()||lock_original()!=0){copy(dst,source,bytes);return;}
    if(af_cp_override406_faulted())copy(dst,source,bytes);
    else af_cp_jobs406_c4_target(dst,source,bytes,lr);
    AfCpJobs406 *jobs=af_cp_jobs406_target_state();
    if(!jobs||__atomic_load_n(&jobs->fault,__ATOMIC_SEQ_CST))af_cp_override406_close();
    __asm__ volatile("dmb sy" ::: "memory");
    if(unlock_original()!=0)af_cp_override406_close();
}
#endif
void af_cp_override406_snapshot_target(void *dst,size_t bytes) {
    if (!__atomic_load_n(&fault,__ATOMIC_SEQ_CST) && af_cp_override406_snapshot_locked(&active,(const void *)(uintptr_t)0x157aa10u,dst,bytes)!=AF_OK)
        __atomic_store_n(&fault,1,__ATOMIC_SEQ_CST);
}
#ifdef AF_CP_CAPTURE_INPUT406
int af_cp_override406_read_input(uint32_t source,AfCpInput406Token *out){
    if(!separate(&input_state,sizeof(input_state),out,sizeof(*out))||
       !separate(&active,sizeof(active),out,sizeof(*out))||
       !separate(&fault,sizeof(fault),out,sizeof(*out))||
       (uintptr_t)out%_Alignof(AfCpInput406Token))return AF_INVALID;
    if(__atomic_load_n(&fault,__ATOMIC_SEQ_CST))return AF_IO;
    AfCpInput406Token token;
    int result=af_cp_input406_read(&input_state,source,&token);
    if(__atomic_load_n(&fault,__ATOMIC_SEQ_CST))return AF_IO;
    if(result==AF_OK)for(size_t i=0;i<sizeof(token);++i)((uint8_t *)out)[i]=((uint8_t *)&token)[i];
    return result;
}
void af_cp_override406_snapshot_copy_target(void *dst,const void *source,size_t bytes) {
    AfCpSnapshotCopy406 copy=(AfCpSnapshotCopy406)(uintptr_t)0x5f51bcu;
    if((uintptr_t)dst!=AF_CP_INPUT406_SNAPSHOT){
        copy(dst,source,bytes);
        af_cp_override406_snapshot_target(dst,bytes);
        return;
    }
    if((uintptr_t)source!=0x157aa10u || __atomic_load_n(&fault,__ATOMIC_SEQ_CST)){
        /* 原目的即将被写时，旧USER tag必须同时失效，不能只跳过observer。 */
        (void)af_cp_override406_snapshot_copy_locked(0,source,dst,bytes,
            &input_state,(uint32_t)(uintptr_t)dst,copy);
        return;
    }
    int result=af_cp_override406_snapshot_copy_locked(&active,source,dst,bytes,
        &input_state,(uint32_t)(uintptr_t)dst,copy);
    /* fault可在原unlock之后被另一任务置位，不受当前0x24互斥保护。 */
    if(__atomic_load_n(&fault,__ATOMIC_SEQ_CST)){
        (void)af_cp_input406_invalidate(&input_state,(uint32_t)(uintptr_t)dst);
        return;
    }
    /* 原Native域不受私有资格失败影响；私有模式出现追踪失效则关闭覆盖。 */
    if(result!=AF_OK && active.mode!=AF_CP_OVERRIDE_NATIVE)__atomic_store_n(&fault,1,__ATOMIC_SEQ_CST);
}
#if defined(AF_CP_CAPTURE406) && defined(AF_CP_NATIVE406)
void af_cp_override406_request_copy_target(void *dst,const void *source,size_t bytes){
    AfCpSnapshotCopy406 original=(AfCpSnapshotCopy406)(uintptr_t)0x5f51bcu;
    /* 撤销先于真实覆盖；不持私有guard取得原锁，原锁忙时不等待。 */
    (void)af_cp_input406_invalidate(&input_state,AF_CP_INPUT406_REQUEST);
    af_cp_capture406_request_invalidate_target();
    if((uintptr_t)dst!=AF_CP_INPUT406_REQUEST||(uintptr_t)source!=0x157aa10u||
       bytes!=AF_CP_INPUT406_SNAPSHOT_BYTES||!af_cp_native406_ready()||!installed()||
       ((NativeLock)(uintptr_t)0x5b8f58u)(0x24)!=0){original(dst,source,bytes);return;}
    int result=af_cp_override406_snapshot_copy_locked(&active,source,dst,bytes,
        &input_state,AF_CP_INPUT406_REQUEST,original);
    AfCpInput406Token token;
    if(result==AF_OK&&!af_cp_override406_faulted()&&
       af_cp_input406_read(&input_state,AF_CP_INPUT406_REQUEST,&token)==AF_OK&&
       token.mode==AF_CP_OVERRIDE_USER){
        AfCpNativeBanks406 *banks=af_cp_native406_banks();
        /* 与投影同锁，只从同一版本的已校验深副本发布Capture缓存。 */
        if(banks&&banks->active&&banks->active<=AF_CP_NATIVE_BANKS406){
            AfCpNativeBank406 *bank=&banks->banks[banks->active-1u];
            if(bank->valid&&bank->version==token.version&&bank->slot==token.slot&&
               native_matches(dst,&bank->preset))
                result=af_cp_capture406_request_publish_target(&token,
                    *(const volatile uint32_t *)(uintptr_t)0x163f3c8u,&bank->asset);
        }
    }
    if(result!=AF_OK||af_cp_override406_faulted()){
        (void)af_cp_input406_invalidate(&input_state,AF_CP_INPUT406_REQUEST);
        af_cp_capture406_request_invalidate_target();
    }
    __asm__ volatile("dmb sy" ::: "memory");
    if(unlock_original()!=0){
        af_cp_override406_close();
        (void)af_cp_input406_invalidate(&input_state,AF_CP_INPUT406_REQUEST);
        af_cp_capture406_request_invalidate_target();
    }
}
#endif
#ifdef AF_CP_CAPTURE_COPIES406
void af_cp_override406_image_copy_target(void *dst,const void *source,size_t bytes,uint32_t vd){
    AfCpSnapshotCopy406 copy=(AfCpSnapshotCopy406)(uintptr_t)0x5f51bcu;
    unsigned allow=!__atomic_load_n(&fault,__ATOMIC_SEQ_CST);
    (void)af_cp_copy406_observe(&input_state,dst,(uint32_t)(uintptr_t)dst,
        source,(uint32_t)(uintptr_t)source,bytes,vd,allow,copy);
    if(__atomic_load_n(&fault,__ATOMIC_SEQ_CST))
        (void)af_cp_input406_invalidate(&input_state,(uint32_t)(uintptr_t)dst);
}
void af_cp_override406_untracked_copy_target(void *dst,const void *source,size_t bytes){
    (void)af_cp_input406_invalidate(&input_state,(uint32_t)(uintptr_t)dst);
    ((AfCpSnapshotCopy406)(uintptr_t)0x5f51bcu)(dst,source,bytes);
}
#endif
#endif
#else
int af_cp_override406_ready(void) { return 0; }
int af_cp_override406_faulted(void){return 1;}
void af_cp_override406_close(void){}
#ifdef AF_CP_NATIVE406
int af_cp_override406_prepare_joint(uint64_t version,uint32_t slot,const AfPreset *p,const AfJointAsset *a){(void)version;(void)slot;(void)p;(void)a;return AF_IO;}
void af_cp_native406_c4_target(void *d,const void *s,size_t n,uint32_t lr){(void)d;(void)s;(void)n;(void)lr;}
#endif
int af_cp_override406_prepare(uint64_t version,uint32_t slot,const AfPreset *preset) { (void)version;(void)slot;(void)preset;return AF_IO; }
int af_cp_override406_release(uint64_t version) { (void)version;return AF_IO; }
void af_cp_override406_snapshot_target(void *dst,size_t bytes) { (void)dst;(void)bytes; }
#ifdef AF_CP_CAPTURE_INPUT406
int af_cp_override406_read_input(uint32_t source,AfCpInput406Token *out){(void)source;(void)out;return AF_IO;}
void af_cp_override406_snapshot_copy_target(void *dst,const void *source,size_t bytes){(void)dst;(void)source;(void)bytes;}
#ifdef AF_CP_CAPTURE406
void af_cp_override406_request_copy_target(void *dst,const void *source,size_t bytes){(void)dst;(void)source;(void)bytes;}
#endif
#endif
#endif
