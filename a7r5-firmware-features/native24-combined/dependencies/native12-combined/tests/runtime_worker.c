/* 真实启动工作线程；仅时钟、Fsys、目录服务和CP提交边界用内存替身。 */
#include <string.h>
#include <stdlib.h>
#undef memset
#undef memcpy
#define memset worker_memset
#define memcpy worker_memcpy
#include "r5_stage413_thread.c"
#undef memset
#undef memcpy

struct memory_file {uint8_t data[R5_LOOK_MAX+2];size_t size,pos;int present;};
static struct memory_file card[2],active,pending;
static unsigned faults,live,sd_opens,internal_reads,transfer_calls,release_calls,log_calls;
static unsigned step_ms=100,late_second;
static uint64_t milliseconds;
static struct r5_look_set transferred;
enum {SD_CLOSE=1,SD_READ=2,WRITE=4,FILE_SYNC=8,MISMATCH=16,RENAME=32,
      DIR_SYNC=64,DIR_CLOSE=128,RELEASE=256,CANCEL=512};
static int fake_clock(int id,struct timespec64 *t){
 (void)id;t->seconds=(int64_t)(milliseconds/1000);t->nanoseconds=(int64_t)(milliseconds%1000)*1000000;return 0;
}
static int fake_sleep(const void *delay,void *rest){
 (void)delay;(void)rest;milliseconds+=step_ms;
 if(late_second && milliseconds>=late_second){r5_stage411_completed(1);r5_stage411_media(1,0,'B');late_second=0;}
 return 0;
}
static int fake_schedule(int a,int b,const void *p){(void)a;(void)b;(void)p;return 0;}
void *r5_stage411_dlsym(void *h,const char *s){
 (void)h;if(!strcmp(s,"clock_gettime"))return (void *)fake_clock;
 if(!strcmp(s,"nanosleep"))return (void *)fake_sleep;
 if(!strcmp(s,"sched_setscheduler"))return (void *)fake_schedule;return 0;
}
void r5_stage421_probe_reset(void){}
void r5_stage421_transfer_reset(void){}
void r5_stage421_log_reset(void){}
void r5_filter_service(void){}
void r5_filter_load_selection(struct r5_lut_directory *d){(void)d;}
void r5_stage411_probe_run(uint32_t a,uint32_t b){(void)a;(void)b;}
int r5_log420_emit(unsigned d,const char *s,const uint32_t *v,unsigned n){(void)d;(void)s;(void)v;(void)n;log_calls++;return 0;}
void r5_grid420_watch(unsigned d,uint32_t m){(void)d;(void)m;}
void r5_transfer420_log(unsigned d){(void)d;}
void r5_probe420_log(unsigned d){(void)d;}
void r5_stage413_transfer_run(const struct r5_look_set *s){transferred=*s;transfer_calls++;}
int r5_stage421_parameters_ready(void){return 0;}
int r5_stage421_transfer_matched(void){return 1;}
int r5_native_fsys_open(const char *s,uint32_t mode,uint64_t *h){
 unsigned n=(unsigned)(s[0]-'A');sd_opens++;
 if(n>1 || mode!=1 || strcmp(s+1,":/R5NATIVE.BIN") || !card[n].present)return -1;
 card[n].pos=0;*h=n+1;live++;return 0;
}
int r5_native_fsys_read(uint64_t h,void *p,uint64_t size,uint64_t *got){
 struct memory_file *f=&card[h-1];size_t n=f->size-f->pos;
 if(faults&CANCEL){uint32_t event=0x920143;r5_stage421_power(&event);}
 if(faults&SD_READ)return -1;if(n>size)n=(size_t)size;
 memcpy(p,f->data+f->pos,n);f->pos+=n;*got=n;return 0;
}
int r5_native_fsys_close(uint64_t h){(void)h;live--;return (faults&SD_CLOSE)?-1:0;}
static int read_open(void *c,const char *name,uintptr_t *h){
 struct memory_file *f; (void)c;
 if(!strcmp(name,R5_LOOK_STORE)){f=&active;*h=3;internal_reads++;}else{f=&pending;*h=4;}
 if(!f->present)return 1;f->pos=0;live++;return 0;
}
static int read_file(void *c,uintptr_t h,uint8_t *p,size_t size,size_t *got){
 struct memory_file *f=h==3?&active:&pending;size_t n=f->size-f->pos;(void)c;
 if(n>size)n=size;memcpy(p,f->data+f->pos,n);f->pos+=n;
 if((faults&MISMATCH)&&h==4&&n)p[0]^=1;*got=n;return 0;
}
static int close_file(void *c,uintptr_t h){(void)c;live--;return h==5&&(faults&DIR_CLOSE)?-1:0;}
static int open_dir(void *c,const char *name,uintptr_t *h){(void)c;(void)name;*h=5;live++;return 0;}
static int rename_file(void *c,const char *from,const char *to){
 (void)c;(void)from;(void)to;if(faults&RENAME)return -1;active=pending;pending.present=0;return 0;
}
static int sync_dir(void *c,uintptr_t h){(void)c;(void)h;return faults&DIR_SYNC?-1:0;}
static int create_file(void *c,const char *name,uintptr_t *h){
 (void)c;(void)name;if(pending.present)return 2;pending.present=1;pending.size=0;*h=4;live++;return 0;
}
static int write_file(void *c,uintptr_t h,const uint8_t *p,size_t n,size_t *actual){
 (void)c;(void)h;if(faults&WRITE)return -1;
 if(n>137)n=137;memcpy(pending.data+pending.size,p,n);pending.size+=n;*actual=n;return 0;
}
static int sync_file(void *c,uintptr_t h){(void)c;(void)h;return faults&FILE_SYNC?-1:0;}
static int unlink_file(void *c,const char *name){(void)c;(void)name;pending.present=0;return 0;}
int r5_native_lut_directory_api_init(struct r5_lut_directory_api *a){memset(a,0,sizeof(*a));return 0;}
int r5_lut_directory_acquire(struct r5_lut_directory *d,const struct r5_lut_directory_api *a,uint8_t *p,size_t n){
 (void)a;(void)p;(void)n;d->phase=2;d->fd=9;live++;return 0;
}
int r5_lut_directory_release(struct r5_lut_directory *d){(void)d;release_calls++;live--;return faults&RELEASE?-1:0;}
int r5_lut_directory_bind_storage(struct r5_lut_directory *d,struct r5_persist_ops *p,struct r5_stage_ops *s){
 *p=(struct r5_persist_ops){d,read_open,read_file,close_file,open_dir,rename_file,sync_dir};
 *s=(struct r5_stage_ops){d,create_file,write_file,sync_file,close_file,unlink_file};return 0;
}
void test_input(unsigned which,const uint8_t *p,size_t n,int present){
 struct memory_file *f=which<2?&card[which]:&active;
 if(n>sizeof f->data)abort();memcpy(f->data,p,n);f->size=n;f->present=present;
}
void test_faults(unsigned value){faults=value;}
void test_scan(unsigned a,unsigned b,unsigned completed,unsigned late){
 r5_stage411_initial(a,b);for(unsigned i=0;i<2;i++)if(completed&(1u<<i)){r5_stage411_completed(i);r5_stage411_media(i,0,'A'+i);}late_second=late;
}
int test_run(unsigned resume){
 if(resume){r5_session_finish();uint32_t event=0x920143;r5_stage421_power(&event);event=0x92015a;r5_stage421_power(&event);}
 else r5_session_cold();
 if(!r5_session_prepare())return -1;r5_stage411_child(&r5_stage411_state);r5_session_finish();return 0;
}
unsigned test_value(unsigned n){
 const unsigned v[]={r5_stage411_state.result,r5_stage411_state.current.valid_mask,
  transferred.valid_mask,live,sd_opens,internal_reads,transfer_calls,release_calls,
  r5_stage411_state.selected_slot,(unsigned)r5_stage411_state.publish_status,log_calls,
  active.present,(unsigned)active.size,r5_stage411_state.terminal};return n<sizeof v/sizeof v[0]?v[n]:~0u;
}
size_t test_active(uint8_t *out){memcpy(out,active.data,active.size);return active.size;}
