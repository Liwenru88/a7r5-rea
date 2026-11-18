/* 原Capture按值伴随；失败只撤销私有资格，不持有原图像引用。 */
#include "af_cp_capture406.h"
#include "af_cp_capture_fields406.h"
#define MAGIC 0x43415034u
#define LIVE 1u
#define WRITING 2u
#define RESTORING 4u
#define PENDING 8u
#define STAMPED 16u
static void copy(void *a,const void *b,size_t n){uint8_t *d=a;const uint8_t *s=b;for(size_t i=0;i<n;++i)d[i]=s[i];}
static void clear(void *a,size_t n){volatile uint8_t *d=a;for(size_t i=0;i<n;++i)d[i]=0;}
static int same(const void *a,const void *b,size_t n){const uint8_t *x=a,*y=b;for(size_t i=0;i<n;++i)if(x[i]!=y[i])return 0;return 1;}
static int apart(const void *a,size_t n,const void *b,size_t m){uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);}
static uint32_t word(const uint8_t *p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static int valid(const AfCpCapture406 *s){return s&&__atomic_load_n(&s->magic,__ATOMIC_ACQUIRE)==MAGIC&&s->records;}
static int fault(const AfCpCapture406 *s){return __atomic_load_n(&s->fault,__ATOMIC_ACQUIRE)!=0;}
static void poison(AfCpCapture406 *s){__atomic_store_n(&s->fault,1,__ATOMIC_RELEASE);}
/* 两段被多入口共享，禁止逐入口展开原子序列以守住固定RX预算。 */
__attribute__((noinline)) static int lock(AfCpCapture406 *s,int writer){uint32_t zero=0;if(!__atomic_compare_exchange_n(&s->guard,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED)){if(writer)poison(s);return 0;}return 1;}
static void unlock(AfCpCapture406 *s){__atomic_store_n(&s->guard,0,__ATOMIC_RELEASE);}
__attribute__((noinline)) static int usable(AfCpCapture406 *s){return fault(s)?AF_IO:s->pool_busy?AF_BUSY:AF_OK;}
static int address(uint32_t a){return a&&!(a&3u)&&a<=UINT32_MAX-AF_CP_CAPTURE406_D-0x3au;}
static unsigned find(AfCpCapture406 *s,uint32_t a){unsigned i;for(i=0;i<AF_CP_CAPTURE406_COUNT;++i)if(s->records[i].a==a)return i;return i;}
static int advance(AfCpCapture406 *s,AfCpCapture406Record *r){if(r->epoch==UINT32_MAX){poison(s);return AF_EXHAUSTED;}++r->epoch;return AF_OK;}
static void token(AfCpCapture406Token *t,const AfCpCapture406Record *r,unsigned i,uint32_t thread,uint32_t serial,unsigned channel){t->birth=r->birth;t->a=r->a;t->epoch=r->epoch;t->thread=thread;t->serial=serial;t->channel=channel;t->index=i;}
static AfCpCapture406Record *record(AfCpCapture406 *s,const AfCpCapture406Token *t){if(t->index>=AF_CP_CAPTURE406_COUNT)return 0;AfCpCapture406Record *r=s->records+t->index;return (r->flags&LIVE)&&r->a==t->a&&r->birth==t->birth&&r->epoch==t->epoch?r:0;}
static int writing(AfCpCapture406 *s,const AfCpCapture406Token *t,unsigned kind,AfCpCapture406Record **out){AfCpCapture406Record *r=record(s,t);if(!r||!(r->flags&WRITING)||t->serial!=r->epoch||t->channel!=kind||r->thread!=t->thread||!!(r->flags&RESTORING)!=(kind==AF_CP_CAPTURE406_RESTORE))return AF_STALE;*out=r;return AF_OK;}
static int scope(AfCpCapture406 *s,const AfCpCapture406Token *t){return s->scope_active&&same(&s->scope,t,sizeof *t);}
static uint32_t formatter(unsigned ch){return ch?0x1f6e390u:0x1f6dfdcu;}
static uint32_t output(unsigned ch){return ch?0x1f709f4u:0x1f6ff74u;}
size_t af_cp_capture406_records_bytes(void){return AF_CP_CAPTURE406_COUNT*sizeof(AfCpCapture406Record);}
int af_cp_capture406_init(AfCpCapture406 *s,const AfCpCapture406Ports *p,void *records,size_t bytes){
    size_t n=af_cp_capture406_records_bytes();
    if(!s||!p||!p->read||!p->thread||!p->shadow||bytes<n||((uintptr_t)records&7u)||
       !apart(s,sizeof *s,records,n)||!apart(s,sizeof *s,p,sizeof *p)||!apart(records,n,p,sizeof *p))return AF_INVALID;
    if(__atomic_load_n(&s->magic,__ATOMIC_ACQUIRE))return AF_EXISTS;
    clear(s,sizeof *s);clear(records,n);s->ports=*p;s->records=records;
    __atomic_store_n(&s->magic,MAGIC,__ATOMIC_RELEASE);return AF_OK;
}
int af_cp_capture406_ready(const AfCpCapture406 *s){return valid(s)&&!fault(s)&&!__atomic_load_n(&s->pool_busy,__ATOMIC_ACQUIRE);}
int af_cp_capture406_birth(AfCpCapture406 *s,uint32_t a){
    if(!valid(s)||!address(a))return AF_INVALID;if(!lock(s,1))return AF_BUSY;
    int status=usable(s);unsigned i=AF_CP_CAPTURE406_COUNT;
    if(!status){i=find(s,a);if(i<AF_CP_CAPTURE406_COUNT){s->records[i].flags=0;poison(s);status=AF_STALE;}}
    if(!status&&s->next_birth==UINT64_MAX){poison(s);status=AF_EXHAUSTED;}
    if(!status){for(i=0;i<AF_CP_CAPTURE406_COUNT&&s->records[i].a;++i){}if(i==AF_CP_CAPTURE406_COUNT)status=AF_EXHAUSTED;}
    if(!status){AfCpCapture406Record *r=s->records+i;clear(r,sizeof *r);r->a=a;r->birth=++s->next_birth;r->epoch=1;r->flags=LIVE;}
    unlock(s);return status;
}
int af_cp_capture406_release(AfCpCapture406 *s,uint32_t a){
    if(!valid(s)||!address(a))return AF_INVALID;if(!lock(s,1))return AF_BUSY;
    unsigned i=find(s,a);int status=i==AF_CP_CAPTURE406_COUNT?AF_EMPTY:AF_OK;
    if(!status){AfCpCapture406Record *r=s->records+i;if((r->flags&WRITING)||(s->scope_active&&s->scope.a==a))poison(s);clear(r,sizeof *r);}
    unlock(s);return status;
}
int af_cp_capture406_write_begin(AfCpCapture406 *s,uint32_t a,unsigned kind,AfCpCapture406Token *out){
    if(!valid(s)||!out||!address(a)||(kind!=1&&kind!=2))return AF_INVALID;clear(out,sizeof *out);
    uint32_t tid=0;int got=s->ports.thread(s->ports.context,&tid);
    if(!lock(s,1))return AF_BUSY;int status=usable(s);unsigned i=find(s,a);
    if(i<AF_CP_CAPTURE406_COUNT){AfCpCapture406Record *r=s->records+i;unsigned active=r->flags&WRITING;
        r->flags&=~(STAMPED|PENDING);int changed=advance(s,r);
        if(active||(s->scope_active&&s->scope.a==a)){poison(s);status=AF_BUSY;}
        if(changed)status=changed;
        if(!status&&got)status=got;
        if(!status&&!tid)status=AF_EMPTY;
        if(!status){r->thread=tid;r->flags=LIVE|WRITING|(kind==2?RESTORING:0);token(out,r,i,tid,r->epoch,kind);}
        else r->flags=LIVE;
    }else if(!status)status=AF_EMPTY;
    unlock(s);return status;
}
int af_cp_capture406_reverse_begin(AfCpCapture406 *s,uint32_t d,AfCpCapture406Reverse *out){
    if(!valid(s)||!out||d<AF_CP_CAPTURE406_D||!address(d-AF_CP_CAPTURE406_D))return AF_INVALID;
    uint32_t tid=0;int status=s->ports.thread(s->ports.context,&tid);if(status)return status;
    AfCpCapture406Reverse v;if(!lock(s,1))return AF_BUSY;status=usable(s);unsigned i=find(s,d-AF_CP_CAPTURE406_D);
    if(!status&&(i==AF_CP_CAPTURE406_COUNT||!(s->records[i].flags&WRITING)||(s->records[i].flags&RESTORING)||s->records[i].thread!=tid))status=AF_EMPTY;
    if(!status){s->records[i].flags&=~PENDING;token(&v.token,s->records+i,i,tid,s->records[i].epoch,1);}
    unlock(s);if(status)return status;
    status=s->ports.shadow(s->ports.context,&v.tone,v.shadow);if(!status)status=s->ports.thread(s->ports.context,&tid);if(!status&&tid!=v.token.thread)status=AF_STALE;if(status)return status;
    if(!lock(s,0))return AF_BUSY;AfCpCapture406Record *r;status=usable(s);if(!status)status=writing(s,&v.token,1,&r);
    if(!status)copy(out,&v,sizeof v);unlock(s);return status;
}
int af_cp_capture406_reverse_end(AfCpCapture406 *s,uint32_t d,const AfCpCapture406Reverse *v){
    if(!valid(s)||!v||d!=v->token.a+AF_CP_CAPTURE406_D)return AF_INVALID;
    uint32_t tid=0;AfCpGamma406Tone tone;uint8_t shadow[84],raw[0x3a],fields[47];
    int status=s->ports.thread(s->ports.context,&tid);if(!status&&tid!=v->token.thread)status=AF_STALE;
    if(!status)status=s->ports.shadow(s->ports.context,&tone,shadow);
    if(!status&&(!same(&tone,&v->tone,sizeof tone)||!same(shadow,v->shadow,84)))status=AF_STALE;
    if(!status)status=s->ports.read(s->ports.context,d,raw,sizeof raw);
    if(!status)status=af_cp_capture_fields406_matches(v->shadow,raw);
    if(!status)status=af_cp_capture_fields406_normalize(raw,fields);
    if(!status)status=s->ports.thread(s->ports.context,&tid);if(!status&&tid!=v->token.thread)status=AF_STALE;
    if(!lock(s,1))return AF_BUSY;AfCpCapture406Record *r=0;int current=usable(s);if(!current)current=writing(s,&v->token,1,&r);
    if(current)status=current;
    if(r){r->flags&=~PENDING;if(!status){r->tone=v->tone;copy(r->fields,fields,47);r->flags|=PENDING;}}
    unlock(s);return status;
}
int af_cp_capture406_write_end(AfCpCapture406 *s,const AfCpCapture406Token *t,unsigned kind){
    if(!valid(s)||!t||(kind!=1&&kind!=2))return AF_INVALID;
    if(!lock(s,1))return AF_BUSY;AfCpCapture406Record *r=0;int status=usable(s);if(!status)status=writing(s,t,kind,&r);
    uint8_t expected[47];int pending=!status&&(r->flags&PENDING)&&kind==1;
    if(!status&&pending)copy(expected,r->fields,47);unlock(s);if(status)return status;
    uint8_t raw[0x3a],fields[47];uint32_t tid=0;
    if(pending){status=s->ports.thread(s->ports.context,&tid);if(!status&&tid!=t->thread)status=AF_STALE;
        if(!status)status=s->ports.read(s->ports.context,t->a+AF_CP_CAPTURE406_D,raw,sizeof raw);
        if(!status)status=af_cp_capture_fields406_normalize(raw,fields);
        if(!status&&!same(fields,expected,47))status=AF_STALE;
        if(!status)status=s->ports.thread(s->ports.context,&tid);if(!status&&tid!=t->thread)status=AF_STALE;
    }
    if(!lock(s,1))return AF_BUSY;int current=usable(s);if(!current)current=writing(s,t,kind,&r);
    if(current)status=current;
    if(!current){r->flags=LIVE|(!status&&pending?STAMPED:0);if(!pending&&!status)status=AF_EMPTY;}
    unlock(s);return status;
}
int af_cp_capture406_scope_begin(AfCpCapture406 *s,uint32_t g,AfCpCapture406Token *out){
    if(!valid(s)||!out)return AF_INVALID;clear(out,sizeof *out);if(!lock(s,1))return AF_BUSY;
    int status=usable(s);if(s->scope_active){poison(s);status=AF_BUSY;}
    if(!status&&s->sequence==UINT32_MAX){poison(s);status=AF_EXHAUSTED;}
    if(!status){clear(&s->scope,sizeof s->scope);s->scope.serial=++s->sequence;s->scope.index=UINT32_MAX;s->scope_active=1;s->scope_qualified=0;s->scope_formatted=0;s->scope_formatter=0;*out=s->scope;}
    unlock(s);if(status)return status;
    uint8_t image[8];uint32_t tid=0;int read=s->ports.thread(s->ports.context,&tid);
    if(!read&&g>=AF_CP_CAPTURE406_G&&address(g-AF_CP_CAPTURE406_G))read=s->ports.read(s->ports.context,g,image,sizeof image);else if(!read)read=AF_EMPTY;
    if(!lock(s,1))return AF_BUSY;status=usable(s);
    if(!status&&(!s->scope_active||s->scope.serial!=out->serial))status=AF_STALE;
    if(!status){s->scope.thread=tid;if(read||!tid||image[0]>1||(image[3]&&word(image+4)))status=read?read:AF_EMPTY;
        else{unsigned i=find(s,g-AF_CP_CAPTURE406_G);if(i==AF_CP_CAPTURE406_COUNT||(s->records[i].flags&(LIVE|STAMPED|WRITING))!=(LIVE|STAMPED))status=AF_EMPTY;
            else{token(&s->scope,s->records+i,i,tid,s->scope.serial,image[0]);s->scope_qualified=1;}}
        *out=s->scope;
    }
    unlock(s);return status;
}
/* 只检查本次原调用的身份及D写集；所有原内存读取在私有guard之外。 */
static int inspect(AfCpCapture406 *s,const AfCpCapture406Token *t){
    if(!lock(s,0))return AF_BUSY;int status=usable(s);AfCpCapture406Record *r=record(s,t);uint8_t expected[47];
    if(!status&&(!scope(s,t)||!s->scope_qualified||!r||(r->flags&(STAMPED|WRITING))!=STAMPED))status=AF_STALE;
    if(!status)copy(expected,r->fields,47);unlock(s);if(status)return status;
    uint32_t tid=0;uint8_t g[8],raw[0x3a],fields[47];status=s->ports.thread(s->ports.context,&tid);
    if(!status&&tid!=t->thread)status=AF_STALE;
    if(!status)status=s->ports.read(s->ports.context,t->a+AF_CP_CAPTURE406_G,g,sizeof g);
    if(!status&&(g[0]!=t->channel||(g[3]&&word(g+4))))status=AF_STALE;
    if(!status)status=s->ports.read(s->ports.context,t->a+AF_CP_CAPTURE406_D,raw,sizeof raw);
    if(!status)status=af_cp_capture_fields406_normalize(raw,fields);
    if(!status&&!same(fields,expected,47))status=AF_STALE;
    if(!status)status=s->ports.thread(s->ports.context,&tid);if(!status&&tid!=t->thread)status=AF_STALE;
    if(!lock(s,0))return AF_BUSY;int current=usable(s);r=record(s,t);
    if(!current&&(!scope(s,t)||!s->scope_qualified||!r||(r->flags&(STAMPED|WRITING))!=STAMPED||!same(r->fields,expected,47)))current=AF_STALE;
    unlock(s);return current?current:status;
}
int af_cp_capture406_scope_current(AfCpCapture406 *s,const AfCpCapture406Token *t){if(!valid(s)||!t)return AF_INVALID;return inspect(s,t);}
int af_cp_capture406_format_begin(AfCpCapture406 *s,uint32_t d,uint32_t f,AfCpCapture406Token *out){
    if(!valid(s)||!out)return AF_INVALID;clear(out,sizeof *out);uint32_t tid=0;int got=s->ports.thread(s->ports.context,&tid);if(!lock(s,1))return AF_BUSY;
    int status=usable(s);AfCpCapture406Token t=s->scope;
    /* 无Bstamp的原厂scope没有A/channel来源身份，也不允许私有消费；不能据零token误判外来写者。
     * 原845DB8重入仍在scope_begin统一poison，已获资格scope的格式写者冲突保持严格拒绝。 */
    if(s->scope_active&&s->scope_qualified&&f==formatter(t.channel)&&(s->scope_formatted==2||got||tid!=t.thread||d!=t.a+AF_CP_CAPTURE406_D)){poison(s);status=AF_BUSY;}
    if(s->scope_active&&f==formatter(t.channel))s->scope_formatted=0;
    if(!status&&(!s->scope_active||!s->scope_qualified||d!=t.a+AF_CP_CAPTURE406_D||f!=formatter(t.channel)))status=AF_EMPTY;
    unlock(s);if(status)return status;status=inspect(s,&t);
    if(status==AF_STALE){poison(s);return status;}if(status)return status;
    if(!lock(s,1))return AF_BUSY;status=usable(s);if(!status&&!scope(s,&t))status=AF_STALE;
    if(!status){s->scope_formatted=2;s->scope_formatter=f;*out=t;}
    unlock(s);return status;
}
int af_cp_capture406_format_end(AfCpCapture406 *s,uint32_t d,uint32_t f,const AfCpCapture406Token *t){
    if(!valid(s)||!t)return AF_INVALID;int status=inspect(s,t);
    if(!lock(s,1))return AF_BUSY;int current=usable(s);
    if(!current&&(!scope(s,t)||s->scope_formatted!=2||s->scope_formatter!=f||f!=formatter(t->channel)||d!=t->a+AF_CP_CAPTURE406_D))current=AF_STALE;
    if(current)status=current;
    if(scope(s,t))s->scope_formatted=status?0:1;
    unlock(s);return status;
}
int af_cp_capture406_scope_read(AfCpCapture406 *s,uint32_t f,uint32_t o,AfCpGamma406Tone *tone,AfCpCapture406Token *out,uint8_t image[0x4e]){
    if(!valid(s)||!tone||!out||!image)return AF_INVALID;if(!lock(s,0))return AF_BUSY;
    int status=usable(s);AfCpCapture406Token t=s->scope;AfCpGamma406Tone saved;
    if(!status&&(!s->scope_active||!s->scope_qualified||s->scope_formatted!=1||s->scope_formatter!=f||f!=formatter(t.channel)||o!=output(t.channel)))status=AF_EMPTY;
    AfCpCapture406Record *r=record(s,&t);if(!status&&!r)status=AF_STALE;if(!status)saved=r->tone;
    unlock(s);if(status)return status;status=inspect(s,&t);if(status)return status;
    uint8_t snapshot[0x4e];status=s->ports.read(s->ports.context,f,snapshot,sizeof snapshot);if(!status)status=inspect(s,&t);
    if(!lock(s,0))return AF_BUSY;int current=usable(s);
    if(!current&&(!scope(s,&t)||s->scope_formatted!=1||s->scope_formatter!=f))current=AF_STALE;
    if(current)status=current;if(!status){*tone=saved;*out=t;copy(image,snapshot,sizeof snapshot);}
    unlock(s);return status;
}
int af_cp_capture406_scope_end(AfCpCapture406 *s,const AfCpCapture406Token *t){
    if(!valid(s)||!t)return AF_INVALID;uint32_t tid=0;int got=s->ports.thread(s->ports.context,&tid);
    if(!lock(s,1))return AF_BUSY;int status=AF_OK;if(!scope(s,t))status=AF_STALE;
    else if(t->thread&&(got||tid!=t->thread)){poison(s);status=got?got:AF_STALE;}
    if(scope(s,t)){s->scope_active=0;s->scope_qualified=0;s->scope_formatted=0;s->scope_formatter=0;}
    if(fault(s))status=AF_IO;unlock(s);return status;
}
static int invalidate(AfCpCapture406 *s,int pool){
    if(!valid(s))return AF_INVALID;if(!lock(s,1))return AF_BUSY;int status=AF_OK;
    if(s->scope_active||(pool&&s->pool_busy))poison(s);
    for(unsigned i=0;i<AF_CP_CAPTURE406_COUNT;++i){AfCpCapture406Record *r=s->records+i;
        if(r->flags&WRITING)poison(s);if(pool)clear(r,sizeof *r);
        else if(r->a){r->flags=LIVE;if(advance(s,r))status=AF_EXHAUSTED;}}
    s->scope_qualified=0;s->scope_formatted=0;if(pool)s->pool_busy=1;
    if(fault(s)&&!status)status=AF_IO;unlock(s);return status;
}
int af_cp_capture406_reset(AfCpCapture406 *s){return invalidate(s,0);}
int af_cp_capture406_pool_begin(AfCpCapture406 *s){return invalidate(s,1);}
int af_cp_capture406_pool_end(AfCpCapture406 *s){if(!valid(s))return AF_INVALID;if(!lock(s,1))return AF_BUSY;int status=s->pool_busy?AF_OK:AF_STALE;s->pool_busy=0;if(fault(s))status=AF_IO;unlock(s);return status;}
