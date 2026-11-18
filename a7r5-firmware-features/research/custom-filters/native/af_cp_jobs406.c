#include "af_cp_jobs406.h"
#include "af_cp_components406.h"
#define MAGIC 0x314a3741u
_Static_assert(__atomic_always_lock_free(4,0),"jobs require lock-free 32-bit atomics");
static const uint32_t identities[3]={2,3,6},tasks[3]={0x55,0x4b,0x5b};
static const uint32_t queues[3]={0x172d308,0x16bac50,0x1774d44};
static const uint32_t c4s[3]={0x15787e4,0x1214e98,0x157c278};
static const uint32_t completions[3]={0x15788a8,0x1214f5c,0x157c33c};
static const uint32_t id_addresses[3]={0x15787e0,0x1214f70,0x157c350};
static const uint32_t native_workers[3]={0x8847c1,0x71965b,0x907251};
static const uint32_t c4_returns[3]={0x88476b,0x719605,0x9071fb};
static const uint32_t submit_returns[3]={0x884799,0x719633,0x907229};
static const uint32_t reject_returns[3]={0x8847b9,0x719653,0x907249};
static uint32_t load(const uint32_t*p){return __atomic_load_n(p,__ATOMIC_SEQ_CST);}
static void store(uint32_t*p,uint32_t v){__atomic_store_n(p,v,__ATOMIC_SEQ_CST);}
static int change(uint32_t*p,uint32_t before,uint32_t after){return __atomic_compare_exchange_n(p,&before,after,0,__ATOMIC_SEQ_CST,__ATOMIC_SEQ_CST);}
static int range(const void*p,size_t n){return p&&n&&(uintptr_t)p<=UINTPTR_MAX-n;}
static int apart(const void*a,size_t n,const void*b,size_t m){return range(a,n)&&range(b,m)&&((uintptr_t)a+n<=(uintptr_t)b||(uintptr_t)b+m<=(uintptr_t)a);}
static void bytes(void*d,const void*s,size_t n){for(size_t i=0;i<n;++i)((uint8_t*)d)[i]=((const uint8_t*)s)[i];}
static uint32_t word(const void*v){const uint8_t*p=v;return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put(void*v,uint32_t x){uint8_t*p=v;for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(x>>(8*i));}
static int index_of(uint32_t id){for(unsigned i=0;i<3;++i)if(id==identities[i])return (int)i;return -1;}
static int valid(const AfCpJobs406*s){return range(s,sizeof(*s))&&!((uintptr_t)s%_Alignof(AfCpJobs406))&&s->magic==MAGIC;}
static int same_preset(const AfPreset*a,const AfPreset*b){if(a->base!=b->base||a->kind!=b->kind)return 0;for(unsigned i=0;i<8;++i)if(a->params[i]!=b->params[i])return 0;return 1;}
static int same_token(const AfCpInput406Token*a,const AfCpInput406Token*b){return a->version==b->version&&a->source==b->source&&a->epoch==b->epoch&&a->origin_snapshot_epoch==b->origin_snapshot_epoch&&a->slot==b->slot&&a->mode==b->mode&&a->flags==b->flags&&a->native_vd==b->native_vd&&same_preset(&a->actual,&b->actual);}
static int token_valid(const AfCpInput406Token*t,uint32_t source){return t->source==source&&t->version&&t->epoch&&!(t->epoch&1u)&&t->origin_snapshot_epoch&&!(t->origin_snapshot_epoch&1u)&&t->slot&&t->slot<=AF_USERS&&t->mode==AF_CP_OVERRIDE_USER&&t->flags==3&&!t->actual.kind&&af_validate(&t->actual)==AF_OK;}
static int prefix_matches(const uint8_t*p,const AfCpInput406Token*t){
    static const uint8_t base[12]={0,3,2,1,16,15,17,18,5,13,19,20};
    static const unsigned at[8]={0xa44,0xa46,0xa45,0xa47,0xa48,0xd2e,0xd2f,0xd30};
    unsigned b=t->actual.base<10?t->actual.base:t->actual.base-7u;
    if(b>=12||word(p+0xa40)!=base[b]||word(p+0xdc0)!=t->native_vd)return 0;
    for(unsigned i=0;i<8;++i)if(p[at[i]]!=(uint8_t)t->actual.params[i])return 0;
    return 1;
}
static int descriptor(const uint8_t*p,uint32_t handler,uint32_t fn){return word(p)==handler&&!word(p+4)&&word(p+8)==fn&&!word(p+12)&&!word(p+16);}
static int pin(AfCpJobs406*s,AfCpJob406*j){store(&s->fault,1);if(j)store(&j->state,AF_CP_JOB406_PINNED);return AF_IO;}
static int finish(AfCpJobs406*s,AfCpJob406*j,int executed){
    if(s->config.release(s->config.context,s->config.banks,&j->view.lease)!=AF_OK)return pin(s,j);
    if(executed)store(&j->executed,load(&j->executed)+1u);
    store(&j->state,AF_CP_JOB406_FREE);return AF_OK;
}
size_t af_cp_jobs406_bytes(void){return sizeof(AfCpJobs406);}
int af_cp_jobs406_init(AfCpJobs406*s,const AfCpJobs406Config*c){
    if(!range(s,sizeof(*s))||(uintptr_t)s%_Alignof(AfCpJobs406)||!apart(s,sizeof(*s),c,sizeof(*c))||
       !apart(s,sizeof(*s),c->banks,sizeof(*c->banks))||!c->map||!c->read_input||!c->borrow_locked||!c->release||!c->allowed||!c->copy||!c->task||!c->invoke||!c->complete||
       !(c->completion_address&1u)||!(c->after_native_lr&1u))return AF_INVALID;
    if(s->magic)return AF_EXISTS;
    for(unsigned i=0;i<3;++i){if(!(c->worker_address[i]&1u))return AF_INVALID;
        for(unsigned k=0;k<2;++k){uint32_t p=c->prefix_address[i][k];if(!p||(p&3u)||p>UINT32_MAX-AF_CP_INPUT406_COPY_BYTES)return AF_INVALID;
            for(unsigned a=0;a<=i;++a)for(unsigned b=0;b<2;++b)if((a<i||b<k)&&!(p+AF_CP_INPUT406_COPY_BYTES<=c->prefix_address[a][b]||c->prefix_address[a][b]+AF_CP_INPUT406_COPY_BYTES<=p))return AF_INVALID;}}
    bytes(&s->config,c,sizeof(*c));s->magic=MAGIC;return AF_OK;
}
int af_cp_jobs406_c4_copy_locked(AfCpJobs406*s,void*dst,uint32_t dst_address,const void*src,uint32_t src_address,size_t n,uint32_t lr){
    if(!valid(s))return AF_INVALID;
    int i=-1,k=-1,result=AF_INVALID,held=0;AfCpInput406Token token,after;AfCpNativeLease406 lease;
    AfCpJob406*j=0;uint8_t*completion=0;const uint8_t*original=0;
    if(n==AF_CP_JOBS406_C4_BYTES&&apart(s,sizeof(*s),dst,n)&&apart(s,sizeof(*s),src,n)&&apart(src,n,dst,n)&&!load(&s->fault)&&s->config.allowed(s->config.context)){
        for(unsigned a=0;a<3;++a)if(dst_address==c4s[a]&&lr==c4_returns[a])i=(int)a;
        if(i>=0){uint32_t source=word(src);k=(src_address==0x192b070u&&source==AF_CP_INPUT406_COPY_A)?0:(src_address==0x165d820u&&source==AF_CP_INPUT406_COPY_B)?1:-1;
            if(k>=0&&word((const uint8_t*)src+4)==source+0xdc0&&word((const uint8_t*)src+8)==source+AF_CP_JOBS406_ALIAS_OFFSET){
                completion=s->config.map(s->config.context,completions[i],20);const void*id=s->config.map(s->config.context,id_addresses[i],4);
                original=s->config.map(s->config.context,source,AF_CP_INPUT406_COPY_BYTES);
                if(completion&&id&&original&&apart(s,sizeof(*s),completion,20)&&apart(s,sizeof(*s),original,AF_CP_INPUT406_COPY_BYTES)&&descriptor(completion,0x60daa5,0x4bf3e1)&&word(id)==identities[i]&&
                   s->config.read_input(s->config.context,source,&token)==AF_OK&&token_valid(&token,source)){
                    j=&s->jobs[i];if(change(&j->state,AF_CP_JOB406_FREE,AF_CP_JOB406_BUILDING)){
                        if(j->next_ticket==UINT32_MAX){pin(s,j);result=AF_EXHAUSTED;}
                        else{result=s->config.borrow_locked(s->config.context,s->config.banks,&token,identities[i],&lease);held=result==AF_OK;
                            /* 未知release结果也必须保留明确的银行票据，不把唯一借用留在栈上。 */
                            if(held)bytes(&j->view.lease,&lease,sizeof(lease));
                            if(!held)store(&j->state,AF_CP_JOB406_FREE);}
                    }else{j=0;result=AF_BUSY;}
                }
            }
        }
    }
    /* 原三个copy不因来源、票据或配方验证失败而消失，也不重复用于回滚。 */
    s->config.copy(s->config.context,dst,src,n);
    if(!held)return result;
    uint8_t*prefix=s->prefixes[i][k];bytes(prefix,original,AF_CP_INPUT406_COPY_BYTES);
    if(!lease.asset||!lease.preset||lease.worker!=identities[i]||lease.version!=token.version||
       !prefix_matches(prefix,&token)||s->config.read_input(s->config.context,token.source,&after)!=AF_OK||!same_token(&token,&after)||load(&s->fault)||!s->config.allowed(s->config.context)||
       word(dst)!=token.source||word((uint8_t*)dst+4)!=token.source+0xdc0||word((uint8_t*)dst+8)!=token.source+AF_CP_JOBS406_ALIAS_OFFSET||
       !descriptor(completion,0x60daa5,0x4bf3e1)){
        if(s->config.release(s->config.context,s->config.banks,&lease)!=AF_OK)return pin(s,j);
        store(&j->state,AF_CP_JOB406_FREE);return AF_STALE;
    }
    AfCpJobs406View*v=&j->view;v->ticket=++j->next_ticket;v->identity=identities[i];v->source_index=(uint32_t)k;v->task=tasks[i];v->queue=queues[i];
    v->c4_address=dst_address;v->original_source=token.source;v->prefix_address=s->config.prefix_address[i][k];v->prefix=prefix;v->asset=lease.asset;
    bytes(&v->input,&token,sizeof(token));bytes(&v->lease,&lease,sizeof(lease));j->ticket=v->ticket;j->message_address=0;store(&j->completion_seen,0);
    put(dst,v->prefix_address);put((uint8_t*)dst+4,v->prefix_address+0xdc0);put((uint8_t*)dst+8,v->prefix_address+AF_CP_JOBS406_ALIAS_OFFSET);
    put(completion+8,s->config.completion_address);store(&j->state,AF_CP_JOB406_CAPTURED);return AF_OK;
}
static int queue_bind(AfCpJobs406*s,const void*source,size_t n,uint32_t lr,const AfCpJobs406QueueFrame*f){
    if(load(&s->fault)||!s->config.allowed(s->config.context)||!apart(s,sizeof(*s),f,sizeof(*f))||f->bytes<AF_CP_JOBS406_STACK_BYTES||
       !apart(s,sizeof(*s),f->stack,f->bytes)||f->address>UINT32_MAX-AF_CP_JOBS406_STACK_BYTES||
       (lr!=0x5c36e4u&&lr!=0x5c3864u&&lr!=0x5c388cu))return AF_INVALID;
    uint8_t*stack=f->stack;uint8_t*m=stack+0x68;
    if(word(stack+0x54)!=0x4e8abf||word(stack+0x50)!=f->address+0xac)return AF_INVALID;
    int i=-1;for(unsigned a=0;a<3;++a)if(word(stack+0xa4)==submit_returns[a]&&word(stack+0x48)==queues[a])i=(int)a;
    if(i<0||!descriptor(stack+0xac,0x719e37,native_workers[i])||word(m)!=0x719e37||word(m+4)||word(m+12)||word(m+16)||word(m+20)||word(m+24)||
       (uintptr_t)source<(uintptr_t)m||(uintptr_t)source>(uintptr_t)m+28)return AF_INVALID;
    size_t offset=(uintptr_t)source-(uintptr_t)m;
    if(!n||n>28-offset||offset%4||n%4)return AF_INVALID;
    int first=offset==0&&(lr==0x5c36e4u?n==28:lr==0x5c3864u?n<28:n==28);
    int tail=lr==0x5c388cu&&offset>0&&offset+n==28;
    if(!first&&!tail)return AF_INVALID;
    AfCpJob406*j=&s->jobs[i];uint32_t state=load(&j->state);
    if(tail)return state==AF_CP_JOB406_QUEUED&&j->message_address==f->address+0x68&&word(m+8)==s->config.worker_address[i]?AF_OK:AF_STALE;
    if(word(m+8)!=native_workers[i]||state!=AF_CP_JOB406_CAPTURED||!change(&j->state,AF_CP_JOB406_CAPTURED,AF_CP_JOB406_QUEUING))return AF_STALE;
    j->message_address=f->address+0x68;put(m+8,s->config.worker_address[i]);store(&j->state,AF_CP_JOB406_QUEUED);return AF_OK;
}
int af_cp_jobs406_queue_copy(AfCpJobs406*s,void*d,const void*source,size_t n,uint32_t lr,const AfCpJobs406QueueFrame*f){
    if(!valid(s))return AF_INVALID;
    int result=queue_bind(s,source,n,lr,f);s->config.copy(s->config.context,d,source,n);return result;
}
static int task_matches(AfCpJobs406*s,unsigned i){uint32_t t,q;return s->config.task(s->config.context,&t,&q)==AF_OK&&t==tasks[i]&&q==queues[i];}
int af_cp_jobs406_run(AfCpJobs406*s,uint32_t id){
    if(!valid(s))return AF_INVALID;int i=index_of(id);if(i<0)return AF_INVALID;AfCpJob406*j=&s->jobs[i];
    if(!task_matches(s,(unsigned)i)||!change(&j->state,AF_CP_JOB406_QUEUED,AF_CP_JOB406_RUNNING)){
        /* 已改work指针的原队列项不能被资格拒绝吞掉。先固定未知借用，
         * 再委派已知原worker一次；其completion仍只清原pending，不递归run。 */
        (void)pin(s,j);s->config.invoke(s->config.context,id,native_workers[i]);return AF_IO;
    }
    /* 已排队原work仍执行；sticky故障只关闭私有组件，不吞掉原厂工作。 */
    int eligible=!load(&s->fault)&&s->config.allowed(s->config.context);
    uint32_t ticket=j->ticket;s->config.invoke(s->config.context,id,native_workers[i]);
    if(load(&j->state)!=AF_CP_JOB406_RUNNING||j->ticket!=ticket||!load(&j->completion_seen)||!task_matches(s,(unsigned)i))return pin(s,j);
    eligible=eligible&&!load(&s->fault)&&s->config.allowed(s->config.context);
    int result=finish(s,j,eligible);return result==AF_OK&&!eligible?AF_IO:result;
}
int af_cp_jobs406_complete(AfCpJobs406*s,uint32_t id,uint32_t lr){
    if(!valid(s))return AF_INVALID;int i=index_of(id);int result=AF_IO;AfCpJob406*j=i<0?0:&s->jobs[i];
    uint32_t state=j?load(&j->state):AF_CP_JOB406_PINNED;
    if(j&&lr==reject_returns[i]&&state==AF_CP_JOB406_CAPTURED&&change(&j->state,state,AF_CP_JOB406_BUILDING))result=finish(s,j,0);
    else if(j&&lr==s->config.after_native_lr&&state==AF_CP_JOB406_RUNNING&&!load(&j->completion_seen)&&task_matches(s,(unsigned)i)){store(&j->completion_seen,1);result=AF_OK;}
    else if(j&&lr==0x4e8c0bu&&state==AF_CP_JOB406_CAPTURED&&task_matches(s,(unsigned)i)&&change(&j->state,state,AF_CP_JOB406_BUILDING))result=finish(s,j,0);
    else result=pin(s,j);
    /* 每个原完成入口只委派一次；未知LR固定借用，不能假释放或假执行成功。 */
    s->config.complete(s->config.context,id);return result;
}
int af_cp_jobs406_current_view(AfCpJobs406*s,uint32_t id,AfCpJobs406View*out){
    if(!valid(s)||!apart(s,sizeof(*s),out,sizeof(*out))||(uintptr_t)out%_Alignof(AfCpJobs406View))return AF_INVALID;
    int i=index_of(id);if(i<0)return AF_INVALID;if(load(&s->fault)||!s->config.allowed(s->config.context))return AF_IO;AfCpJob406*j=&s->jobs[i];
    if(!task_matches(s,(unsigned)i)||load(&j->state)!=AF_CP_JOB406_RUNNING)return AF_EMPTY;
    AfCpJobs406View next;bytes(&next,&j->view,sizeof(next));
    if(load(&s->fault)||!s->config.allowed(s->config.context)||load(&j->state)!=AF_CP_JOB406_RUNNING||next.ticket!=j->ticket||!task_matches(s,(unsigned)i))return AF_STALE;
    bytes(out,&next,sizeof(next));return AF_OK;
}
int af_cp_jobs406_current(AfCpJobs406*s,const AfCpJobs406View*expected){
    if(!valid(s)||!apart(s,sizeof(*s),expected,sizeof(*expected)))return AF_INVALID;
    AfCpJobs406View now;int r=af_cp_jobs406_current_view(s,expected->identity,&now);if(r!=AF_OK)return r;
    return now.ticket==expected->ticket&&now.source_index==expected->source_index&&now.task==expected->task&&now.queue==expected->queue&&now.c4_address==expected->c4_address&&
        now.original_source==expected->original_source&&now.prefix==expected->prefix&&now.prefix_address==expected->prefix_address&&now.asset==expected->asset&&
        now.lease.worker==expected->lease.worker&&now.lease.bank==expected->lease.bank&&now.lease.ticket==expected->lease.ticket&&now.lease.generation==expected->lease.generation&&
        now.lease.version==expected->lease.version&&now.lease.asset==expected->lease.asset&&now.lease.preset==expected->lease.preset&&same_token(&now.input,&expected->input)?AF_OK:AF_STALE;
}

#if defined(__arm__) && defined(AF_CP_NATIVE_JOBS406)
static AfCpJobs406 target;
static void *target_map(void*c,uint32_t a,size_t n){(void)c;
    if((a==AF_CP_INPUT406_COPY_A||a==AF_CP_INPUT406_COPY_B)&&n==AF_CP_INPUT406_COPY_BYTES)return(void*)(uintptr_t)a;
    for(unsigned i=0;i<3;++i)if((a==completions[i]&&n==20)||(a==id_addresses[i]&&n==4))return(void*)(uintptr_t)a;
    return 0;
}
static int target_input(void*c,uint32_t source,AfCpInput406Token*t){(void)c;return af_cp_override406_read_input(source,t);}
static int target_borrow(void*c,AfCpNativeBanks406*b,const AfCpInput406Token*t,uint32_t w,AfCpNativeLease406*l){(void)c;return af_cp_native_bank406_borrow_locked(b,t,w,l);}
static int target_release(void*c,AfCpNativeBanks406*b,const AfCpNativeLease406*l){(void)c;return af_cp_native_bank406_release(b,l);}
static int target_allowed(void*c){(void)c;return !af_cp_override406_faulted();}
static void target_copy(void*c,void*d,const void*s,size_t n){(void)c;((void(*)(void*,const void*,size_t))(uintptr_t)0x5f51bcu)(d,s,n);}
static int target_task(void*c,uint32_t*t,uint32_t*q){(void)c;return((int(*)(uint32_t*))(uintptr_t)0x5c88dcu)(t)||((int(*)(uint32_t*))(uintptr_t)0x5dcfdcu)(q)?AF_IO:AF_OK;}
static void target_invoke(void*c,uint32_t id,uint32_t fn){
    (void)c;
    /* prepare自己复核同次RUNNING视图；失败仍完整执行原work，沿原分组回退。 */
    if(id==2||id==3)(void)af_cp_components406_prepare_target(id);
    af_cp_jobs406_invoke_native(fn);
}
static void target_complete(void*c,uint32_t id){(void)c;((void(*)(uint32_t))(uintptr_t)0x4bf3e1u)(id);}
int af_cp_jobs406_bind_target(AfCpNativeBanks406*b){
    AfCpJobs406Config c;
    /* 明确逐字节清零，避免固件目标引入未提供的memclr运行库。 */
    for(size_t i=0;i<sizeof(c);++i)((volatile uint8_t*)&c)[i]=0;
    c.banks=b;c.map=target_map;c.read_input=target_input;c.borrow_locked=target_borrow;c.release=target_release;c.allowed=target_allowed;c.copy=target_copy;c.task=target_task;c.invoke=target_invoke;c.complete=target_complete;
    c.completion_address=(uint32_t)(uintptr_t)&af_cp_jobs406_completion;c.after_native_lr=(uint32_t)(uintptr_t)&af_cp_jobs406_after_native;
    c.worker_address[0]=(uint32_t)(uintptr_t)&af_cp_jobs406_worker2;c.worker_address[1]=(uint32_t)(uintptr_t)&af_cp_jobs406_worker3;c.worker_address[2]=(uint32_t)(uintptr_t)&af_cp_jobs406_worker6;
    for(unsigned i=0;i<3;++i)for(unsigned k=0;k<2;++k)c.prefix_address[i][k]=(uint32_t)(uintptr_t)target.prefixes[i][k];
    return af_cp_jobs406_init(&target,&c);
}
AfCpJobs406*af_cp_jobs406_target_state(void){return valid(&target)?&target:0;}
int af_cp_jobs406_current_target(uint32_t id,AfCpJobs406View*v){return af_cp_jobs406_current_view(&target,id,v);}
int af_cp_jobs406_current_matches_target(const AfCpJobs406View*v){return af_cp_jobs406_current(&target,v);}
void af_cp_jobs406_c4_target(void*d,const void*s,size_t n,uint32_t lr){if(valid(&target))(void)af_cp_jobs406_c4_copy_locked(&target,d,(uint32_t)(uintptr_t)d,s,(uint32_t)(uintptr_t)s,n,lr);else target_copy(0,d,s,n);}
void af_cp_jobs406_queue_target(void*d,const void*s,size_t n,uint32_t lr,const void*sp){AfCpJobs406QueueFrame f={(void*)sp,AF_CP_JOBS406_STACK_BYTES,(uint32_t)(uintptr_t)sp};if(valid(&target))(void)af_cp_jobs406_queue_copy(&target,d,s,n,lr,&f);else target_copy(0,d,s,n);}
void af_cp_jobs406_worker_target(uint32_t id){
    if(valid(&target)){(void)af_cp_jobs406_run(&target,id);return;}
    /* 正常boot只在bind后发布wrapper；若遗留已知wrapper先到，仍委派
     * 固定原worker，不读取未绑定config、不释放无法确认的银行票据。 */
    int i=index_of(id);if(i>=0){store(&target.fault,1);target_invoke(0,id,native_workers[i]);}
}
void af_cp_jobs406_completion_target(uint32_t id,uint32_t lr){if(valid(&target))(void)af_cp_jobs406_complete(&target,id,lr);else target_complete(0,id);}
#else
int af_cp_jobs406_bind_target(AfCpNativeBanks406*b){(void)b;return AF_IO;}
AfCpJobs406*af_cp_jobs406_target_state(void){return 0;}
int af_cp_jobs406_current_target(uint32_t id,AfCpJobs406View*v){(void)id;(void)v;return AF_IO;}
int af_cp_jobs406_current_matches_target(const AfCpJobs406View*v){(void)v;return AF_IO;}
void af_cp_jobs406_c4_target(void*d,const void*s,size_t n,uint32_t lr){(void)d;(void)s;(void)n;(void)lr;}
void af_cp_jobs406_queue_target(void*d,const void*s,size_t n,uint32_t lr,const void*sp){(void)d;(void)s;(void)n;(void)lr;(void)sp;}
void af_cp_jobs406_worker_target(uint32_t id){(void)id;}
void af_cp_jobs406_completion_target(uint32_t id,uint32_t lr){(void)id;(void)lr;}
#endif
