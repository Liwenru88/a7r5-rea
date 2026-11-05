/* 诊断留在有界RAM中；选择与启动不依赖SD日志写入。 */
#include "r5_grid_diagnostics.h"
#include "r5_runtime_session.h"
#include "r5_filter_runtime423.h"
#include "r5_stable_io425.h"
extern void *r5_stage411_dlsym(void *,const char *);
extern int r5_native_ap_send(void *,const uint8_t *,size_t);
extern uint32_t r5_osal_msg_size(const void *);
struct r5_log420_state {int32_t open,write,flush,close;uint32_t records,failures,active,inbox_state,token,late;uint8_t inbox[128];};
__attribute__((aligned(16))) struct r5_log420_state r5_log420_state;
struct r5_ram_log425 {char stage[40];uint32_t count,values[16];};
struct r5_ram_log425 r5_ram_log425[16];
int r5_log420_emit(unsigned drive,const char *stage,const uint32_t *values,unsigned n){
    struct r5_log420_state *s=&r5_log420_state;struct r5_ram_log425 *out;unsigned i;
    (void)drive;if(!stage||n>16 || (n && !values))return -1;
    out=&r5_ram_log425[s->records&15];
    for(i=0;i<39 && stage[i];i++)out->stage[i]=stage[i];out->stage[i]=0;
    for(i=0;i<n;i++)out->values[i]=values[i];out->count=n;s->records++;return 0;
}
int r5_grid420_inbound(const uint8_t *p,uint32_t source){
 struct r5_log420_state *s=&r5_log420_state;uint32_t n,expected=0;unsigned i;
 if(source!=0x90030001u)return 0;n=r5_osal_msg_size(p);
 if(!r5_diag_envelope(p,n))return 0;
 if(!r5_session_current())return 1;
 if(n!=128||p[1]!=1||p[2]!=0x81||p[3]!=128||r5_diag_get(p+12)!=0x524||r5_diag_get(p+8)!=__atomic_load_n(&s->token,__ATOMIC_ACQUIRE)||r5_diag_get(p+28)!=r5_diag_crc(p,n)||!__atomic_load_n(&s->active,__ATOMIC_ACQUIRE)){s->late++;return 1;}
 if(!__atomic_compare_exchange_n(&s->inbox_state,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)){s->late++;return 1;}
 for(i=0;i<128;i++)s->inbox[i]=p[i];__atomic_store_n(&s->inbox_state,2,__ATOMIC_RELEASE);return 1;
}
struct log_time {int64_t sec,nsec;};
typedef int (*sleep_fn)(const struct log_time *,struct log_time *);
typedef int (*clock_fn)(int,struct log_time *);
static int now(clock_fn clock,uint64_t *ms){struct log_time t;if(!clock||clock(1,&t)||t.sec<0||t.nsec<0||t.nsec>=1000000000||(uint64_t)t.sec>(UINT64_MAX-999)/1000)return -1;*ms=(uint64_t)t.sec*1000+(uint64_t)t.nsec/1000000;return 0;}
/* 健康查询只拦截已报告的资源错误，不充当画面完成回执。 */
int r5_grid420_health(void){
    struct r5_log420_state *s=&r5_log420_state;uint8_t packet[32]={0};unsigned i;uint64_t start,last,stamp;
    static uint32_t serial;const struct log_time delay={0,10000000};int result=-1;
    sleep_fn sleep=(sleep_fn)r5_stage411_dlsym(0,"nanosleep");clock_fn clock=(clock_fn)r5_stage411_dlsym(0,"clock_gettime");
    if(!sleep||!clock||now(clock,&start)||serial==0xffffffffu)return -1;last=start;
    s->token=(++serial)^r5_session_token(0x5240d1a6u);if(!s->token)s->token=serial;
    __atomic_store_n(&s->inbox_state,0,__ATOMIC_RELEASE);__atomic_store_n(&s->active,1,__ATOMIC_RELEASE);
    packet[0]=0xe9;packet[1]=1;packet[2]=1;packet[3]=32;
    r5_diag_put(packet+4,R5_DIAG_MAGIC);r5_diag_put(packet+8,s->token);r5_diag_put(packet+28,r5_diag_crc(packet,32));
    if(r5_native_ap_send(0,packet,32))goto done;
    for(i=0;i<101;i++){
        if(!r5_session_current()||now(clock,&stamp)||stamp<last||stamp<start||stamp-start>=1000)goto done;last=stamp;
        if(__atomic_load_n(&s->inbox_state,__ATOMIC_ACQUIRE)==2){
            if(r5_diag_get(s->inbox+16)==57472u && r5_diag_get(s->inbox+20)==0x35424c53u &&
               r5_diag_get(s->inbox+80)==r5_filter_bank_crc())result=r5_diag_get(s->inbox+48)==5?-5:0;
            goto done;
        }
        if(i==100 || sleep(&delay,0))goto done;
    }
done:__atomic_store_n(&s->active,0,__ATOMIC_RELEASE);return result;
}
void r5_grid420_watch(unsigned drive,uint32_t expected){
    uint32_t result=(uint32_t)r5_grid420_health();(void)expected;r5_log420_emit(drive,"PIPELINE_HEALTH",&result,1);
}
void r5_stage421_log_reset(void){
    struct r5_log420_state *s=&r5_log420_state;
    __atomic_store_n(&s->active,0,__ATOMIC_RELEASE);__atomic_store_n(&s->inbox_state,0,__ATOMIC_RELEASE);
}
