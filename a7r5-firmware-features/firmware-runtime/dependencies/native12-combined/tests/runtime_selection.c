/* 生产选择状态机；消息、时间、原E4与持久化服务为可控替身。 */
#include <string.h>
#include "r5_filter_runtime423.c"
static int (*transport)(const uint8_t *,size_t);
static unsigned fault,clocks,refreshes,saves,persisted;
static uint64_t ms;
static int active=1;
static unsigned available=4095;
static unsigned char object[64],foreign[64];
enum {BAD_REFRESH=1,SAVE_FAIL=2,SLEEP_CANCEL=4};
static int fake_clock(int id,struct time423 *t){(void)id;clocks++;t->sec=(int64_t)(ms/1000);t->ns=(int64_t)(ms%1000)*1000000;return 0;}
static int fake_sleep(const void *p,void *r){(void)p;(void)r;ms+=10;if(fault&SLEEP_CANCEL)active=0;return 0;}
void *r5_stage411_dlsym(void *h,const char *s){(void)h;if(!strcmp(s,"clock_gettime"))return (void *)fake_clock;if(!strcmp(s,"nanosleep"))return (void *)fake_sleep;return 0;}
int r5_session_current(void){return active;}
uint32_t r5_session_epoch(void){return 7;}
uint32_t r5_filter_available_mask(void){return available;}
uint32_t r5_osal_msg_size(const void *p){(void)p;return 32;}
int r5_native_ap_send(void *h,const uint8_t *p,size_t n){(void)h;return transport?transport(p,n):-1;}
void r5_native_refresh_construct425(void *o,const void *p){(void)o;(void)p;}
void r5_native_refresh_execute425(void *o){(void)o;}
void r5_native_creative_sequence_request(const void *p){
 (void)p;refreshes++;
 r5_filter_refresh_construct425(object,refresh_request+4);
 r5_filter_refresh_execute425(fault&BAD_REFRESH?foreign:object);
}
int r5_stage425_reload(void){return -1;}
int r5_filter_selection_load(struct r5_lut_directory *d,unsigned *n){(void)d;*n=0;return R5_ABSENT;}
int r5_filter_selection_save(struct r5_lut_directory *d,unsigned n){(void)d;saves++;if(fault&SAVE_FAIL)return -1;persisted=n;return 0;}
int r5_native_lut_directory_api_init(struct r5_lut_directory_api *a){memset(a,0,sizeof(*a));return 0;}
int r5_lut_directory_acquire(struct r5_lut_directory *d,const struct r5_lut_directory_api *a,uint8_t *s,size_t n){(void)a;(void)s;(void)n;d->phase=2;return 0;}
int r5_lut_directory_release(struct r5_lut_directory *d){(void)d;return 0;}
void test_bind(int (*f)(const uint8_t *,size_t)){transport=f;}
void test_fault(unsigned value){fault=value;}
void test_available(unsigned value){available=value;}
void test_advance(unsigned n){ms+=n;}
unsigned test_stat(unsigned n){const unsigned v[]={refreshes,saves,persisted,clocks,attempts,active};return n<6?v[n]:~0u;}
