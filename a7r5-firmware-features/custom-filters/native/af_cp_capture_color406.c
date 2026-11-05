/* 按原request复制事件授予Capture颜色来源；不持有原图像或原bank引用。 */
#include "af_cp_capture_color406.h"
#define MAGIC 0x43434634u
#define MASK 7u
#define RESERVED 5u
#define LIMIT 0x1fffffffu
#define BANKS 2u
typedef struct {uint32_t a,mark;} Link;
typedef struct {
    uint32_t valid,generation,refs,slot;
    uint64_t version;
    AfPreset preset;
    AfCpRuntimeAsset406 asset;
} Cache;
struct AfCpCaptureColor406 {
    AfCpCaptureColor406Ports ports;
    uint32_t magic,guard,fault,next,writers;
    uint32_t request_ready,request_bank,request_serial,publish_pending,request_id;
    AfCpInput406Token request_input;
    AfCpCaptureColor406Scope scope;
    uint32_t scope_active,scope_qualified,scope_held;
    Link links[AF_CP_CAPTURE_COLOR406_COUNT];
    Cache banks[BANKS];
};
_Static_assert(sizeof(Link)==8,"Capture color link ABI");
_Static_assert(sizeof(AfCpCaptureColor406)+54880u<65536u,"Capture combined bounded heap");
static void clear(void *p,size_t n){volatile uint8_t *d=p;for(size_t i=0;i<n;++i)d[i]=0;}
static void copy(void *p,const void *q,size_t n){uint8_t *d=p;const uint8_t *s=q;for(size_t i=0;i<n;++i)d[i]=s[i];}
static int same(const void *p,const void *q,size_t n){const uint8_t *a=p,*b=q;for(size_t i=0;i<n;++i)if(a[i]!=b[i])return 0;return 1;}
static int apart(const void *p,size_t n,const void *q,size_t m){uintptr_t a=(uintptr_t)p,b=(uintptr_t)q;return p&&q&&a<=UINTPTR_MAX-n&&b<=UINTPTR_MAX-m&&(a+n<=b||b+m<=a);}
static int valid(const AfCpCaptureColor406 *s){return s&&__atomic_load_n(&s->magic,__ATOMIC_ACQUIRE)==MAGIC;}
static int fault(const AfCpCaptureColor406 *s){return __atomic_load_n(&s->fault,__ATOMIC_ACQUIRE)!=0;}
static void poison(AfCpCaptureColor406 *s){__atomic_store_n(&s->fault,1,__ATOMIC_RELEASE);}
__attribute__((noinline)) static int lock(AfCpCaptureColor406 *s,int writer){uint32_t zero=0;if(!__atomic_compare_exchange_n(&s->guard,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED)){if(writer)poison(s);return 0;}return 1;}
static void unlock(AfCpCaptureColor406 *s){__atomic_store_n(&s->guard,0,__ATOMIC_RELEASE);}
static int address(uint32_t a){return a&&!(a&3u)&&a<=UINT32_MAX-0x6000u;}
static int fresh(AfCpCaptureColor406 *s,uint32_t *out){if(s->next==LIMIT){poison(s);return AF_EXHAUSTED;}*out=++s->next;return AF_OK;}
static unsigned find(AfCpCaptureColor406 *s,uint32_t a){unsigned i;for(i=0;i<AF_CP_CAPTURE_COLOR406_COUNT;++i)if(s->links[i].a==a)break;return i;}
static unsigned bank_of(uint32_t mark){unsigned state=mark&MASK;return state>=1&&state<=4?(state-1u)&1u:BANKS;}
static int pending(uint32_t mark){unsigned state=mark&MASK;return state==1||state==2||state==RESERVED;}
static int committed(uint32_t mark){unsigned state=mark&MASK;return state==3||state==4;}
static void drop(AfCpCaptureColor406 *s,unsigned bank){if(bank>=BANKS||!s->banks[bank].refs){poison(s);return;}--s->banks[bank].refs;}
static int hold(AfCpCaptureColor406 *s,unsigned bank){if(bank>=BANKS||!s->banks[bank].valid)return AF_STALE;if(s->banks[bank].refs>=AF_CP_CAPTURE_COLOR406_COUNT+2u){poison(s);return AF_EXHAUSTED;}++s->banks[bank].refs;return AF_OK;}
static void revoke(AfCpCaptureColor406 *s,Link *l){unsigned b=bank_of(l->mark);if(b<BANKS)drop(s,b);if(pending(l->mark)){if(s->writers)--s->writers;else poison(s);}l->mark&=~MASK;}
static int preset_same(const AfPreset *a,const AfPreset *b){return a->base==b->base&&!a->kind&&!b->kind&&same(a->params,b->params,8);}
static int input_same(const AfCpInput406Token *a,const AfCpInput406Token *b){return a->version==b->version&&a->source==b->source&&a->epoch==b->epoch&&a->origin_snapshot_epoch==b->origin_snapshot_epoch&&a->slot==b->slot&&a->mode==b->mode&&a->flags==b->flags&&a->native_vd==b->native_vd&&preset_same(&a->actual,&b->actual);}
static int input_valid(const AfCpInput406Token *t){return t&&t->source==AF_CP_CAPTURE_COLOR406_REQUEST&&t->version&&t->epoch&&!(t->epoch&1u)&&t->origin_snapshot_epoch==t->epoch&&t->slot>=1&&t->slot<=AF_USERS&&t->mode==AF_CP_OVERRIDE_USER&&t->flags==AF_CP_INPUT406_USER_VERSION&&!t->native_vd&&!t->actual.kind&&af_validate(&t->actual)==AF_OK;}
static int asset_valid(const AfCpRuntimeAsset406 *a,const AfCpInput406Token *t){
    if(!a||a->base!=t->actual.base||a->native_mode!=1||a->matrix_mode>1)return 0;
    unsigned any=0;for(unsigned i=0;i<32;++i)any|=a->model_sha256[i];if(!any)return 0;
    for(unsigned i=0;i<3;++i)if(a->native_tone[i]<-1024||a->native_tone[i]>1024)return 0;
    for(unsigned i=0;i<18;++i)if(a->matrix_mode?a->recipe.matrix[i]!=0:a->recipe.matrix[i]<-1024||a->recipe.matrix[i]>1024)return 0;
    for(unsigned i=0;i<288;++i)if(a->matrix_mode?a->sector_matrix[i]<-1024||a->sector_matrix[i]>1024:a->sector_matrix[i]!=0)return 0;
    for(unsigned i=0;i<24;++i)if(a->recipe.cc1[i]<-1024||a->recipe.cc1[i]>1024)return 0;
    for(unsigned i=0;i<AF_GRID_BYTES;++i)if(a->recipe.grid[i]<-64||a->recipe.grid[i]>63)return 0;
    return 1;
}
static int request_matches(AfCpCaptureColor406 *s,const AfCpInput406Token *t,uint32_t id,uint32_t serial){return s->request_ready&&s->request_serial==serial&&s->request_id==id&&input_same(&s->request_input,t);}
static int thread_matches(AfCpCaptureColor406 *s,uint32_t expected){uint32_t thread=0;int status=s->ports.thread(s->ports.context,&thread);return status?status:thread&&thread==expected?AF_OK:AF_STALE;}
size_t af_cp_capture_color406_bytes(void){return sizeof(AfCpCaptureColor406);}
int af_cp_capture_color406_init(AfCpCaptureColor406 *s,size_t bytes,const AfCpCaptureColor406Ports *p){
    if(!s||bytes<sizeof(*s)||(uintptr_t)s%_Alignof(AfCpCaptureColor406)||!p||!p->request||!p->thread||!p->r_matches||!apart(s,sizeof(*s),p,sizeof(*p)))return AF_INVALID;
    if(s->magic)return AF_EXISTS;clear(s,sizeof(*s));copy(&s->ports,p,sizeof(*p));s->request_bank=BANKS;__atomic_store_n(&s->magic,MAGIC,__ATOMIC_RELEASE);return AF_OK;
}
int af_cp_capture_color406_ready(const AfCpCaptureColor406 *s){return valid(s)&&!fault(s);}
int af_cp_capture_color406_a_birth(AfCpCaptureColor406 *s,uint32_t a){
    if(!valid(s)||!address(a))return AF_INVALID;if(!lock(s,1))return AF_BUSY;int status=fault(s)?AF_IO:AF_OK;unsigned i=find(s,a);uint32_t serial=0;
    if(!status&&i<AF_CP_CAPTURE_COLOR406_COUNT){revoke(s,s->links+i);poison(s);status=AF_STALE;}
    if(!status){i=find(s,0);if(i==AF_CP_CAPTURE_COLOR406_COUNT)status=AF_EXHAUSTED;else status=fresh(s,&serial);}
    if(!status){s->links[i].a=a;s->links[i].mark=serial<<3;}unlock(s);return status;
}
int af_cp_capture_color406_a_release(AfCpCaptureColor406 *s,uint32_t a){
    if(!valid(s)||!address(a))return AF_INVALID;if(!lock(s,1))return AF_BUSY;unsigned i=find(s,a);int status=i==AF_CP_CAPTURE_COLOR406_COUNT?AF_EMPTY:AF_OK;
    if(!status){Link *l=s->links+i;if(pending(l->mark)||(s->scope_active&&s->scope.a==a))poison(s);revoke(s,l);clear(l,sizeof(*l));}unlock(s);return status;
}
int af_cp_capture_color406_a_invalidate(AfCpCaptureColor406 *s,uint32_t a){
    if(!valid(s)||!address(a))return AF_INVALID;if(!lock(s,1))return AF_BUSY;
    unsigned i=find(s,a);int status=i==AF_CP_CAPTURE_COLOR406_COUNT?AF_EMPTY:AF_OK;
    if(!status){Link *l=s->links+i;if(pending(l->mark)||(s->scope_active&&s->scope.a==a))poison(s);revoke(s,l);
        uint32_t serial=0;status=fresh(s,&serial);if(!status)l->mark=serial<<3;if(fault(s)&&!status)status=AF_IO;}
    unlock(s);return status;
}
int af_cp_capture_color406_request_invalidate(AfCpCaptureColor406 *s){
    if(!valid(s))return AF_INVALID;if(!lock(s,1))return AF_BUSY;
    if(s->request_ready)drop(s,s->request_bank);s->request_ready=0;s->request_bank=BANKS;s->publish_pending=1;
    int status=fault(s)?AF_IO:fresh(s,&s->request_serial);unlock(s);return status;
}
int af_cp_capture_color406_request_publish(AfCpCaptureColor406 *s,const AfCpInput406Token *t,uint32_t id,const AfCpRuntimeAsset406 *asset){
    if(!valid(s)||!input_valid(t)||!asset_valid(asset,t)||!apart(s,sizeof(*s),t,sizeof(*t))||!apart(s,sizeof(*s),asset,sizeof(*asset)))return AF_INVALID;
    if(!lock(s,0))return AF_BUSY;uint32_t serial=s->request_serial;int status=fault(s)?AF_IO:s->publish_pending&&!s->request_ready?AF_OK:AF_STALE;unlock(s);if(status)return status;
    AfCpInput406Token observed;uint32_t observed_id=0;status=s->ports.request(s->ports.context,&observed,&observed_id);
    if(!status&&(!input_same(t,&observed)||id!=observed_id))status=AF_STALE;if(status)return status;
    if(!lock(s,1))return AF_BUSY;if(fault(s))status=AF_IO;else if(!s->publish_pending||s->request_ready||s->request_serial!=serial)status=AF_STALE;
    unsigned bank=BANKS;uint32_t generation=0;
    if(!status){for(unsigned i=0;i<BANKS;++i)if(s->banks[i].valid&&s->banks[i].version==t->version){
        Cache *b=s->banks+i;if(b->slot!=t->slot||!preset_same(&b->preset,&t->actual)||!same(&b->asset,asset,sizeof(*asset))){poison(s);status=AF_STALE;}else bank=i;break;}}
    if(!status&&bank==BANKS){for(unsigned i=0;i<BANKS;++i)if(!s->banks[i].refs){bank=i;break;}if(bank==BANKS)status=AF_BUSY;
        else if(!(status=fresh(s,&generation))){Cache *b=s->banks+bank;clear(b,sizeof(*b));b->generation=generation;b->version=t->version;b->slot=t->slot;copy(&b->preset,&t->actual,sizeof b->preset);copy(&b->asset,asset,sizeof b->asset);b->valid=1;}}
    if(!status)status=hold(s,bank);
    if(!status){copy(&s->request_input,t,sizeof *t);s->request_id=id;s->request_bank=bank;s->request_ready=1;s->publish_pending=0;}
    unlock(s);return status;
}
static int write_matches(AfCpCaptureColor406 *s,const AfCpCaptureColor406Write *w){
    const AfCpCaptureColor406Scope *t=&w->token;if(t->index>=AF_CP_CAPTURE_COLOR406_COUNT||t->bank>=BANKS)return 0;
    Link *l=s->links+t->index;return t->thread&&t->serial==(t->mark>>3)&&l->a==t->a&&l->mark==t->mark&&pending(l->mark)&&bank_of(l->mark)==t->bank&&s->banks[t->bank].generation==t->generation;
}
int af_cp_capture_color406_r_begin(AfCpCaptureColor406 *s,uint32_t a,AfCpCaptureColor406Write *out){
    if(!valid(s)||!out||!address(a)||!apart(s,sizeof(*s),out,sizeof(*out)))return AF_INVALID;
    if(!lock(s,1))return AF_BUSY;unsigned index=find(s,a);int status=fault(s)?AF_IO:index==AF_CP_CAPTURE_COLOR406_COUNT?AF_EMPTY:AF_OK;uint32_t serial=0,mark=0;
    if(!status){Link *l=s->links+index;if(pending(l->mark)||(s->scope_active&&s->scope.a==a)){poison(s);status=AF_BUSY;}revoke(s,l);
        if(!status)status=fresh(s,&serial);if(!status){mark=(serial<<3)|RESERVED;l->mark=mark;++s->writers;}}
    unlock(s);if(status)return status;
    AfCpCaptureColor406Write w;clear(&w,sizeof w);status=s->ports.thread(s->ports.context,&w.token.thread);
    if(!status&&!w.token.thread)status=AF_EMPTY;
    if(!status)status=s->ports.request(s->ports.context,&w.input,&w.request_id);
    if(!lock(s,1))return AF_BUSY;Link *l=s->links+index;
    if(fault(s))status=AF_IO;else if(l->a!=a||l->mark!=mark)status=AF_STALE;
    if(!status&&(!s->request_ready||!input_same(&s->request_input,&w.input)||s->request_id!=w.request_id))status=AF_EMPTY;
    if(l->a==a&&l->mark==mark){if(!status){unsigned bank=s->request_bank;status=hold(s,bank);
            if(!status){l->mark=(mark&~MASK)|((unsigned)bank+1u);w.token.a=a;w.token.index=index;w.token.mark=l->mark;w.token.serial=serial;w.token.bank=bank;w.token.generation=s->banks[bank].generation;w.request_serial=s->request_serial;copy(out,&w,sizeof w);}}
        if(status){l->mark&=~MASK;if(s->writers)--s->writers;}}
    unlock(s);return status;
}
int af_cp_capture_color406_r_end(AfCpCaptureColor406 *s,const AfCpCaptureColor406Write *w){
    if(!valid(s)||!w||!apart(s,sizeof(*s),w,sizeof(*w)))return AF_INVALID;
    if(!lock(s,0))return AF_BUSY;int status=fault(s)?AF_IO:write_matches(s,w)?AF_OK:AF_STALE;unlock(s);if(status)return status;
    status=thread_matches(s,w->token.thread);AfCpInput406Token input;uint32_t id=0;
    if(!status)status=s->ports.request(s->ports.context,&input,&id);
    if(!status&&(!input_same(&input,&w->input)||id!=w->request_id))status=AF_STALE;
    if(!status)status=s->ports.r_matches(s->ports.context,w->token.a+AF_CP_CAPTURE_COLOR406_R_OFFSET,&w->input.actual);
    if(!status)status=thread_matches(s,w->token.thread);
    if(!lock(s,1))return AF_BUSY;int owned=write_matches(s,w);
    if(fault(s))status=AF_IO;else if(!owned||!request_matches(s,&w->input,w->request_id,w->request_serial))status=AF_STALE;
    if(owned){Link *l=s->links+w->token.index;if(status)revoke(s,l);else{l->mark=(l->mark&~MASK)|(w->token.bank+3u);if(s->writers)--s->writers;else{poison(s);status=AF_IO;}}}
    unlock(s);return status;
}
static int scope_matches(AfCpCaptureColor406 *s,const AfCpCaptureColor406Scope *t){return s->scope_active&&same(&s->scope,t,sizeof *t);}
static int qualified(AfCpCaptureColor406 *s,const AfCpCaptureColor406Scope *t){
    if(!scope_matches(s,t)||!s->scope_qualified||t->index>=AF_CP_CAPTURE_COLOR406_COUNT||t->bank>=BANKS)return 0;
    Link *l=s->links+t->index;return l->a==t->a&&l->mark==t->mark&&committed(l->mark)&&bank_of(l->mark)==t->bank&&s->banks[t->bank].valid&&s->banks[t->bank].generation==t->generation;
}
int af_cp_capture_color406_scope_begin(AfCpCaptureColor406 *s,uint32_t r,AfCpCaptureColor406Scope *out){
    if(!valid(s)||!out||!apart(s,sizeof(*s),out,sizeof(*out)))return AF_INVALID;clear(out,sizeof *out);
    if(!lock(s,1))return AF_BUSY;int status=fault(s)?AF_IO:AF_OK;
    if(s->scope_active){poison(s);status=AF_BUSY;}uint32_t serial=0;if(!status)status=fresh(s,&serial);
    if(!status){clear(&s->scope,sizeof s->scope);s->scope.index=AF_CP_CAPTURE_COLOR406_COUNT;s->scope.bank=BANKS;s->scope.serial=serial;s->scope_active=1;s->scope_qualified=0;s->scope_held=0;
        if(r>=AF_CP_CAPTURE_COLOR406_R_OFFSET&&address(r-AF_CP_CAPTURE_COLOR406_R_OFFSET)){uint32_t a=r-AF_CP_CAPTURE_COLOR406_R_OFFSET;unsigned i=find(s,a);s->scope.a=a;
            if(i<AF_CP_CAPTURE_COLOR406_COUNT&&committed(s->links[i].mark)){unsigned b=bank_of(s->links[i].mark);status=hold(s,b);if(!status){s->scope.index=i;s->scope.mark=s->links[i].mark;s->scope.bank=b;s->scope.generation=s->banks[b].generation;s->scope_qualified=1;s->scope_held=1;}}}
        copy(out,&s->scope,sizeof *out);}
    unlock(s);if(status)return status;
    uint32_t thread=0;int got=s->ports.thread(s->ports.context,&thread);
    if(!lock(s,1))return AF_BUSY;status=fault(s)?AF_IO:AF_OK;
    if(!status&&(!s->scope_active||s->scope.serial!=serial))status=AF_STALE;
    if(!status){s->scope.thread=thread;copy(out,&s->scope,sizeof *out);if(got||!thread||!s->scope_qualified){s->scope_qualified=0;status=got?got:AF_EMPTY;}}
    unlock(s);if(status)return status;
    AfCpCaptureColor406View v;status=af_cp_capture_color406_view(s,&v);
    if(status){if(!lock(s,1))return AF_BUSY;if(s->scope_active&&s->scope.serial==serial)s->scope_qualified=0;unlock(s);}return status;
}
int af_cp_capture_color406_current(AfCpCaptureColor406 *s,const AfCpCaptureColor406View *v){
    if(!valid(s)||!v||!apart(s,sizeof(*s),v,sizeof(*v)))return AF_INVALID;
    if(!lock(s,0))return AF_BUSY;int status=fault(s)?AF_IO:!qualified(s,&v->token)?AF_STALE:AF_OK;
    if(!status){Cache *b=s->banks+v->token.bank;if(v->asset!=&b->asset||v->preset!=&b->preset||v->version!=b->version||v->slot!=b->slot)status=AF_STALE;}
    unlock(s);if(status)return status;
    status=thread_matches(s,v->token.thread);
    if(!status)status=s->ports.r_matches(s->ports.context,v->token.a+AF_CP_CAPTURE_COLOR406_R_OFFSET,v->preset);
    if(!status)status=thread_matches(s,v->token.thread);
    if(!lock(s,0))return AF_BUSY;int current=fault(s)?AF_IO:qualified(s,&v->token)?AF_OK:AF_STALE;unlock(s);return current?current:status;
}
int af_cp_capture_color406_scope_observe(AfCpCaptureColor406 *s,uint32_t r,AfCpCaptureColor406Scope *out){
    if(!valid(s)||!out||!apart(s,sizeof(*s),out,sizeof(*out)))return AF_INVALID;
    if(!lock(s,0))return AF_BUSY;AfCpCaptureColor406Scope token;int status=fault(s)?AF_IO:AF_OK;
    if(!status&&(!s->scope_active||!s->scope.thread||!s->scope.a||r!=s->scope.a+AF_CP_CAPTURE_COLOR406_R_OFFSET))status=AF_EMPTY;
    if(!status)copy(&token,&s->scope,sizeof token);unlock(s);if(status)return status;
    status=thread_matches(s,token.thread);if(!lock(s,0))return AF_BUSY;
    if(fault(s))status=AF_IO;else if(!scope_matches(s,&token))status=AF_STALE;
    if(!status)copy(out,&token,sizeof token);unlock(s);return status;
}
int af_cp_capture_color406_view(AfCpCaptureColor406 *s,AfCpCaptureColor406View *out){
    if(!valid(s)||!out||!apart(s,sizeof(*s),out,sizeof(*out)))return AF_INVALID;
    if(!lock(s,0))return AF_BUSY;int status=fault(s)?AF_IO:!qualified(s,&s->scope)?AF_EMPTY:AF_OK;AfCpCaptureColor406View v;
    if(!status){Cache *b=s->banks+s->scope.bank;copy(&v.token,&s->scope,sizeof v.token);v.asset=&b->asset;v.preset=&b->preset;v.version=b->version;v.slot=b->slot;}
    unlock(s);if(status)return status;status=af_cp_capture_color406_current(s,&v);
    if(!lock(s,0))return AF_BUSY;if(fault(s))status=AF_IO;else if(!qualified(s,&v.token))status=AF_STALE;
    if(!status)copy(out,&v,sizeof v);unlock(s);return status;
}
int af_cp_capture_color406_scope_end(AfCpCaptureColor406 *s,const AfCpCaptureColor406Scope *t){
    if(!valid(s)||!t||!apart(s,sizeof(*s),t,sizeof(*t)))return AF_INVALID;int got=t->thread?thread_matches(s,t->thread):AF_OK;
    if(!lock(s,1))return AF_BUSY;int status=scope_matches(s,t)?AF_OK:AF_STALE;
    if(!status){if(got){poison(s);status=got;}if(s->scope_held)drop(s,s->scope.bank);s->scope_active=0;s->scope_qualified=0;s->scope_held=0;}
    if(fault(s))status=AF_IO;unlock(s);return status;
}
int af_cp_capture_color406_pool_reset(AfCpCaptureColor406 *s){
    if(!valid(s))return AF_INVALID;if(!lock(s,1))return AF_BUSY;
    if(s->writers||s->scope_active)poison(s);
    for(unsigned i=0;i<AF_CP_CAPTURE_COLOR406_COUNT;++i)if(s->links[i].a){revoke(s,s->links+i);clear(s->links+i,sizeof(Link));}
    if(s->request_ready)drop(s,s->request_bank);s->request_ready=0;s->request_bank=BANKS;s->publish_pending=0;s->scope_qualified=0;
    uint32_t ignored;int status=fresh(s,&ignored);if(fault(s)&&!status)status=AF_IO;unlock(s);return status;
}
