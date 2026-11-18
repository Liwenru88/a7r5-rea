/* 实际工作线程与调度源码回放；原厂存储、CP和音频接口使用受控替身。 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "r5sound_runtime.c"
static uint32_t mode=1,epoch=1,silent=1,playing,stop_requests,starts,bank,step_now,install_wait,fail_write;
static unsigned writes,reads;static uint8_t config[96];static size_t config_size;
static unsigned live,peak,allocations,releases;
static void *allocate(size_t n){void *p=malloc(n);if(p){allocations++;live++;if(live>peak)peak=live;}return p;}
static void release(void *p){if(p){assert(live);live--;releases++;}free(p);}
static int read_file(void *c,const char *name,uint8_t *p,size_t cap,size_t *n){
 (void)c;reads++;if(strcmp(name,"R5SOUND.PRO")||!config_size)return 1;
 assert(cap>=config_size);memcpy(p,config,config_size);*n=config_size;return 0;
}
static int write_file(void *c,const char *name,const uint8_t *p,size_t n){
 (void)c;assert(!strcmp(name,"R5SOUND.PRO")&&n==96);writes++;if(fail_write)return -1;
 memcpy(config,p,n);config_size=n;return 0;
}
static int audio(void *c,const char *name,const uint8_t *sha,size_t bytes,unsigned step,uint8_t *p,size_t cap,size_t *n){
 (void)c;(void)name;(void)bytes;reads++;assert(cap>=R5SOUND_STAGING_BYTES);memset(p,0,cap);p[0]=sha[0];p[1]=(uint8_t)step;*n=32;return 0;
}
unsigned r5sound_native_shutter_type(void){return mode;}
uint32_t r5ss_native_silent_get(void){return silent;}
int r5_session_current(void){return 1;}
int r5_session_cold_start(void){return 0;}
uint32_t r5_session_epoch(void){return epoch;}
void *r5_stage411_dlsym(void *h,const char *n){(void)h;if(!strcmp(n,"malloc"))return (void *)malloc;if(!strcmp(n,"free"))return (void *)free;return 0;}
int r5_native_lut_directory_api_init(struct r5_lut_directory_api *a){memset(a,0,sizeof(*a));return 0;}
int r5_lut_directory_acquire(struct r5_lut_directory *d,const struct r5_lut_directory_api *a,uint8_t *p,size_t n){(void)a;(void)p;assert(n==65537);d->phase=2;return 0;}
int r5_lut_directory_release(struct r5_lut_directory *d){assert(d->phase==2);d->phase=0;return 0;}
void r5sound_storage_bind(r5sound_storage *s,struct r5_lut_directory *d){(void)d;*s=(r5sound_storage){0,read_file,write_file,0,0,audio};}
void r5sound_log(unsigned d,const char *s,const char *n,int rc,const uint32_t *v,unsigned count){(void)d;(void)s;(void)n;(void)rc;(void)v;(void)count;}
void r5sound_menu_catalog_changed(void){}
int r5sound_worker_yield(void){return 1;}
int r5_native_fsys_open(const char *p,uint32_t f,uint64_t *h){(void)p;(void)f;(void)h;return -1;}
int r5_native_fsys_read(uint64_t h,void *p,uint64_t n,uint64_t *k){(void)h;(void)p;(void)n;(void)k;return -1;}
int r5_native_fsys_close(uint64_t h){(void)h;return 0;}
int r5_native_fsys_find_first(const char *p,void *o){(void)p;(void)o;return -1;}
int r5_native_fsys_find_next(void *p){(void)p;return -1;}
uint32_t r5_osal_msg_size(const void *p){(void)p;return 28;}
void r5ss_bridge_power(void){}
int r5ss_bridge_bind_epoch(uint32_t e){assert(e==epoch);return 0;}
int r5ss_bridge_active(void){return playing;}
void r5ss_bridge_diagnostics(uint32_t *p){memset(p,0,21*sizeof(*p));}
int r5ss_native_first_owner17(uint32_t *p){*p=1;return 0;}
int r5ss_backend_first_authorize(r5ss_native_backend *b,uint32_t t){(void)b;assert(t==1);return 0;}
int r5ss_backend_resume(r5ss_native_backend *b){if(playing)return 1;b->registered=b->mapped=b->ap_owned=0;return 0;}
int r5ss_backend_poll(void *b){(void)b;return playing;}
int r5ss_backend_stop(void *b){(void)b;stop_requests++;return 0;}
int r5ss_backend_authorize(void *b){(void)b;return silent==1;}
int r5ss_backend_stage(r5ss_native_backend *b,uint32_t g,const uint8_t *p,uint32_t n,uint32_t pad,uint32_t v){
 assert(!playing&&n==32&&pad==n+R5SOUND_F0_GUARD);b->encoded=p;b->offered_generation=g;b->volume_step=v;return 0;
}
int r5ss_backend_install(void *p,uint32_t g){r5ss_native_backend *b=p;if(install_wait){install_wait--;return 1;}
 assert(!playing);if(b->encoded){bank=b->encoded[0];step_now=b->encoded[1];}b->registered=1;b->installed_generation=g;b->installed_bytes=32;return 0;
}
int r5ss_backend_start(void *p,uint32_t g,uint32_t s){r5ss_native_backend *b=p;(void)s;assert(g==b->installed_generation&&!playing);playing=1;starts++;return 0;}
int r5ss_backend_unload(r5ss_native_backend *b){assert(!playing);b->registered=0;return 0;}
r5ss_ops r5ss_backend_ops(r5ss_native_backend *b){return (r5ss_ops){b,r5ss_backend_poll,r5ss_backend_stop,r5ss_backend_authorize,r5ss_backend_install,r5ss_backend_start};}
static void drain(void){for(unsigned i=0;i<15;i++)r5sound_service();assert(!run.request&&!run.changing&&!profile_request);}
static void expose(unsigned n){uint32_t p[7]={0x10010004,n,0xf000,0,0,0,0};unsigned old_writes=writes,old_reads=reads;r5sound_inbound((void *)p,0x90030001);assert(writes==old_writes&&reads==old_reads);}
int main(void){
 run.alloc=allocate;run.free=release;run.published=1;run.epoch=epoch;run.step=5;active_profile=1;
 profiles.group[0].step=profiles.group[1].step=5;
 run.catalog.count=2;for(unsigned i=0;i<2;i++){r5sound_entry *e=&run.catalog.entries[i];strcpy(e->name,i?"TWO.R5S":"ONE.R5S");memset(e->sha,i+1,32);e->bytes=R5SOUND_PACKAGE_HEADER_BYTES+320;}
 unsigned io=writes+reads;assert(!r5sound_profile_request(0,1));assert(io==writes+reads);drain();
 assert(!run.selected&&!run.backend.registered&&r5sound_profile_selected(0)==1);
 assert(!strcmp(r5sound_profile_status(0),"已保存：切换至对应快门后生效"));
 assert(!r5sound_profile_volume_request(0,3));drain();
 assert(!r5sound_profile_request(1,2));drain();assert(run.selected==2&&bank==2&&step_now==5);
 assert(!r5sound_profile_volume_request(1,8));drain();assert(bank==2&&step_now==8&&r5sound_profile_volume(0)==3);
 /* 曝光回调占用调度锁时，已保存的请求不得丢失或重复写盘。 */
 run.scheduler.gate=1;assert(!r5sound_profile_request(1,1));r5sound_service();unsigned saved_writes=writes;
 assert(profile_request&&profile_saved);r5sound_service();assert(writes==saved_writes&&profile_request);
 run.scheduler.gate=0;drain();assert(run.selected==1&&bank==1);
 assert(!r5sound_profile_request(1,2));drain();assert(bank==2&&step_now==8);
 expose(1);r5sound_service();assert(starts==1&&playing);expose(1);r5sound_service();assert(starts==1);
 /* 播放中切到机械：必须先退休，不允许把电子组的曝光播到机械组。 */
 mode=0;r5sound_service();assert(stop_requests==1&&bank==2&&run.request);expose(2);r5sound_service();assert(starts==1&&stop_requests==1);
 playing=0;drain();assert(run.selected==1&&bank==1&&step_now==3);r5sound_service();assert(starts==1);
 expose(3);r5sound_service();assert(starts==2&&playing);playing=0;
 fail_write=1;assert(!r5sound_profile_request(0,2));drain();assert(run.selected==1&&bank==1&&r5sound_profile_selected(0)==1);
 assert(!strcmp(r5sound_profile_status(0),"保存失败：详见R5SOUND.LOG"));fail_write=0;
 /* 安装等待期间切换模式：完成旧事务时仍保持静音，再装入新组。 */
 install_wait=2;mode=1;r5sound_service();assert(run.request);mode=0;drain();assert(active_profile==0&&bank==1&&step_now==3&&starts==2);
 mode=1;drain();assert(bank==2&&step_now==8);
 silent=0;expose(4);r5sound_service();assert(starts==2);silent=1;
 mode=2;drain();assert(!run.selected&&!run.backend.registered&&r5sound_profile_selected(1)==2);
 mode=0;drain();assert(bank==1&&step_now==3);
 epoch++;drain();assert(bank==1&&step_now==3&&r5sound_profile_selected(1)==2);
 mode=1;drain();assert(bank==2&&step_now==8);
 assert(!r5sound_profile_request(1,0));drain();assert(!run.selected&&r5sound_profile_selected(0)==1);
 assert(!run.audio);
 /* 连续装卸和模式切换不能积累音频缓冲；停止等待期间不提前释放。 */
 unsigned limit=peak;
 for(unsigned i=0;i<1000;i++){
  mode=i&1;drain();
  assert(!r5sound_profile_request(mode,1+(i&1)));drain();
  expose(100+i);r5sound_service();assert(playing);
  assert(!r5sound_profile_request(mode,0));r5sound_service();
  unsigned before=live,stops=stop_requests;
  for(unsigned wait=0;wait<100;wait++)r5sound_service();
  assert(live==before&&stop_requests==stops);
  playing=0;drain();assert(!run.audio&&live==0);
 }
 assert(peak==limit&&allocations==releases);
 puts("实际服务回放：双组设置与异常恢复、1000次装卸资源归零、停止等待不提前释放均通过");return 0;
}
