/* ST单基底连续软件集成。系统、原构造及packer是显式端口，不模拟ISP或图像。 */
#define _POSIX_C_SOURCE 200809L
#include "af_repository_service.h"
#include "af_reference_import.h"
#include "af_repository_recipe.h"
#include "af_runtime_ap406.h"
#include "af_imaging406.h"
#include "af_cp_recipe406.h"
#include "af_cp_native_bank406.h"
#include "af_cp_copy406.h"
#include "af_cp_capture406.h"
#include "af_cp_capture_fields406.h"
#include "af_sha256.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static AfCatalog catalog;
static AfLabels labels;
static AfApManage manager;
static void *service;
static AfApImagingBinding imaging;
static const char *artifact_directory;
static AfCpNativeBanks406 banks;
static AfCpOverride406 override;
static AfCpInput406 inputs;
static AfCpJobs406View view;
static AfCpCapture406 capture;
static AfCpCapture406Record capture_records[AF_CP_CAPTURE406_COUNT];
static AfCpCaptureColor406 *colors;
static AfCpComponents406 component;
static AfCpInput406Token request_token;
static AfPreset captured_actual[2];
static AfHandshake server;
static uint64_t input_version,now=100;
static uint32_t input_slot,input_fault,request_id=77,active_worker;
static AfRecipeLease received_lease;
static int release_received,ack_ready,reject_incoming;
static unsigned frames,accepted,private_gamma_calls,stock_gamma_calls,grid_calls;
static uint8_t packet[128],reply[128],record[576],source_image[84],shadow_image[84];
static uint8_t live[AF_CP_INPUT406_SNAPSHOT_BYTES],snapshot[AF_CP_INPUT406_COPY_BYTES];
static uint8_t prefix[AF_CP_INPUT406_COPY_BYTES],request[AF_CP_INPUT406_SNAPSHOT_BYTES];
static uint8_t main_params[0x4e],main_output[0x466],capture_output[2][0x466];
static uint8_t gd[2][8],dd[2][0x3a],ff[2][0x4e];
static uint8_t root[8],pipe_state[24],operation[0x360],calibration[0x30];
static uint8_t raw_state[0x18a],context[0x6b4],stage[13],packed[3*1620];
static const int8_t *raw_borrow;
static const uint32_t object=0x31000000u;
static const uint8_t offsets[47]={0,4,5,6,7,8,9,10,11,12,13,14,16,17,18,19,20,21,22,
 24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,48,49,50,51,52,53,54,55,56,57};
static void put(void *p,uint32_t v){uint8_t *b=p;for(unsigned i=0;i<4;++i)b[i]=(uint8_t)(v>>(8*i));}
static uint32_t word(const void *p){const uint8_t *b=p;return b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;}
static uint32_t faddr(unsigned ch){return ch?0x1f6e390u:0x1f6dfdcu;}
static uint32_t oaddr(unsigned ch){return ch?0x1f709f4u:0x1f6ff74u;}
static void original_copy(void *d,const void *s,size_t n){memcpy(d,s,n);}
static void dump(const char *,const char *,const void *,size_t);
int af_ap_factory406_snapshot(uintptr_t base,uint32_t selector,AfPreset *out){(void)base;(void)selector;(void)out;return AF_INVALID;}

/* 原OS消息/时钟端口。帧进入真实CP配方接收拥有者，不能默认返回接受成功。 */
extern AfRuntime af_ap_runtime;
int af_ap_runtime_reply(const void *,uint32_t,size_t);
static int monotonic(int id,void *p){int64_t *t=p;assert(id==1);t[0]=(int64_t)(now/1000);t[1]=(int64_t)(now%1000)*1000000;return 0;}
void *af_stock_dlsym(void *p,const char *name){assert(!p&&!strcmp(name,"clock_gettime"));return (void *)monotonic;}
int af_stock_open(const char *p,int flags,...){(void)p;(void)flags;return -1;}
long af_stock_read(int fd,void *p,size_t n){(void)fd;(void)p;(void)n;return -1;}
int af_stock_close(int fd){(void)fd;return 0;}
int *af_stock_errno(void){static int value=4;return &value;}
int af_stock_usleep(unsigned n){(void)n;return 0;}
int af_stock_receive(uint32_t q,void **out,int wait){assert(q==0x80020002u&&wait>=0);*out=0;return -1022;}
int af_stock_allocate(uint32_t q,void **p,uint32_t n,int wait){assert(q==0x90030001u&&n==128&&!wait);*p=packet;return 0;}
void af_stock_source(void *p,uint32_t source){assert(p==packet&&source==0x80020002u);}
static void *rx_allocate(void *c,size_t n){(void)c;return calloc(1,n);}
static void rx_free(void *c,void *p){(void)c;free(p);}
static int rx_send(void *c,const void *p,size_t n,uint32_t dst){(void)c;assert(n==128&&dst==0x80020002u&&!ack_ready);memcpy(reply,p,n);ack_ready=1;return 0;}
static int rx_consume(void *c,const AfRecipeOwned *owned,const AfRecipeLease *lease){
 (void)c;uint8_t marker=0;
 if(reject_incoming)return AF_EXHAUSTED;
 int status=af_cp_native_bank406_accept_locked(&banks,&override,owned->message.version,
  owned->message.slot,&owned->message.preset,&owned->asset,&marker);
 if(!status){assert(marker==1);received_lease=*lease;release_received=1;++accepted;}
 return status==AF_BUSY?AF_EXHAUSTED:status;
}
int af_stock_send(uint32_t q,void *p){
 assert(q==0x90030001u&&p==packet);
 if(packet[2]=='R'){
  ++frames;assert(af_cp_recipe406_receive(packet,0x80020002u,128)==1);
  if(release_received){assert(!af_cp_recipe406_release(&received_lease));release_received=0;}
 }else{
  AfApplyPacket value;assert(!af_apply_packet_decode(packet,128,&value));
  assert(value.operation==AF_APPLY_NATIVE&&value.version>override.version);
  uint8_t marker=0;assert(!af_cp_override406_release_locked(&override,value.version,&marker));
  assert(!af_cp_native_bank406_clear_active_locked(&banks));input_version=value.version;input_slot=0;
 }
 return 0;
}
static void connect(void){
 AfCpRecipe406Config c={&server,&input_version,&input_slot,&input_fault,rx_allocate,rx_free,rx_send,rx_consume,0};
 assert(!af_cp_recipe406_bind(&c));assert(!af_hs_server_init(&server,AF_APPLY_PROTOCOL_REQUIRED));
 uint8_t hello[128],answer[128];size_t n=0;
 af_ap_runtime.attempted=1;af_ap_runtime.last_now=now;
 assert(!af_hs_begin(&af_ap_runtime.hello,71,AF_APPLY_PROTOCOL_REQUIRED,now,1000,hello));
 assert(af_hs_server(&server,hello,128,0x80020002u,answer,128,&n)==1&&n==128);
 assert(af_ap_runtime_reply(answer,0x90030001u,128)==1&&server.state==5);
}
static void transmit(void){
 AfPreset p=catalog.slots[6].working;
 unsigned before=frames;assert(!imaging.send(imaging.context,7,&p));
 assert(frames==before+28&&ack_ready&&!input_fault);
 assert(af_ap_runtime_reply(reply,0x90030001u,128)==1);ack_ready=0;
 AfRecipeAck ack;assert(!af_ap_runtime_recipe_result(&ack)&&!ack.status&&ack.slot==7);
 assert(ack.version==override.version&&ack.version==input_version&&!memcmp(ack.payload_sha256,p.payload_sha256,32));
}

/* 真实组件/Capture核心的固定地址适配；原构造与packer输出仅是参数夹具。 */
static int read_memory(void *c,uint32_t a,void *out,size_t n){
 (void)c;
 if(a==AF_CP_COMPONENTS406_SOURCE&&n==84){memcpy(out,source_image,n);return AF_OK;}
 if(a==AF_CP_COMPONENTS406_SHADOW&&n==84){memcpy(out,shadow_image,n);return AF_OK;}
 for(unsigned i=0;i<2;++i){uint32_t obj=object+0x1000*i;
  if(a==obj+AF_CP_CAPTURE406_G&&n==8){memcpy(out,gd[i],n);return AF_OK;}
  if(a==obj+AF_CP_CAPTURE406_D&&n==sizeof dd[i]){memcpy(out,dd[i],n);return AF_OK;}
  if(a==faddr(i)&&n==sizeof ff[i]){memcpy(out,ff[i],n);return AF_OK;}
 }
 if(a>=AF_CP_COMPONENTS406_GAMMA_TABLE&&a<AF_CP_COMPONENTS406_GAMMA_TABLE+51*28&&n==4){put(out,0xdcca0c);return AF_OK;}
 if(a==0xdcca0c&&n==576){memcpy(out,record,n);return AF_OK;}
 if(a>=0x2000&&a-0x2000<=sizeof operation&&n<=sizeof operation-(a-0x2000)){memcpy(out,operation+a-0x2000,n);return AF_OK;}
 if(a==0x3000&&n==4){put(out,0x4000);return AF_OK;}
 return AF_IO;
}
static int current(void *c,const AfCpJobs406View *v){(void)c;return active_worker==v->identity&&view.lease.ticket==v->lease.ticket&&view.asset==v->asset?AF_OK:AF_STALE;}
static int get_view(void *c,uint32_t id,AfCpJobs406View *out){(void)c;if(active_worker!=id)return AF_EMPTY;*out=view;return AF_OK;}
static int worker(void *c,uint32_t id){(void)c;return active_worker==id?AF_OK:AF_EMPTY;}
static uint32_t matrix(void *c,void *out,uint32_t sector,void *r,uint32_t profile){(void)c;assert(sector<16&&r==root&&!profile);for(unsigned i=0;i<27;++i)((int16_t *)out)[i]=(int16_t)(100+i);return 101;}
static uint32_t cc1(void *c,void *out,uint32_t profile,void *r){(void)c;assert(!profile&&r==root);for(unsigned i=0;i<24;++i)((int16_t *)out)[i]=(int16_t)(100+i);return 102;}
static uint32_t stock_gamma(void *c,uint32_t mode,const void *p,void *out){(void)c;(void)mode;(void)p;++stock_gamma_calls;memcpy((uint8_t *)out+0x24c,record,516);return 103;}
static uint32_t private_gamma(void *c,uint32_t mode,const void *p,void *out,const void *r){
 (void)c;(void)p;++private_gamma_calls;memcpy((uint8_t *)out+0x24c,r,516);
 char name[80];assert(snprintf(name,sizeof name,"gamma-candidate-%u-mode%u.bin",private_gamma_calls,mode)>0);
 dump(artifact_directory,name,r,576);return 104;
}
static uint32_t source_build(void *c,const void *p){(void)c;assert(p==main_params);memset(source_image,0,84);source_image[0]=1;return 105;}
static uint32_t source_reset(void *c,const void *p){(void)c;(void)p;memset(source_image,0,84);memset(shadow_image,0,84);return 106;}
static void component_copy(void *c,void *d,const void *s,size_t n){(void)c;memcpy(d,s,n);}
static void *map(void *c,uint32_t a,size_t n){(void)c;
 if(a==0x2000&&n<=sizeof operation)return operation;if(a==0x2100&&n<=sizeof calibration)return calibration;
 if(a==0x5000&&n<=sizeof raw_state)return raw_state;if(a==0x6000&&n<=sizeof context)return context;
 if(a==0x7000&&n<=sizeof stage)return stage;
 if(a>=0x8000&&a-0x8000<=sizeof packed&&n<=sizeof packed-(a-0x8000))return packed+(a-0x8000);return 0;
}
static int address(void *c,const void *p,size_t n,uint32_t *out){(void)c;
 if(n==AF_GRID_BYTES){raw_borrow=p;*out=0x9000;return AF_OK;}
 if(n==0x466){if(p==main_output){*out=AF_CP_COMPONENTS406_GAMMA_PACKED0;return AF_OK;}
  for(unsigned i=0;i<2;++i)if(p==capture_output[i]){*out=oaddr(i);return AF_OK;}}
 return AF_INVALID;
}
static uint32_t query(void *c,void *r,void *p){(void)c;assert(r==root&&p==pipe_state);context[0x54+stage[11]]=0;return 1;}
static void pack(void *c,void *r,void *p){(void)c;assert(r==root&&p==pipe_state);++grid_calls;
 if(word(raw_state+0x184)==0x9000){assert(raw_borrow);for(unsigned i=0;i<405;++i)
  put(packed+stage[11]*1620+4*i,((uint32_t)raw_borrow[i]&127)<<22|((uint32_t)raw_borrow[i+405]&127)<<12|((uint32_t)raw_borrow[i+810]&127)<<2);
 }else memset(packed+stage[11]*1620,12,1620);
}
static int thread(void *c,uint32_t *out){(void)c;*out=22;return AF_OK;}
static int shadow(void *c,AfCpGamma406Tone *tone,uint8_t image[84]){(void)c;return af_cp_components406_gamma_snapshot(&component,tone,image);}
int af_cp_capture406_read_target(uint32_t f,uint32_t o,AfCpGamma406Tone *t,AfCpCapture406Token *v,uint8_t image[78]){return af_cp_capture406_scope_read(&capture,f,o,t,v,image);}
int af_cp_capture406_current_target(const AfCpCapture406Token *v){return af_cp_capture406_scope_current(&capture,v);}
void af_cp_capture406_reset_target(void){assert(!af_cp_capture406_reset(&capture));}
int af_cp_capture406_color_view_target(AfCpCaptureColor406View *v){return af_cp_capture_color406_view(colors,v);}
int af_cp_capture406_color_current_target(const AfCpCaptureColor406View *v){return af_cp_capture_color406_current(colors,v);}
int af_cp_capture406_color_scope_target(uint32_t r){AfCpCaptureColor406Scope s;return af_cp_capture_color406_scope_observe(colors,r,&s);}
static int request_read(void *c,AfCpInput406Token *t,uint32_t *id){(void)c;*t=request_token;*id=request_id;return AF_OK;}
static int r_matches(void *c,uint32_t r,const AfPreset *p){(void)c;if(r<object+0x20||(r-object-0x20)%0x1000)return AF_STALE;
 unsigned i=(r-object-0x20)/0x1000;return i<2&&!memcmp(&captured_actual[i],p,sizeof *p)?AF_OK:AF_STALE;}
static void initialize(const char *record_path){
 FILE *file=fopen(record_path,"rb");assert(file&&fread(record,1,576,file)==576&&!fclose(file));
 AfCpCapture406Ports cp={0,read_memory,thread,shadow};assert(!af_cp_capture406_init(&capture,&cp,capture_records,sizeof capture_records));
 colors=calloc(1,af_cp_capture_color406_bytes());assert(colors);
 AfCpCaptureColor406Ports color_ports={0,request_read,thread,r_matches};assert(!af_cp_capture_color406_init(colors,af_cp_capture_color406_bytes(),&color_ports));
 AfCpComponents406Ports p={0,get_view,current,read_memory,matrix,cc1,stock_gamma,private_gamma,map,query,pack,0x100001,address,worker,source_build,source_reset,component_copy};
 assert(!af_cp_components406_init(&component,&p));
 main_params[0x38]=6;for(unsigned i=0;i<2;++i){ff[i][0x38]=6;ff[i][0x3a]=ff[i][0x3b]=18;gd[i][0]=(uint8_t)i;}
 put(root,0x2000);put(root+4,0x2100);put(pipe_state+8,0x5000);put(pipe_state+12,0x6000);put(pipe_state+16,0x7000);
 put(context+0x6b0,0x8000);put(raw_state+0x184,0xa000);raw_state[0x18]=1;operation[0x2f]=8;calibration[12]=11;
}
static void acquire(unsigned id){
 assert(!view.lease.ticket);assert(!af_cp_override406_snapshot_copy_locked(&override,live,snapshot,AF_CP_INPUT406_SNAPSHOT_BYTES,&inputs,AF_CP_INPUT406_SNAPSHOT,original_copy));
 put(snapshot+0xdc0,53);assert(!af_cp_copy406_observe(&inputs,prefix,AF_CP_INPUT406_COPY_A,snapshot,AF_CP_INPUT406_SNAPSHOT,sizeof prefix,53,1,original_copy));
 assert(!af_cp_input406_read(&inputs,AF_CP_INPUT406_COPY_A,&view.input));
 assert(!af_cp_native_bank406_borrow_locked(&banks,&view.input,id,&view.lease));
 view.identity=id;view.ticket=(uint32_t)view.lease.ticket;view.asset=view.lease.asset;view.prefix=prefix;view.c4_address=0x3000;view.prefix_address=0x4000;active_worker=id;
 assert(!af_cp_components406_prepare(&component,id));
}
static void drop(void){assert(!af_cp_native_bank406_release(&banks,&view.lease));memset(&view,0,sizeof view);active_worker=0;}
static void gamma_check(const void *out,const AfCpRuntimeAsset406 *a){uint32_t original[129],expected[129];for(unsigned i=0;i<129;++i)original[i]=word(record+4*i);
 assert(!af_joint_gamma(original,a->native_tone,expected));assert(!memcmp((const uint8_t *)out+0x24c,expected,516));}
static void main_gamma(void){acquire(2);assert(af_cp_components406_gamma_source(&component,main_params)==105);
 assert(af_cp_components406_gamma(&component,0,main_params,AF_CP_COMPONENTS406_FORMATTER,main_output)==104);gamma_check(main_output,view.asset);
 assert(!af_cp_components406_gamma_copy(&component,shadow_image,source_image,84,AF_CP_COMPONENTS406_SHADOW,AF_CP_COMPONENTS406_SOURCE,AF_CP_COMPONENTS406_SHADOW_LR));drop();}
static void color_check(const AfCpRuntimeAsset406 *a,int is_capture){
 operation[1]=(uint8_t)is_capture;put(operation+4,is_capture?0:0x3000);stage[11]=(uint8_t)is_capture;if(!is_capture||stage[12]!=6)stage[12]=11;
 int16_t out[29],delta[27];out[27]=1234;out[28]=4321;assert(!af_cp_runtime_asset406_matrix(a,7,delta));
 assert(af_cp_components406_matrix(&component,out,7,root,0)==101);
 for(unsigned i=0;i<27;++i)assert(out[i]==100+(int)i+delta[i]);assert(out[27]==1234&&out[28]==4321);
 assert(af_cp_components406_cc1(&component,out,0,root)==102);for(unsigned i=0;i<24;++i)assert(out[i]==100+(int)i+a->recipe.cc1[i]);
 uint32_t lr=0x123457;assert(af_cp_components406_grid_enter(&component,root,pipe_state,&lr)==0x230f23&&lr==0x100001);
 for(unsigned i=0;i<405;++i)assert(word(packed+stage[11]*1620+4*i)==
  (((uint32_t)a->recipe.grid[i]&127)<<22|((uint32_t)a->recipe.grid[i+405]&127)<<12|((uint32_t)a->recipe.grid[i+810]&127)<<2));
 assert(af_cp_components406_grid_leave(&component)==0x123457&&word(raw_state+0x184)==0xa000);
}
static void main_color(void){acquire(3);color_check(view.asset,0);drop();}
static void factory_color(unsigned is_capture){
 operation[1]=(uint8_t)is_capture;put(operation+4,is_capture?0:0x3000);put(operation+8,object+0x20);
 stage[11]=(uint8_t)is_capture;stage[12]=11;active_worker=is_capture?0:3;
 int16_t out[27];assert(af_cp_components406_matrix(&component,out,7,root,0)==101);
 for(unsigned i=0;i<27;++i)assert(out[i]==100+(int)i);
 assert(af_cp_components406_cc1(&component,out,0,root)==102);for(unsigned i=0;i<24;++i)assert(out[i]==100+(int)i);
 uint32_t lr=0x123457;assert(af_cp_components406_grid_enter(&component,root,pipe_state,&lr)==0x230f23);
 assert(af_cp_components406_grid_leave(&component)==0x123457);for(unsigned i=0;i<1620;++i)assert(packed[is_capture*1620+i]==12);
 active_worker=0;
}
static void capture_bind(unsigned i){
 assert(!af_cp_capture_color406_request_invalidate(colors));
 assert(!af_cp_override406_snapshot_copy_locked(&override,live,request,sizeof request,&inputs,AF_CP_INPUT406_REQUEST,original_copy));
 assert(!af_cp_input406_read(&inputs,AF_CP_INPUT406_REQUEST,&request_token));
 const AfCpRuntimeAsset406 *a=&banks.banks[banks.active-1].asset;
 assert(!af_cp_capture_color406_request_publish(colors,&request_token,request_id,a));
 uint32_t obj=object+i*0x1000;assert(!af_cp_capture_color406_a_birth(colors,obj));
 AfCpCaptureColor406Write w;assert(!af_cp_capture_color406_r_begin(colors,obj,&w));captured_actual[i]=request_token.actual;assert(!af_cp_capture_color406_r_end(colors,&w));
 uint8_t normal[47];assert(!af_cp_capture_fields406_shadow(shadow_image,normal));for(unsigned k=0;k<47;++k)dd[i][offsets[k]]=normal[k];
 AfCpCapture406Token t;AfCpCapture406Reverse r;assert(!af_cp_capture406_birth(&capture,obj));
 assert(!af_cp_capture406_write_begin(&capture,obj,AF_CP_CAPTURE406_NORMAL,&t));
 assert(!af_cp_capture406_reverse_begin(&capture,obj+AF_CP_CAPTURE406_D,&r));
 assert(!af_cp_capture406_reverse_end(&capture,obj+AF_CP_CAPTURE406_D,&r));assert(!af_cp_capture406_write_end(&capture,&t,AF_CP_CAPTURE406_NORMAL));
}
static void capture_check(unsigned i,const AfCpRuntimeAsset406 *expected,uint64_t version){
 uint32_t obj=object+i*0x1000;AfCpCaptureColor406Scope cs;assert(!af_cp_capture_color406_scope_begin(colors,obj+0x20,&cs));
 AfCpCaptureColor406View v;assert(!af_cp_capture_color406_view(colors,&v)&&v.version==version&&!memcmp(v.asset,expected,sizeof *expected));
 put(operation+8,obj+0x20);stage[12]=11;color_check(v.asset,1);stage[12]=6;color_check(v.asset,1);assert(!af_cp_capture_color406_scope_end(colors,&cs));
 AfCpCapture406Token gs,fs;assert(!af_cp_capture406_scope_begin(&capture,obj+AF_CP_CAPTURE406_G,&gs));
 assert(!af_cp_capture406_format_begin(&capture,obj+AF_CP_CAPTURE406_D,faddr(i),&fs));
 assert(!af_cp_capture406_format_end(&capture,obj+AF_CP_CAPTURE406_D,faddr(i),&fs));
 assert(af_cp_components406_gamma(&component,1,ff[i],faddr(i),capture_output[i])==104);gamma_check(capture_output[i],expected);
 AfCpGamma406Tone tone;AfCpCapture406Token token;uint8_t formatter[78];
 assert(!af_cp_capture406_scope_read(&capture,faddr(i),oaddr(i),&tone,&token,formatter)&&tone.version==version);
 assert(!af_cp_capture406_scope_end(&capture,&gs));
}
static void reopen(int fd){int status;assert(!af_repository_service_close(service));af_catalog_init(&catalog);af_labels_init(&labels);service=af_repository_service_open(fd,&catalog,&labels,&status);assert(service&&!status);}
static int import_file(int media,const char *name,int cancel){
 AfMediaList work,list;assert(!af_media_scan(media,17,&work,&list));unsigned index=0;
 for(;index<list.count;++index)if(!strcmp(list.entries[index].name,name))break;assert(index<list.count);
 AfApMediaImporter importer;assert(!af_repository_service_media_importer(service,&importer));
 AfApMediaInfo selected={0};selected.generation=list.generation;selected.index=index;char source[4096];
 assert(!af_media_read(media,&list,index,source,sizeof source,&selected.source,0,0));
 assert(!importer.prepare(service,media,&list,&selected));AfApManageRequest q;assert(!importer.request(service,&q));q.target_slot=7;q.overwrite=catalog.slots[6].present;
 assert(!af_ap_manage_submit(&manager,&catalog,&q));int status=af_repository_service_pump(service,&manager);assert(status==AF_JOINT_MORE);
 if(cancel)assert(!af_ap_manage_cancel(&manager,manager.job.ticket));
 unsigned polls=0;do{status=af_repository_service_pump(service,&manager);assert(++polls<512);}while(status==AF_JOINT_MORE);return status;
}
static void dump(const char *directory,const char *name,const void *p,size_t n){char path[1024];assert(snprintf(path,sizeof path,"%s/%s",directory,name)>0);FILE *f=fopen(path,"wb");assert(f&&fwrite(p,1,n,f)==n&&!fclose(f));}
int main(int argc,char **argv){
 assert(argc==6);int body=open(argv[1],O_RDONLY|O_DIRECTORY),media=open(argv[2],O_RDONLY|O_DIRECTORY);assert(body>=0&&media>=0);
 int status;af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 service=af_repository_service_open(body,&catalog,&labels,&status);assert(service&&!status&&!af_reference_import_bind(service));
 if(!strcmp(argv[5],"cancel")){assert(import_file(media,"ST.cube",1)<0&&!catalog.slots[6].present&&!manager.receipt.durable);assert(!af_repository_service_close(service));return 0;}
 assert(!import_file(media,"ST.cube",0)&&manager.receipt.durable&&catalog.slots[6].saved.kind==1);
 AfPreset initial=catalog.slots[6].saved;assert(!initial.base);
 if(!strcmp(argv[5],"invalid")){
  AfSlot before=catalog.slots[6];assert(import_file(media,"ST2.cube",0)<0&&!manager.receipt.durable);
  assert(!memcmp(&before,&catalog.slots[6],sizeof before));reopen(body);
  assert(!memcmp(&initial,&catalog.slots[6].saved,sizeof initial));assert(!af_repository_service_close(service));return 0;
 }
 assert(!unlinkat(media,"ST.cube",0));reopen(body);
 assert(!memcmp(&catalog.slots[6].saved,&initial,sizeof initial));
 /* 八项暂存、显式保存与重新打开；不通过重读文件偷偷覆盖工作值。 */
 for(unsigned i=0;i<8;++i)assert(!af_edit(&catalog,7,i,i==6?4:1));
 assert(af_dirty(&catalog,7));AfPreset edited=catalog.slots[6].working;
 AfApManageRequest q={0};q.op=AF_MANAGE_SAVE;q.source_slot=q.target_slot=7;
 assert(!af_ap_manage_submit(&manager,&catalog,&q)&&!af_repository_service_pump(service,&manager));
 assert(manager.receipt.durable&&!af_dirty(&catalog,7));reopen(body);assert(!memcmp(&catalog.slots[6].working,&edited,sizeof edited));
 /* 同一完整配方经标准.a7filter导出再导入；不依赖已删除CUBE或重新拟合。 */
 int library=open(argv[4],O_RDONLY|O_DIRECTORY);assert(library>=0&&!af_repository_service_bind_library(service,library));
 q=(AfApManageRequest){0};q.op=AF_MANAGE_EXPORT;q.source_slot=q.target_slot=7;
 assert(!af_ap_manage_submit(&manager,&catalog,&q)&&!af_repository_service_pump(service,&manager));
 assert(!import_file(library,"C07_G0000000000000002.a7filter",0));
 assert(!memcmp(&catalog.slots[6].working,&edited,sizeof edited)&&!close(library));
 artifact_directory=argv[4];initialize(argv[3]);connect();
 AfImaging406RecipeSource source={AF_IMAGING406_RECIPE_SOURCE_VERSION,sizeof source,service,af_repository_service_recipe_capture};
 assert(!af_imaging406_bind_recipe_source(&source)&&!af_imaging406_binding(0x70000000u,&imaging));
 assert(imaging.capabilities(imaging.context)&AF_AP_IMAGING_FULL_RECIPE);
 if(!strcmp(argv[5],"reject")){
  reject_incoming=1;assert(!imaging.send(imaging.context,7,&catalog.slots[6].working)&&ack_ready&&frames==28);
  assert(af_ap_runtime_reply(reply,0x90030001u,128)==1);AfRecipeAck ack;
  assert(!af_ap_runtime_recipe_result(&ack)&&ack.status==AF_EXHAUSTED&&!banks.active&&!input_version&&!input_fault&&!accepted);
  assert(!af_cp_recipe406_busy()&&!af_repository_service_close(service)&&!close(body)&&!close(media));free(colors);return 0;
 }
 transmit();main_gamma();main_color();capture_bind(0);
 AfCpRuntimeAsset406 first=banks.banks[banks.active-1].asset;uint64_t first_version=override.version;
 dump(argv[4],"first-main-gamma.bin",main_output,sizeof main_output);dump(argv[4],"first-runtime.bin",&first,sizeof first);
 capture_check(0,&first,first_version);
 /* 第二份真实CUBE同槽替换；原八值可相同但资产和软件版本必须更新。 */
 assert(!af_reference_import_bind(service));assert(!import_file(media,"ST2.cube",0));
 for(unsigned i=0;i<8;++i)assert(!af_edit(&catalog,7,i,edited.params[i]));
 transmit();main_gamma();main_color();capture_bind(1);
 AfCpRuntimeAsset406 second=banks.banks[banks.active-1].asset;uint64_t second_version=override.version;
 assert(second_version>first_version&&memcmp(&first,&second,sizeof first));
 capture_check(0,&first,first_version);capture_check(1,&second,second_version);
 dump(argv[4],"second-main-gamma.bin",main_output,sizeof main_output);dump(argv[4],"first-capture-gamma.bin",capture_output[0],sizeof capture_output[0]);
 dump(argv[4],"second-capture-gamma.bin",capture_output[1],sizeof capture_output[1]);
 /* 原厂退出只撤销新输入；旧Capture在原生命周期内仍按自己的配方完成。 */
 assert(!imaging.release(imaging.context)&&!banks.active&&override.mode==AF_CP_OVERRIDE_NATIVE);
 capture_check(0,&first,first_version);capture_check(1,&second,second_version);
 for(unsigned i=0;i<2;++i){assert(!af_cp_capture_color406_a_release(colors,object+i*0x1000));assert(!af_cp_capture406_release(&capture,object+i*0x1000));}
 factory_color(0);
 /* 原厂复用A没有私有来源；原颜色scope仍负责清除已跟踪的旧packed。 */
 assert(!af_cp_capture_color406_a_birth(colors,object));AfCpCaptureColor406Scope native_scope;
 assert(af_cp_capture_color406_scope_begin(colors,object+0x20,&native_scope)==AF_EMPTY&&native_scope.serial);
 factory_color(1);assert(!af_cp_capture_color406_scope_end(colors,&native_scope));assert(!af_cp_capture_color406_a_release(colors,object));
 active_worker=2;assert(af_cp_components406_gamma(&component,0,main_params,AF_CP_COMPONENTS406_FORMATTER,main_output)==103);active_worker=0;
 assert(!memcmp(main_output+0x24c,record,516)&&!component.gamma_private_mask);
 assert(!af_cp_capture_color406_request_invalidate(colors));assert(!af_repository_service_close(service));
 assert(!close(body)&&!close(media));free(colors);
 printf("{\"status\":\"PASS_ST_CONTINUOUS_SOFTWARE_CHAIN\",\"frames\":%u,\"accepted\":%u,\"private_gamma_calls\":%u,\"stock_gamma_calls\":%u,\"grid_calls\":%u,\"camera_pixels_verified\":false}\n",frames,accepted,private_gamma_calls,stock_gamma_calls,grid_calls);return 0;
}
