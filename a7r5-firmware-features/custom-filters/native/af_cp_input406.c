/* 固定记录的所有跨任务数据均为32位原子；不读取或占用原C4字段。 */
#include "af_cp_input406.h"
#define SNAPSHOT_OPERATION 1u
#define COPY_OPERATION 2u
_Static_assert(__atomic_always_lock_free(4,0),"input sidecar requires lock-free 32-bit atomics");
static const uint32_t addresses[AF_CP_INPUT406_RECORDS]={AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_COPY_A,AF_CP_INPUT406_COPY_B
#ifdef AF_CP_CAPTURE406
    ,AF_CP_INPUT406_REQUEST
#endif
};
static const unsigned fields[8]={0xa44,0xa46,0xa45,0xa47,0xa48,0xd2e,0xd2f,0xd30};
static uint32_t load(const uint32_t *p){return __atomic_load_n(p,__ATOMIC_SEQ_CST);}
static void store(uint32_t *p,uint32_t v){__atomic_store_n(p,v,__ATOMIC_SEQ_CST);}
static int range(const void *p,size_t n){return p&&n&&(uintptr_t)p<=UINTPTR_MAX-n;}
static int apart(const void *a,size_t n,const void *b,size_t m){
    return range(a,n)&&range(b,m)&&((uintptr_t)a+n<=(uintptr_t)b||(uintptr_t)b+m<=(uintptr_t)a);
}
static int state_valid(const AfCpInput406 *s){return range(s,sizeof(*s))&&!((uintptr_t)s%_Alignof(AfCpInput406));}
static int index_of(uint32_t address){for(unsigned i=0;i<AF_CP_INPUT406_RECORDS;++i)if(addresses[i]==address)return (int)i;return -1;}
static int snapshot_index(int i){
#ifdef AF_CP_CAPTURE406
    return i==0||i==3;
#else
    return i==0;
#endif
}
static int copy_index(int i){
#ifdef AF_CP_CAPTURE406
    return i==1||i==2;
#else
    return i!=0;
#endif
}
static uint32_t u32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint64_t version_of(const uint32_t *w){return (uint64_t)w[0]|((uint64_t)w[1]<<32);}
static int signed_byte(unsigned v){return v<128?(int)v:(int)v-256;}
static void empty_preset(AfPreset *p){for(size_t i=0;i<sizeof(*p);++i)((uint8_t *)p)[i]=0;}
static int actual_preset(const void *actual,size_t bytes,AfPreset *out){
    const uint8_t *p=actual;
    static const uint8_t wire[12]={0,3,2,1,16,15,17,18,5,13,19,20};
    if(!range(p,bytes)||bytes<AF_CP_INPUT406_SNAPSHOT_BYTES)return AF_INVALID;
    unsigned value=u32(p+0xa40),found=12;
    for(unsigned i=0;i<12;++i)if(value==wire[i]){found=i;break;}
    if(found==12)return AF_INVALID;
    empty_preset(out);out->base=(uint8_t)(found<10?found:found+7);
    for(unsigned i=0;i<8;++i)out->params[i]=(int8_t)signed_byte(p[fields[i]]);
    return af_validate(out);
}
static void pack_actual(uint32_t *w,const AfPreset *p){
    w[7]=(uint32_t)p->base|(uint32_t)(uint8_t)p->params[0]<<8|
        (uint32_t)(uint8_t)p->params[1]<<16|(uint32_t)(uint8_t)p->params[2]<<24;
    w[8]=(uint32_t)(uint8_t)p->params[3]|(uint32_t)(uint8_t)p->params[4]<<8|
        (uint32_t)(uint8_t)p->params[5]<<16|(uint32_t)(uint8_t)p->params[6]<<24;
    w[9]=(uint32_t)(uint8_t)p->params[7];
}
static void unpack_actual(const uint32_t *w,AfPreset *p){
    empty_preset(p);p->base=(uint8_t)w[7];
    p->params[0]=(int8_t)signed_byte((w[7]>>8)&255u);
    p->params[1]=(int8_t)signed_byte((w[7]>>16)&255u);
    p->params[2]=(int8_t)signed_byte(w[7]>>24);
    for(unsigned i=0;i<4;++i)p->params[i+3]=(int8_t)signed_byte((w[8]>>(8*i))&255u);
    p->params[7]=(int8_t)signed_byte(w[9]&255u);
}
static int same_actual(const AfPreset *a,const AfPreset *b){
    unsigned different=a->base^b->base;
    for(unsigned i=0;i<8;++i)different|=(uint8_t)a->params[i]^(uint8_t)b->params[i];
    return !different;
}
/* 即使失败也消耗本次目的epoch；已知目的不保留过期资格，耗尽时永不回卷。 */
static void invalidate(AfCpInput406Record *r){
    uint32_t seq=load(&r->sequence);
    if(!(seq&1u))store(&r->sequence,seq+1u);
    store(&r->valid,0);r->operation=0;
    if(seq!=UINT32_MAX&&seq!=UINT32_MAX-1u)store(&r->sequence,(seq&1u)?seq+1u:seq+2u);
}
static int fail(AfCpInput406Record *r,int error){invalidate(r);return error;}
static int begin(AfCpInput406Record *r,uint32_t operation,uint32_t *epoch){
    uint32_t seq=load(&r->sequence);
    if(seq>=UINT32_MAX-1u){invalidate(r);return AF_EXHAUSTED;}
    if(seq&1u)return fail(r,AF_BUSY);
    store(&r->sequence,seq+1u);store(&r->valid,0);
    r->operation=operation;r->operation_epoch=seq+1u;*epoch=seq+1u;return AF_OK;
}
static int read_words(const AfCpInput406Record *r,uint32_t *words,uint32_t *epoch){
    uint32_t first=load(&r->sequence);
    if(first==UINT32_MAX)return AF_EXHAUSTED;
    if(first&1u)return AF_BUSY;
    uint32_t valid=load(&r->valid);
    for(unsigned i=0;i<AF_CP_INPUT406_WORDS;++i)words[i]=load(&r->published[i]);
    uint32_t last=load(&r->sequence);
    if(first!=last||(last&1u))return AF_BUSY;
    if(!valid)return AF_EMPTY;
    *epoch=last;return AF_OK;
}
static int publish(AfCpInput406Record *r,uint32_t epoch,const uint32_t *words){
    for(unsigned i=0;i<AF_CP_INPUT406_WORDS;++i)store(&r->published[i],words[i]);
    r->operation=0;store(&r->valid,1);store(&r->sequence,epoch+1u);return AF_OK;
}
static int valid_identity(uint64_t version,uint32_t slot,uint32_t mode){
    return mode==AF_CP_OVERRIDE_NATIVE?slot==0:
        (version&&((mode==AF_CP_OVERRIDE_USER&&slot>=1&&slot<=AF_USERS)||
                   (mode==AF_CP_OVERRIDE_FACTORY_PENDING&&!slot)));
}
static int ticket(AfCpInput406 *s,const AfCpInput406Write *t,uint32_t operation,int *index){
    if(!state_valid(s)||!apart(s,sizeof(*s),t,sizeof(*t))||(uintptr_t)t%_Alignof(AfCpInput406Write))return AF_INVALID;
    int i=index_of(t->source);
    if(i<0)return AF_INVALID;
    *index=i;AfCpInput406Record *r=&s->records[i];
    /* 旧票据不拥有当前写入，不能取消或发布较新的目的代。 */
    if(load(&r->sequence)!=t->epoch||!(t->epoch&1u)||t->epoch==UINT32_MAX||
       r->operation!=operation||r->operation_epoch!=t->epoch)return AF_STALE;
    return AF_OK;
}
size_t af_cp_input406_bytes(void){return sizeof(AfCpInput406);}
int af_cp_input406_invalidate(AfCpInput406 *s,uint32_t destination){
    if(!state_valid(s))return AF_INVALID;
    int i=index_of(destination);if(i<0)return AF_INVALID;
    invalidate(&s->records[i]);return AF_OK;
}
int af_cp_input406_snapshot_begin(AfCpInput406 *s,uint32_t destination,size_t bytes,AfCpInput406Write *out){
    if(!state_valid(s))return AF_INVALID;
    int i=index_of(destination);if(i<0)return AF_INVALID;
    AfCpInput406Record *r=&s->records[i];
    if(!snapshot_index(i)||bytes!=AF_CP_INPUT406_SNAPSHOT_BYTES||!apart(s,sizeof(*s),out,sizeof(*out))||
       (uintptr_t)out%_Alignof(AfCpInput406Write))return fail(r,AF_INVALID);
    uint32_t epoch;int result=begin(r,SNAPSHOT_OPERATION,&epoch);
    if(result==AF_OK){out->source=destination;out->epoch=epoch;}return result;
}
int af_cp_input406_snapshot_end(AfCpInput406 *s,const AfCpInput406Write *t,uint64_t version,
    uint32_t slot,uint32_t mode,const AfPreset *expected,const void *actual,size_t bytes){
    int i=-1;int result=ticket(s,t,SNAPSHOT_OPERATION,&i);
    if(result!=AF_OK)return result;
    AfCpInput406Record *r=&s->records[i];AfPreset value;uint32_t words[AF_CP_INPUT406_WORDS];
    if(!snapshot_index(i)||bytes!=AF_CP_INPUT406_SNAPSHOT_BYTES||!valid_identity(version,slot,mode)||
       !apart(s,sizeof(*s),actual,bytes)||!apart(t,sizeof(*t),actual,bytes)||
       (expected&&(!apart(s,sizeof(*s),expected,sizeof(*expected))||
        !apart(t,sizeof(*t),expected,sizeof(*expected))||!apart(actual,bytes,expected,sizeof(*expected))||
        af_validate(expected)!=AF_OK||expected->kind))||
       (!expected&&mode!=AF_CP_OVERRIDE_NATIVE)||actual_preset(actual,bytes,&value)!=AF_OK)return fail(r,AF_INVALID);
    if(expected&&!same_actual(expected,&value))return fail(r,AF_STALE);
    uint64_t seen=(uint64_t)r->seen_version_lo|((uint64_t)r->seen_version_hi<<32);
    if(version<seen)return fail(r,AF_STALE);
    words[0]=(uint32_t)version;words[1]=(uint32_t)(version>>32);words[2]=slot;words[3]=mode;
    words[4]=mode==AF_CP_OVERRIDE_USER?AF_CP_INPUT406_USER_VERSION:0;
    words[5]=0;words[6]=t->epoch+1u;pack_actual(words,&value);
    r->seen_version_lo=words[0];r->seen_version_hi=words[1];return publish(r,t->epoch,words);
}
int af_cp_input406_copy_begin(AfCpInput406 *s,uint32_t destination,uint32_t source,size_t bytes,
    uint32_t expected_vd,AfCpInput406Write *out){
    if(!state_valid(s))return AF_INVALID;
    int i=index_of(destination);if(i<0)return AF_INVALID;
    AfCpInput406Record *r=&s->records[i];
    if(!copy_index(i)||source!=AF_CP_INPUT406_SNAPSHOT||bytes!=AF_CP_INPUT406_COPY_BYTES||
       !apart(s,sizeof(*s),out,sizeof(*out))||(uintptr_t)out%_Alignof(AfCpInput406Write))return fail(r,AF_INVALID);
    uint32_t epoch;int result=begin(r,COPY_OPERATION,&epoch);
    if(result!=AF_OK)return result;
    uint32_t words[AF_CP_INPUT406_WORDS],source_epoch;
    result=read_words(&s->records[0],words,&source_epoch);
    if(result!=AF_OK)return fail(r,result);
    for(unsigned j=0;j<AF_CP_INPUT406_WORDS;++j)r->captured[j]=words[j];
    r->source_epoch=source_epoch;r->expected_vd=expected_vd;
    out->source=destination;out->epoch=epoch;return AF_OK;
}
int af_cp_input406_copy_end(AfCpInput406 *s,const AfCpInput406Write *t,const void *actual,size_t bytes){
    int i=-1;int result=ticket(s,t,COPY_OPERATION,&i);
    if(result!=AF_OK)return result;
    AfCpInput406Record *r=&s->records[i];
    if(!copy_index(i)||bytes!=AF_CP_INPUT406_COPY_BYTES||!apart(s,sizeof(*s),actual,bytes)||
       !apart(t,sizeof(*t),actual,bytes))return fail(r,AF_INVALID);
    uint32_t now[AF_CP_INPUT406_WORDS],epoch;
    result=read_words(&s->records[0],now,&epoch);
    if(result!=AF_OK||epoch!=r->source_epoch)return fail(r,AF_STALE);
    for(unsigned j=0;j<AF_CP_INPUT406_WORDS;++j)if(now[j]!=r->captured[j])return fail(r,AF_STALE);
    AfPreset value;uint32_t words[AF_CP_INPUT406_WORDS];
    if(actual_preset(actual,bytes,&value)!=AF_OK)return fail(r,AF_INVALID);
    pack_actual(words,&value);
    for(unsigned j=7;j<10;++j)if(words[j]!=r->captured[j])return fail(r,AF_STALE);
    if(u32((const uint8_t *)actual+AF_CP_INPUT406_VD_OFFSET)!=r->expected_vd)return fail(r,AF_STALE);
    /* 实际目的读取结束后再核源stamp；同值刷新也必须拒绝，不借九值反推版本。 */
    result=read_words(&s->records[0],now,&epoch);
    if(result!=AF_OK||epoch!=r->source_epoch)return fail(r,AF_STALE);
    for(unsigned j=0;j<AF_CP_INPUT406_WORDS;++j)words[j]=r->captured[j];
    words[4]|=AF_CP_INPUT406_VD_VALID;words[5]=r->expected_vd;
    return publish(r,t->epoch,words);
}
int af_cp_input406_read(const AfCpInput406 *s,uint32_t source,AfCpInput406Token *out){
    if(!state_valid(s)||!apart(s,sizeof(*s),out,sizeof(*out))||(uintptr_t)out%_Alignof(AfCpInput406Token))return AF_INVALID;
    int i=index_of(source);if(i<0)return AF_INVALID;
    uint32_t words[AF_CP_INPUT406_WORDS],epoch;
    int result=read_words(&s->records[i],words,&epoch);if(result!=AF_OK)return result;
    AfCpInput406Token next;
    for(size_t j=0;j<sizeof(next);++j)((uint8_t *)&next)[j]=0;
    next.version=version_of(words);next.source=source;next.epoch=epoch;next.origin_snapshot_epoch=words[6];
    next.slot=words[2];next.mode=words[3];next.flags=words[4];next.native_vd=words[5];
    unpack_actual(words,&next.actual);
    if(!epoch||!words[6]||(words[6]&1u)||words[9]>255u||
       !valid_identity(next.version,next.slot,next.mode)||af_validate(&next.actual)!=AF_OK||
       next.flags!=((next.mode==AF_CP_OVERRIDE_USER?AF_CP_INPUT406_USER_VERSION:0)|
                    (snapshot_index(i)?0:AF_CP_INPUT406_VD_VALID))||(snapshot_index(i)&&(words[5]||words[6]!=epoch)))return AF_INVALID;
    /* 显式字节复制避免引入大结构赋值的隐式目标运行库调用。 */
    for(size_t j=0;j<sizeof(next);++j)((uint8_t *)out)[j]=((uint8_t *)&next)[j];return AF_OK;
}
