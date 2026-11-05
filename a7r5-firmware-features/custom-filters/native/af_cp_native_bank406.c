/* 原0x24锁串行发布/借用；原worker跨任务仅按唯一票据归还32位引用。 */
#include "af_cp_native_bank406.h"

_Static_assert(__atomic_always_lock_free(4,0),"native banks require lock-free 32-bit atomics");
enum { TICKET_FREE=0,TICKET_WRITING=1,TICKET_HELD=2,TICKET_RELEASING=3 };
static uint32_t load(const uint32_t *p){return __atomic_load_n(p,__ATOMIC_SEQ_CST);}
static void store(uint32_t *p,uint32_t n){__atomic_store_n(p,n,__ATOMIC_SEQ_CST);}
static int claim(uint32_t *p,uint32_t old,uint32_t next){
    return __atomic_compare_exchange_n(p,&old,next,0,__ATOMIC_SEQ_CST,__ATOMIC_SEQ_CST);
}
static int range(const void *p,size_t n){return p&&n&&(uintptr_t)p<=UINTPTR_MAX-n;}
static int apart(const void *a,size_t n,const void *b,size_t m){
    return range(a,n)&&range(b,m)&&((uintptr_t)a+n<=(uintptr_t)b||(uintptr_t)b+m<=(uintptr_t)a);
}
static int state_range(const AfCpNativeBanks406 *s){
    return range(s,sizeof(*s))&&!((uintptr_t)s%_Alignof(AfCpNativeBanks406));
}
static int worker_index(uint32_t worker){return worker==2?0:worker==3?1:worker==6?2:-1;}
static int preset_valid(const AfPreset *p){return range(p,sizeof(*p))&&af_validate(p)==AF_OK;}
static int same_actual(const AfPreset *a,const AfPreset *b){
    unsigned changed=a->base^b->base;
    for(unsigned i=0;i<AF_PARAMETERS;++i)changed|=(uint8_t)a->params[i]^(uint8_t)b->params[i];
    return !changed;
}
static void copy_bytes(void *out,const void *in,size_t n){
    for(size_t i=0;i<n;++i)((uint8_t *)out)[i]=((const uint8_t *)in)[i];
}
static int override_valid(const AfCpOverride406 *s){
    if(s->mode==AF_CP_OVERRIDE_NATIVE)return !s->slot;
    return s->version&&preset_valid(&s->preset)&&!s->preset.kind&&
        ((s->mode==AF_CP_OVERRIDE_USER&&s->slot>=1&&s->slot<=AF_USERS)||
         (s->mode==AF_CP_OVERRIDE_FACTORY_PENDING&&!s->slot));
}
size_t af_cp_native_bank406_bytes(void){return sizeof(AfCpNativeBanks406);}
int af_cp_native_bank406_accept_locked(AfCpNativeBanks406 *s,AfCpOverride406 *override,
    uint64_t version,uint32_t slot,const AfPreset *preset,const AfJointAsset *asset,uint8_t *marker){
    if(!state_range(s)||s->active>AF_CP_NATIVE_BANKS406||!version||slot<1||slot>AF_USERS||
       !range(override,sizeof(*override))||(uintptr_t)override%_Alignof(AfCpOverride406)||
       !preset_valid(preset)||!preset->kind||!range(asset,sizeof(*asset))||
       (uintptr_t)asset%_Alignof(AfJointAsset)||!range(marker,1)||
       !apart(s,sizeof(*s),override,sizeof(*override))||!apart(s,sizeof(*s),preset,sizeof(*preset))||
       !apart(s,sizeof(*s),asset,sizeof(*asset))||!apart(s,sizeof(*s),marker,1)||
       !apart(override,sizeof(*override),preset,sizeof(*preset))||
       !apart(override,sizeof(*override),asset,sizeof(*asset))||!apart(override,sizeof(*override),marker,1)||
       !apart(preset,sizeof(*preset),asset,sizeof(*asset))||!apart(preset,sizeof(*preset),marker,1)||
       !apart(asset,sizeof(*asset),marker,1)||!override_valid(override))return AF_INVALID;
    if(asset->native_mode!=1)return AF_JOINT_ASSET_UNSUPPORTED;
    if(asset->matrix_mode>1)return AF_JOINT_ASSET_UNSUPPORTED;
    int supported=af_joint_matrix_native406_representable(asset->base,asset->matrix_mode,
        asset->recipe.matrix,asset->sector_matrix);
    if(supported)return supported;
    for(unsigned i=0;i<288;++i)
        if(asset->matrix_mode?(asset->sector_matrix[i]<-1024||asset->sector_matrix[i]>1024):asset->sector_matrix[i]!=0)return AF_INVALID;
    if(asset->matrix_mode)for(unsigned i=0;i<18;++i)if(asset->recipe.matrix[i])return AF_INVALID;
    if(asset->base!=preset->base||af_joint_valid(&asset->recipe)!=AF_OK||
       af_joint_gamma_matches(asset->native_seed,asset->native_tone,asset->recipe.gamma)!=AF_OK)return AF_INVALID;
    unsigned model=0;for(unsigned i=0;i<32;++i)model|=asset->model_sha256[i];
    if(!model)return AF_INVALID;
    if(version<=override->version)return AF_STALE;
    if(s->generation==UINT64_MAX)return AF_EXHAUSTED;
    unsigned index=AF_CP_NATIVE_BANKS406;
    for(unsigned i=0;i<AF_CP_NATIVE_BANKS406;++i)
        if(s->active!=i+1u&&!load(&s->banks[i].refs)){index=i;break;}
    if(index==AF_CP_NATIVE_BANKS406)return AF_BUSY;
    AfCpNativeBank406 *b=&s->banks[index];AfPreset projection;
    /* 逐字节volatile清零，避免freestanding Thumb引入未提供的memclr helper。 */
    for(size_t i=0;i<sizeof(projection);++i)((volatile uint8_t *)&projection)[i]=0;
    projection.base=preset->base;
    for(unsigned i=0;i<AF_PARAMETERS;++i)projection.params[i]=preset->params[i];
    /* refs0且非active才可写候选；原发布若失败，不改变active或已借用旧对象。 */
    b->valid=0;
    af_cp_runtime_asset406_copy_validated(&b->asset,asset);
    copy_bytes(&b->preset,preset,sizeof(*preset));
    int result=af_cp_override406_publish_locked(override,version,slot,&projection,marker);
    if(result!=AF_OK)return result;
    b->slot=slot;b->version=version;b->generation=++s->generation;b->valid=1;
    s->active=index+1u;return AF_OK;
}
int af_cp_native_bank406_borrow_locked(AfCpNativeBanks406 *s,const AfCpInput406Token *token,
    uint32_t worker,AfCpNativeLease406 *out){
    int wi=worker_index(worker);
    if(!state_range(s)||s->active>AF_CP_NATIVE_BANKS406||wi<0||
       !apart(s,sizeof(*s),token,sizeof(*token))||!apart(s,sizeof(*s),out,sizeof(*out))||
       !apart(token,sizeof(*token),out,sizeof(*out))||(uintptr_t)token%_Alignof(AfCpInput406Token)||
       (uintptr_t)out%_Alignof(AfCpNativeLease406)||!token->version||token->slot<1||token->slot>AF_USERS||
       token->mode!=AF_CP_OVERRIDE_USER||!(token->flags&AF_CP_INPUT406_USER_VERSION)||
       !preset_valid(&token->actual)||token->actual.kind)return AF_INVALID;
    unsigned index=AF_CP_NATIVE_BANKS406;
    for(unsigned i=0;i<AF_CP_NATIVE_BANKS406;++i){
        const AfCpNativeBank406 *b=&s->banks[i];
        if(b->valid&&b->version==token->version&&b->slot==token->slot&&
           same_actual(&b->preset,&token->actual)){index=i;break;}
    }
    if(index==AF_CP_NATIVE_BANKS406)return AF_STALE;
    if(s->next_lease==UINT64_MAX)return AF_EXHAUSTED;
    AfCpNativeTicket406 *ticket=&s->leases[wi];
    if(!claim(&ticket->state,TICKET_FREE,TICKET_WRITING))return AF_BUSY;
    AfCpNativeBank406 *b=&s->banks[index];
    if(load(&b->refs)>=AF_CP_NATIVE_WORKERS406){store(&ticket->state,TICKET_FREE);return AF_EXHAUSTED;}
    /* 其他borrow同锁串行，release只减少；先取得引用再发布唯一票据。 */
    (void)__atomic_fetch_add(&b->refs,1,__ATOMIC_SEQ_CST);
    ticket->bank=index;ticket->generation=b->generation;ticket->version=b->version;ticket->ticket=++s->next_lease;
    AfCpNativeLease406 value={worker,index,b->generation,b->version,ticket->ticket,&b->asset,&b->preset};
    store(&ticket->state,TICKET_HELD);
    copy_bytes(out,&value,sizeof(value));return AF_OK;
}
int af_cp_native_bank406_release(AfCpNativeBanks406 *s,const AfCpNativeLease406 *lease){
    if(!state_range(s)||!apart(s,sizeof(*s),lease,sizeof(*lease))||
       (uintptr_t)lease%_Alignof(AfCpNativeLease406))return AF_INVALID;
    int wi=worker_index(lease->worker);
    if(wi<0||lease->bank>=AF_CP_NATIVE_BANKS406||!lease->generation||!lease->version||!lease->ticket)return AF_INVALID;
    AfCpNativeTicket406 *t=&s->leases[wi];
    if(!claim(&t->state,TICKET_HELD,TICKET_RELEASING))return load(&t->state)==TICKET_FREE?AF_STALE:AF_BUSY;
    AfCpNativeBank406 *b=&s->banks[lease->bank];
    if(t->bank!=lease->bank||t->generation!=lease->generation||t->version!=lease->version||
       t->ticket!=lease->ticket||lease->asset!=&b->asset||lease->preset!=&b->preset||
       !b->valid||b->generation!=lease->generation||b->version!=lease->version||!load(&b->refs)){
        store(&t->state,TICKET_HELD);return AF_STALE;
    }
    /* 只有唯一匹配票据的CAS赢家能减一次；减完不再读取可被下一accept重用的bank。 */
    (void)__atomic_fetch_sub(&b->refs,1,__ATOMIC_SEQ_CST);
    store(&t->state,TICKET_FREE);return AF_OK;
}
int af_cp_native_bank406_clear_active_locked(AfCpNativeBanks406 *s){
    if(!state_range(s)||s->active>AF_CP_NATIVE_BANKS406)return AF_INVALID;
    s->active=0;return AF_OK;
}
