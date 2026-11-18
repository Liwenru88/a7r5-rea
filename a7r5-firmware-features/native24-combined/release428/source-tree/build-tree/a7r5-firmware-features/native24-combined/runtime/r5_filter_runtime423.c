/* One AP file/transport worker; UI and native receive callbacks never do IO. */
#include "r5_filter_runtime423.h"
#include "r5_filter423.h"
#include "r5_filter_selection423.h"
#include "r5_runtime_session.h"
#include "r5_native_lut_directory.h"
#include "r5_stable_io425.h"
#include "r5_tune425.h"
extern void *r5_stage411_dlsym(void *,const char *);
extern int r5_native_ap_send(void *,const uint8_t *,size_t);
extern uint32_t r5_osal_msg_size(const void *);
extern void r5_native_creative_sequence_request(const void *);
#define LOAD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define STORE(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
/* desired: high32 request serial, low32 numbered configuration. */
static uint64_t desired;
static uint32_t applied,mask_ready;
static uint32_t command_state,command_kind,command_sequence,service_busy,failure_alias;
static uint32_t refresh_request[8],refresh_wait,refresh_done,refresh_serial;
static uintptr_t refresh_object;
static uintptr_t native_refresh_object;
static uint32_t native_refresh_pending;
extern void r5_native_refresh_construct425(void *,const void *);
extern void r5_native_refresh_execute425(void *);
extern int r5_stage425_reload(void);
static uint64_t handled;
static uint32_t initialized,saved,saved_valid,alias,bank_crc,mask,select_sequence,dirty,synchronized_alias,synchronized_epoch;
static uint32_t inbox_state;
static uint64_t attempted_command;static uint32_t attempted_alias,attempts;
static uint64_t retry_at430;
static uint64_t restore_start;
static uint32_t restore_started,library_identity,loaded_choice,loaded_key,loaded_format,loaded_log;
static uint32_t ui_accepted,ui_epoch,factory_reset;
static uint32_t auto_recover,bank_epoch;
struct r5_filter_diag425 r5_filter_diag425;
static struct r5_filter_select_request expected;
static uint8_t inbox[32];
struct time423 {int64_t sec,ns;};
typedef int (*sleep_fn)(const void *,void *);
typedef int (*clock_fn)(int,struct time423 *);
static int current(void){return initialized && alias && bank_epoch==r5_session_epoch() && r5_session_current();}
unsigned r5_filter_selected(void){return LOAD(&applied);}
unsigned r5_filter_pending(void){unsigned s=LOAD(&command_state);if(s==3||s>=5)return 0;return LOAD(&desired)!=LOAD(&handled)||LOAD(&dirty);}
unsigned r5_filter_command_state(void){return LOAD(&command_state);}
unsigned r5_filter_command_sequence(void){return LOAD(&command_sequence);}
unsigned r5_filter_recovery_required(void){unsigned s=LOAD(&command_state);return s==5||s==7;}
unsigned r5_filter_native_inflight(void){return LOAD(&native_refresh_pending)!=0;}
unsigned r5_filter_recovering(void){return LOAD(&auto_recover)!=0;}
uint32_t r5_filter_bank_crc(void){return LOAD(&bank_crc);}
unsigned r5_filter_factory_reset_needed(void){return LOAD(&factory_reset);}
void r5_filter_factory_reset_done(void){if(!r5_filter_recovery_required()&&!r5_filter_selected())STORE(&factory_reset,0);}
void r5_filter_bank_failed(void){failure_alias=alias;STORE(&command_state,7);r5_filter_diag425.state=7;r5_filter_diag425.error=8;}
static int request425(unsigned n,unsigned kind){
    uint32_t state=LOAD(&command_state),serial;uint64_t old;
    if(kind==1 && (n>24 || !LOAD(&mask_ready) || (n && !(r5_filter_available_mask()&(1u<<(n-1))))))return -1;
    if(kind!=1 || LOAD(&auto_recover) || (r5_filter_recovery_required() && n))return -1;
    do{if(state==1 || state==4)return -1;}while(!__atomic_compare_exchange_n(&command_state,&state,4,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE));
    old=LOAD(&desired);serial=(uint32_t)(old>>32);
    if(serial==0xffffffffu){STORE(&command_state,3);return -1;}
    serial++;STORE(&auto_recover,0);STORE(&ui_epoch,r5_session_epoch());STORE(&ui_accepted,1);STORE(&command_sequence,serial);STORE(&command_kind,kind);
    STORE(&desired,((uint64_t)serial<<32)|n);STORE(&command_state,1);return 0;
}
int r5_filter_request(unsigned n){return request425(n,1);}
int r5_filter_reload_request(void){return request425(r5_filter_selected(),2);}
/* These wrappers run on their original native owner threads.  Only the exact
 * private request's allocated E4 object can complete this transaction. */
void r5_filter_refresh_construct425(void *object,const void *params){
    r5_native_refresh_construct425(object,params);
    if(params==refresh_request+4 && LOAD(&refresh_wait)){
        STORE(&refresh_object,(uintptr_t)object);
        STORE(&native_refresh_object,(uintptr_t)object);STORE(&native_refresh_pending,LOAD(&refresh_wait));
    }
}
void r5_filter_refresh_execute425(void *object){
    uint32_t serial=LOAD(&refresh_wait);
    uintptr_t exact=LOAD(&refresh_object);
    uint32_t native_serial=LOAD(&native_refresh_pending);uintptr_t native_exact=LOAD(&native_refresh_object);
    r5_native_refresh_execute425(object);
    if(native_serial && native_exact==(uintptr_t)object && native_serial==LOAD(&native_refresh_pending) && native_exact==LOAD(&native_refresh_object))
        STORE(&native_refresh_pending,0);
    if(serial && exact==(uintptr_t)object && serial==LOAD(&refresh_wait) && exact==LOAD(&refresh_object))
        STORE(&refresh_done,serial);
}
static int intent_lock425(uint32_t *state){
    *state=LOAD(&command_state);
    do{if(*state==1 || *state==4)return 0;}
    while(!__atomic_compare_exchange_n(&command_state,state,4,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE));
    return 1;
}
void r5_filter_load_selection(struct r5_lut_directory *d){
    uint32_t state;
    unsigned n=0;int rc=r5_filter_selection_load(d,&n);
    loaded_choice=n;loaded_key=r5_filter_selection_loaded_identity();loaded_format=r5_filter_selection_loaded_version();
    loaded_log=r5_filter_selection_recovery();
    if(intent_lock425(&state)){
        if(!LOAD(&ui_accepted) || LOAD(&ui_epoch)!=r5_session_epoch()){
            uint64_t old=LOAD(&desired);STORE(&desired,(old&0xffffffff00000000ull)|n);
            STORE(&ui_accepted,0);STORE(&auto_recover,0);state=loaded_log==2?5:0;
        }
        STORE(&command_state,state);
    }
    initialized=1;saved=n;saved_valid=rc==R5_IMPORTED && loaded_format==3 && !loaded_log;
}
void r5_filter_library_identity(uint32_t key,int changed){
    uint32_t state;unsigned n=loaded_choice;int locked=intent_lock425(&state);
    library_identity=key;r5_filter_selection_identity(key);
    if(locked && (!LOAD(&ui_accepted) || LOAD(&ui_epoch)!=r5_session_epoch()))STORE(&factory_reset,0);
    if(loaded_choice && ((loaded_format==3 && loaded_key!=key) || (loaded_format<3 && changed))){
        n=0;saved_valid=0;STORE(&factory_reset,1);
    }
    if(loaded_format==3 && loaded_key!=key)saved_valid=0;
    if(locked){
        if(!LOAD(&ui_accepted) || LOAD(&ui_epoch)!=r5_session_epoch()){
            uint64_t old=LOAD(&desired);STORE(&desired,(old&0xffffffff00000000ull)|n);
        }
        STORE(&command_state,state);
    }
}
void r5_filter_bank_ready(uint32_t token,uint32_t crc,uint32_t valid_mask){
    uint64_t old,next;uint32_t n;
    if(!token || (valid_mask&~0xffffffu))return;
    if(alias!=token || bank_crc!=crc || mask!=valid_mask)select_sequence=0;
    alias=token;mask=valid_mask;bank_epoch=r5_session_epoch();synchronized_alias=0;STORE(&dirty,1);STORE(&bank_crc,crc);
    /* 损坏日志也由后台解除覆盖，不把修复步骤交给用户。 */
    if(loaded_log==2){failure_alias=alias;STORE(&auto_recover,2);STORE(&command_state,5);}
    if(!initialized){initialized=1;saved_valid=0;}
    old=LOAD(&desired);
    for(;;){n=(uint32_t)old;if(!n || (n<=24 && (mask&(1u<<(n-1)))))break;
        if((uint32_t)(old>>32)==0xffffffffu)break;next=((uint64_t)((uint32_t)(old>>32)+1)<<32);
        if(__atomic_compare_exchange_n(&desired,&old,next,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)){STORE(&factory_reset,1);saved_valid=0;break;}
    }
    STORE(&mask_ready,1);
}
int r5_filter_inbound(const uint8_t *p,uint32_t source){
    uint32_t n,zero=0;unsigned i;
    if(source!=0x90030001u)return 0;n=r5_osal_msg_size(p);
    if(!r5_filter_select_is_envelope(p,n))return 0;
    /* Consume late, malformed and foreign-selection packets without forwarding
     * the private envelope into native dispatch. Worker validates exact ACK. */
    if(n!=32 || !__atomic_compare_exchange_n(&inbox_state,&zero,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return 1;
    if(r5_filter_select_ack(&expected,p,n)==-256){zero=1;(void)__atomic_compare_exchange_n(&inbox_state,&zero,0,0,__ATOMIC_RELEASE,__ATOMIC_ACQUIRE);return 1;}
    for(i=0;i<32;i++)inbox[i]=p[i];zero=1;
    (void)__atomic_compare_exchange_n(&inbox_state,&zero,2,0,__ATOMIC_RELEASE,__ATOMIC_ACQUIRE);return 1;
}
static int now(clock_fn f,uint64_t *out){
    struct time423 t;if(f(1,&t)||t.sec<0||t.ns<0||t.ns>=1000000000 || (uint64_t)t.sec>(UINT64_MAX-999)/1000)return -1;
    *out=(uint64_t)t.sec*1000+(uint64_t)t.ns/1000000;return 0;
}
static int storage(unsigned n,int begin){
    struct r5_lut_directory d={0};struct r5_lut_directory_api a;
    int rc;
    if(r5_native_lut_directory_api_init(&a) || r5_lut_directory_acquire(&d,&a,r5_stable_scratch425,R5_STABLE_SCRATCH_BYTES))return 2;
    if(begin){rc=r5_tune_begin(&d);if(!rc)rc=r5_filter_selection_begin(&d);}
    else {rc=r5_tune_save(&d);if(!rc)rc=r5_filter_selection_save(&d,n);if(!rc)r5_tune_finish(&d);}
    if(r5_lut_directory_release(&d))return 3;
    if(!rc && !begin){saved=n;saved_valid=1;loaded_log=0;}return rc;
}
static int select_send(unsigned n){
    struct r5_filter_select_request request;uint8_t packet[32],ack[32];uint64_t start,last,t;
    clock_fn clock=(clock_fn)r5_stage411_dlsym(0,"clock_gettime");sleep_fn sleep=(sleep_fn)r5_stage411_dlsym(0,"nanosleep");
    const struct time423 pause={0,10000000};uint32_t old;unsigned i,poll;int status=-1;
    if(!clock || !sleep || now(clock,&start) || select_sequence==0xffffffffu)return -1;
    old=LOAD(&inbox_state);do{if(old==1)return -1;}while(!__atomic_compare_exchange_n(&inbox_state,&old,3,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE));
    request.sequence=++select_sequence;request.selected=n;request.payload_crc=bank_crc;request.alias=alias;expected=request;
    STORE(&inbox_state,0);if(!r5_filter_select_encode(&request,packet))goto done;
    if(r5_native_ap_send(0,packet,sizeof(packet)))goto done;last=start;
    for(poll=0;poll<101;poll++) {
        if(!current() || now(clock,&t) || t<last || t<start || t-start>=1000)goto done;last=t;
        if(LOAD(&inbox_state)==2){
            for(i=0;i<32;i++)ack[i]=inbox[i];
            status=r5_filter_select_ack(&request,ack,sizeof(ack));
            if(status==1)goto done;
            /* A valid but late ACK for an earlier serial is ignored. */
            if(status!=-256)goto done;STORE(&inbox_state,0);
        }
        if(poll==100 || sleep(&pause,0))goto done;
    }
done:
    old=LOAD(&inbox_state);while(old!=1 && !__atomic_compare_exchange_n(&inbox_state,&old,3,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)){}
    return status==1?0:-1;
}
static int refresh425(void){
    clock_fn clock=(clock_fn)r5_stage411_dlsym(0,"clock_gettime");
    sleep_fn sleep=(sleep_fn)r5_stage411_dlsym(0,"nanosleep");
    const struct time423 pause={0,10000000};uint64_t start,last,t;unsigned poll;
    uint32_t serial;
    /* 超时只结束等待，不代表原生队列已取消该对象。 */
    if(LOAD(&native_refresh_pending) || refresh_serial==0xffffffffu)return -1;serial=++refresh_serial;
    if(!clock || !sleep || now(clock,&start))return -1;
    STORE(&refresh_done,0);STORE(&refresh_object,0);STORE(&refresh_wait,serial);
    refresh_request[1]=1;r5_native_creative_sequence_request(refresh_request);last=start;
    for(poll=0;poll<501;poll++){
        if(!current() || now(clock,&t) || t<last || t<start || t-start>=5000)break;
        last=t;if(LOAD(&refresh_done)==serial){STORE(&refresh_wait,0);return 0;}
        if(poll==500 || sleep(&pause,0))break;
    }
    STORE(&refresh_wait,0);return -1;
}
/* phase: 1日志、2选择、3原E4、4二次确认、5保存、6回退、7资源诊断。 */
void r5_filter_service(void){
    uint64_t want,t=0;unsigned n,previous,explicit_command,changed=0,journal=0,rollback=0,error=0;
    uint32_t busy=0;clock_fn clock=(clock_fn)r5_stage411_dlsym(0,"clock_gettime");
    if(!current() || !__atomic_compare_exchange_n(&service_busy,&busy,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return;
    {unsigned state=LOAD(&command_state);if(state==4 || ((state==3||state>=5)&&failure_alias==alias && !(state==5 && LOAD(&auto_recover))))goto done;}
    previous=r5_filter_selected();want=LOAD(&desired);n=(uint32_t)want;explicit_command=LOAD(&command_state)==1;
    if(n>24 || (n && !(mask&(1u<<(n-1))))){error=1;goto failed;}
    if(!LOAD(&dirty) && want==LOAD(&handled))goto done;
    if(explicit_command && !LOAD(&dirty) && synchronized_alias==alias && synchronized_epoch==r5_session_epoch() &&
       n==previous && saved_valid && saved==n && !r5_tune_changed(n) && current()){
        STORE(&handled,want);STORE(&command_state,2);goto done;
    }
    if(attempted_command!=want || attempted_alias!=alias){
        attempted_command=want;attempted_alias=alias;attempts=0;retry_at430=0;restore_started=0;
    }
    if(!explicit_command){
        if(!clock || now(clock,&t)){error=9;goto exhausted;}
        if(!restore_started){restore_start=t;restore_started=1;}
        if(t<restore_start || t-restore_start>=60000 || attempts>=30){error=10;goto exhausted;}
        if(t<retry_at430)goto done;
        if(LOAD(&auto_recover) && LOAD(&native_refresh_pending))goto done;
        uint32_t state=LOAD(&command_state);
        if(state==1 || state==4 || !__atomic_compare_exchange_n(&command_state,&state,4,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))goto done;
    }
    attempts++;
    r5_filter_diag425=(struct r5_filter_diag425){LOAD(&command_sequence),n,previous,r5_session_epoch(),library_identity,1,0,0,1};
    if(!explicit_command && LOAD(&auto_recover)){
        unsigned mode=LOAD(&auto_recover);
        unsigned restore=previous && !(mask&(1u<<(previous-1)))?0:previous;
        r5_filter_diag425.phase=6;
        if(!r5_tune_prepare(restore,1) && !select_send(restore) && !refresh425() && !r5_tune_verify() && current() && !r5_grid420_health() && !select_send(restore) && current() &&
           (mode!=2 || !storage(restore,0)) && current()){
            r5_tune_commit();STORE(&applied,restore);STORE(&auto_recover,0);
            if(mode==2){
                /* 显式切换失败只恢复旧结果，不再悄悄重试失败的新目标。 */
                synchronized_alias=alias;synchronized_epoch=r5_session_epoch();
                STORE(&desired,(want&0xffffffff00000000ull)|restore);STORE(&handled,LOAD(&desired));STORE(&dirty,0);
                failure_alias=alias;STORE(&command_state,3);r5_filter_diag425.state=3;r5_filter_diag425.rollback=7;
            }else {STORE(&command_state,0);r5_filter_diag425.state=0;}
        }else{
            if(clock && !now(clock,&t) && t<=UINT64_MAX-1000)retry_at430=t+1000;
            else {STORE(&auto_recover,0);r5_filter_diag425.error=9;}
            failure_alias=alias;STORE(&command_state,5);r5_filter_diag425.state=5;
        }
        goto done;
    }
    /* 日志先确认，再允许可能改变CP的显式选择。 */
    if(explicit_command){
        int rc=storage(previous,1);
        if(rc && !(n==0 && loaded_log==2)){error=11;goto failed;}
        journal=1;
    }
    if(LOAD(&native_refresh_pending) || r5_tune_prepare(n,0)){error=14;goto failed;}
    r5_filter_diag425.phase=2;changed=1;
    /* 报文可能已在CP生效，丢ACK也不能跳过回退。 */
    if(!current() || select_send(n) || !current()){error=2;goto failed;}
    r5_filter_diag425.phase=3;
    if(refresh425() || r5_tune_verify() || !current()){error=3;goto failed;}
    r5_filter_diag425.phase=7;
    if(r5_grid420_health() || !current()){error=7;goto failed;}
    r5_filter_diag425.phase=4;
    if(select_send(n) || !current()){error=4;goto failed;}
    r5_filter_diag425.phase=5;
    if(journal || !saved_valid || saved!=n){
        int rc=storage(n,0);if(rc){error=rc==3?13:12;goto failed;}
    }
    r5_tune_commit();synchronized_alias=alias;synchronized_epoch=r5_session_epoch();STORE(&applied,n);STORE(&dirty,0);STORE(&handled,want);
    r5_filter_diag425.state=2;STORE(&command_state,explicit_command?2:0);goto done;
failed:
    synchronized_alias=0;r5_filter_diag425.error=error;r5_filter_diag425.phase=6;
    if(!changed)rollback=7;
    else if(current() && (previous==0 || (mask&(1u<<(previous-1))))){
        if(!select_send(previous)){rollback|=1;
            if(!LOAD(&native_refresh_pending) && !r5_tune_prepare(previous,1) && !refresh425() && !r5_tune_verify() && current() && !r5_grid420_health() && !select_send(previous) && current())rollback|=2;
        }
    }
    if(explicit_command && ((rollback&3)==3) && (changed||journal)){
        if(!storage(previous,0))rollback|=4;
    }else if(!explicit_command && (rollback&3)==3)rollback|=4;
    r5_filter_diag425.rollback=rollback;
    if((rollback&7)!=7){
        if(clock && !now(clock,&t) && t<=UINT64_MAX-1000){
            retry_at430=t+1000;
            if(explicit_command){attempts=0;restore_start=t;restore_started=1;}
            STORE(&auto_recover,explicit_command?2:1);
        }
        failure_alias=alias;STORE(&command_state,5);r5_filter_diag425.state=5;goto done;
    }
    if(explicit_command){
        STORE(&desired,(want&0xffffffff00000000ull)|previous);STORE(&handled,LOAD(&desired));
        failure_alias=alias;STORE(&command_state,3);r5_filter_diag425.state=3;
    }else{
        if(clock && !now(clock,&t) && t<=UINT64_MAX-1000){retry_at430=t+1000;STORE(&command_state,0);goto done;}
        error=9;goto exhausted;
    }
    goto done;
exhausted:
    {unsigned terminal=LOAD(&auto_recover)?5:6;STORE(&auto_recover,0);
     failure_alias=alias;STORE(&command_state,terminal);r5_filter_diag425.state=terminal;r5_filter_diag425.error=error;}
done:
    STORE(&service_busy,0);
}
