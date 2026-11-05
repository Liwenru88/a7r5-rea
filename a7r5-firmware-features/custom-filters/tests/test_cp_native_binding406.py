"""真实启动/握手/接收/原锁/银行的宿主集成；固定地址与系统端口为显式边界。

不运行ARM或ISP。Jobs/Components这里只验证绑定与失败传播，其真实行为由各模块
测试覆盖。合同字节是自包含读取夹具，不替代同次ELF的18/51挂点合同核对。
"""
from pathlib import Path
import subprocess

import pytest


NATIVE = Path(__file__).resolve().parents[1] / "native"
PORTS = r'''
#include "af_cp_native406.h"
#include "af_cp_jobs406.h"
#include "af_cp_components406.h"
#include <stddef.h>
extern unsigned char test_factor[288],test_snapshot[118],test_marker;
extern unsigned char test_request[AF_CP_INPUT406_SNAPSHOT_BYTES],test_live[AF_CP_INPUT406_SNAPSHOT_BYTES];
extern uint32_t test_request_id;
const volatile unsigned char *test_contract(uint32_t);
int test_sender(const void *,size_t,uint32_t);
int test_lock(uint32_t);
int test_unlock(uint32_t);
int test_try(uint32_t);
void test_stock_copy(void *,const void *,size_t);
'''
DRIVER = r'''
#include "af_sha256.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
extern AfHandshake af_cp_handshake;
extern uint64_t af_cp_hs_input_version;
extern uint32_t af_cp_hs_input_slot,af_cp_hs_input_fault;
int af_cp_hs_start_once(void);
int af_cp_hs_configure(uint32_t);
int af_cp_hs_receive(const void *,uint32_t,size_t);
void test_snapshot_init(void);
const AfCpOverride406 *test_active(void);
unsigned test_core_stage(void);
unsigned test_core_pending_copy(void);
unsigned test_core_arena_used(void);
unsigned char test_factor[288],test_snapshot[118],test_marker;
unsigned char test_request[AF_CP_INPUT406_SNAPSHOT_BYTES],test_live[AF_CP_INPUT406_SNAPSHOT_BYTES];
uint32_t test_request_id=91;
static unsigned char actual_hooks[AF_CP_NATIVE406_HOOKS][4],reply[128];
/* 自包含物理读取夹具；真实432/1280B合同在独立ELF/plan检查中核验。 */
#ifdef AF_CP_CAPTURE406
static unsigned char test_capture[582];
const volatile unsigned char af_cp_native406_capture_expected[584]={
 [0]=0x71,[25]=0xa1,[26]=0x72,[31]=0xa2,[32]=0x73,[37]=0xa3,[38]=0x74,[45]=0xa4,
 [46]=0x75,[65]=0xa5,[66]=0x76,[85]=0xa6,[86]=0x77,[485]=0xa7,[486]=0x78,[581]=0xa8
#ifdef TEST_BAD_CAPTURE_PAD
 ,[TEST_BAD_CAPTURE_PAD]=1
#endif
};
static unsigned capture_binds;
static int capture_result,capture_ready=1;
static unsigned request_invalidations,request_publishes,request_cached;
static int request_result;
static AfCpInput406Token request_token;
static AfCpRuntimeAsset406 request_asset;
#endif
const volatile unsigned char af_cp_native406_factor_expected[288]={0x41,0x46,0x34,0x30,0x36};
const volatile AfCpNative406Hook af_cp_native406_hooks[AF_CP_NATIVE406_HOOKS]={
 {0x898568,{0x57,0xf3,0x5e,0xfa}},{0x4baab6,{0x34,0xf3,0xb7,0xf7}},
 {0x4bba78,{0x33,0xf3,0xd6,0xf7}},{0x4bc002,{0x33,0xf3,0x11,0xf5}},
 {0x884766,{0x6b,0xf3,0x5f,0xf9}},{0x719600,{0xd6,0xf0,0x12,0xf2}},
 {0x9071f6,{0xe8,0xf2,0x17,0xfc}},{0x313c70,{0xdb,0xf0,0xda,0xde}},
 {0x5c36e0,{0xd0,0xb0,0x18,0xfa}},{0x5c3860,{0x70,0xb0,0x18,0xfa}},
 {0x5c3888,{0x66,0xb0,0x18,0xfa}},{0x71e41e,{0xd1,0xf0,0xe4,0xb1}},
 {0x71e670,{0xd1,0xf0,0xa9,0xb0}},{0x41363c,{0xdc,0xf3,0xdc,0xb0}},
 {0x230f0c,{0xbe,0xf1,0x31,0x9c}},
 {0xaa6978,{0x01,0x02,0x03,0x04}},{0x845700,{0x05,0x06,0x07,0x08}},
 {0xaaca82,{0x09,0x0a,0x0b,0x0c}}
#ifdef AF_CP_CAPTURE406
 ,{0x45bc80,{0x93,0xf3,0x0b,0xf6}},{0x45be6c,{0x93,0xf3,0x15,0xf5}},
 {0x48d700,{0x62,0xf3,0xd1,0xf0}},{0x48d8b4,{0x61,0xf3,0xf7,0xf7}},
 {0x46e65a,{0x81,0xf3,0x21,0xf1}},{0x335e56,{0xb9,0xf0,0x40,0xdd}},
 {0x872682,{0x7d,0xf3,0x84,0xf9}},{0x45c09a,{0x93,0xf3,0x27,0xf3}},
 {0xadf96c,{0x0f,0xf1,0x96,0xfe}},{0xadfd2c,{0x0f,0xf1,0xb6,0xfc}},
 {0xae038c,{0x0f,0xf1,0x86,0xf9}},{0xaa7f08,{0x47,0xf1,0x0c,0xfb}},
 {0xadd846,{0x01,0x02,0x03,0x14}},{0xadf128,{0x01,0x02,0x03,0x16}},
 {0x24d32a,{0x01,0x01,0x03,0x10}},{0x24daba,{0x01,0x01,0x03,0x11}},
 {0x73e8dc,{0x01,0x01,0x03,0x12}},{0x73e94e,{0x01,0x01,0x03,0x13}},
 {0x73e9ba,{0x01,0x01,0x03,0x14}},{0x73ea62,{0x01,0x01,0x03,0x15}},
 {0x73ea68,{0x01,0x01,0x03,0x16}},{0x73ea8c,{0x01,0x01,0x03,0x17}},
 {0x73f10e,{0x01,0x01,0x03,0x18}},{0x73f174,{0x01,0x01,0x03,0x19}},
 {0x73f1e4,{0x01,0x01,0x03,0x1a}},{0x73f278,{0x01,0x01,0x03,0x1b}},
 {0x73f2e6,{0x01,0x01,0x03,0x1c}},{0x73f362,{0x01,0x01,0x03,0x1d}},
 {0x73f394,{0x01,0x01,0x03,0x1e}},{0x73f3f4,{0x01,0x01,0x03,0x1f}},
 {0x73f494,{0x01,0x01,0x03,0x20}},{0x73f4c6,{0x01,0x01,0x03,0x21}},
 {0x71d6ec,{0x01,0x01,0x03,0x22}}
#endif
};
static AfCpJobs406 jobs;
static unsigned jobs_binds,component_binds,locks,unlocks,tries,acks,hellos,copies,after_copies;
static unsigned target_slot=7;
static int jobs_bound,component_result,try_busy,lock_held,fail_unlock;
const volatile unsigned char *test_contract(uint32_t address){
#ifdef AF_CP_CAPTURE406
 const uint32_t starts[8]={0xbef524u,0xbef582u,0xbef65au,0xbef678u,0xbef69cu,0xbef6ecu,0xbef838u,0xbef5c0u};
 const unsigned offsets[8]={0,26,32,38,46,66,86,486};
 for(unsigned i=0;i<8;++i)if(address==starts[i])return test_capture+offsets[i];
#endif
 for(unsigned i=0;i<AF_CP_NATIVE406_HOOKS;++i)
  if(af_cp_native406_hooks[i].address==address)return actual_hooks[i];
 assert(!"未知物理读取地址");return 0;
}
int test_lock(uint32_t id){assert(id==0x24&&!lock_held);++locks;lock_held=1;return 0;}
int test_try(uint32_t id){assert(id==0x24&&!lock_held);++tries;if(try_busy)return -1;lock_held=1;return 0;}
int test_unlock(uint32_t id){
 assert(id==0x24&&lock_held);++unlocks;
 if(fail_unlock){fail_unlock=0;return -1;}lock_held=0;return 0;
}
int test_sender(const void *data,size_t bytes,uint32_t destination){
 assert(bytes==128&&destination==0x80020002u);memcpy(reply,data,128);
 if(!memcmp(data,"A7R1",4)){
  AfRecipeAck value;assert(!af_recipe_ack_decode(data,bytes,&value));++acks;
 }else{AfApplyPacket value;assert(!af_apply_packet_decode(data,bytes,&value));++hellos;}
 return 0;
}
void test_stock_copy(void *d,const void *s,size_t n){++copies;memcpy(d,s,n);}
int af_cp_jobs406_bind_target(AfCpNativeBanks406 *banks){
 assert(banks==af_cp_native406_banks());++jobs_binds;jobs_bound=1;return AF_OK;
}
AfCpJobs406 *af_cp_jobs406_target_state(void){return jobs_bound?&jobs:0;}
int af_cp_components406_bind_target(void){++component_binds;return component_result;}
#ifdef AF_CP_CAPTURE406
/* 此集成只替换已单独覆盖的目标端口，不运行固定地址或目标ABI。 */
int af_cp_capture406_bind_target(void){
 assert(jobs_binds==1&&component_binds==1&&!test_core_arena_used());
 ++capture_binds;return capture_result;
}
int af_cp_capture406_target_ready(void){return capture_binds&&capture_ready;}
void af_cp_capture406_request_invalidate_target(void){++request_invalidations;request_cached=0;}
int af_cp_capture406_request_publish_target(const AfCpInput406Token *token,uint32_t id,const AfCpRuntimeAsset406 *asset){
 assert(lock_held&&id==test_request_id&&token->source==AF_CP_INPUT406_REQUEST);
 AfCpInput406Token actual;assert(!af_cp_override406_read_input(AF_CP_INPUT406_REQUEST,&actual));
 assert(actual.version==token->version&&actual.source==token->source&&actual.epoch==token->epoch&&
  actual.origin_snapshot_epoch==token->origin_snapshot_epoch&&actual.slot==token->slot&&
  actual.mode==token->mode&&actual.flags==token->flags&&actual.native_vd==token->native_vd&&
  !memcmp(&actual.actual,&token->actual,sizeof actual.actual));
 AfCpNativeBanks406 *banks=af_cp_native406_banks();assert(banks->active&&banks->active<=2);
 AfCpNativeBank406 *bank=&banks->banks[banks->active-1];
 assert(bank->valid&&bank->version==token->version&&bank->slot==token->slot);
 assert(!memcmp(asset,&bank->asset,sizeof *asset));++request_publishes;
 if(request_result)return request_result;
 request_token=*token;request_asset=*asset;request_cached=1;return AF_OK;
}
#endif
void af_cp_jobs406_c4_target(void *d,const void *s,size_t n,uint32_t lr){
 (void)d;(void)s;(void)n;(void)lr;assert(!"本测试未授予Jobs消费者执行资格");
}
void af_cp_jobs406_queue_target(void *d,const void *s,size_t n,uint32_t lr,const void *sp){
 (void)d;(void)s;(void)n;(void)lr;(void)sp;assert(!"本测试不运行原内核queue");
}
int af_cp_components406_shot_after_target(void *d,const void *s,size_t n,uint32_t lr){
 assert(lr==0x313c75u&&copies==1&&!memcmp(d,s,n));++after_copies;return AF_INVALID;
}
int af_cp406_locked_prepare(const AfPreset *p){(void)p;assert(!"本测试不走旧参数锁端口");return AF_INVALID;}
static void setup(void){
#ifdef AF_CP_CAPTURE406
 _Static_assert(AF_CP_NATIVE406_HOOKS==51,"需完整51挂点合同");
 _Static_assert(sizeof(af_cp_native406_factor_expected)+sizeof(af_cp_native406_capture_expected)+sizeof(af_cp_native406_hooks)==1280,"合同长度");
 for(unsigned i=0;i<582;++i)test_capture[i]=af_cp_native406_capture_expected[i];
#else
 _Static_assert(AF_CP_NATIVE406_HOOKS==18,"需完整18挂点合同");
 _Static_assert(sizeof(af_cp_native406_factor_expected)+sizeof(af_cp_native406_hooks)==432,"合同长度");
#endif
 for(unsigned i=0;i<288;++i)test_factor[i]=af_cp_native406_factor_expected[i];
 for(unsigned i=0;i<AF_CP_NATIVE406_HOOKS;++i)
  for(unsigned j=0;j<4;++j)actual_hooks[i][j]=af_cp_native406_hooks[i].code[j];
 test_snapshot_init();
}
static void start_with(uint32_t required){
 if(required==AF_APPLY_PROTOCOL_REQUIRED)assert(!af_cp_hs_start_once());
 else{
  /* 旧FULL端显式采用无USER20的合同；仍经真实configure与HELLO。 */
  assert(!af_cp_native406_bind_once());assert(!af_cp_hs_configure(required));
 }
 assert(test_core_stage()==2&&test_core_arena_used()==1&&af_cp_native406_ready());
 assert(jobs_binds==1&&component_binds==1&&af_cp_handshake.state==4);
#ifdef AF_CP_CAPTURE406
 assert(capture_binds==1);
#endif
 AfHandshake client={0};unsigned char hello[128];
 assert(!af_hs_begin(&client,71,required,0,1000,hello));
 assert(af_cp_hs_receive(hello,0x80020002u,sizeof hello)==1&&hellos==1);
 assert(af_hs_client(&client,reply,sizeof reply,0x90030001u,0)==1);
 assert(client.state==2&&af_cp_handshake.state==5&&!af_cp_hs_input_fault);
 assert(af_cp_hs_start_once()==AF_BUSY&&jobs_binds==1&&component_binds==1);
}
static void start(void){start_with(AF_APPLY_PROTOCOL_REQUIRED);}
static AfJointAsset make_asset(unsigned version){
 AfJointAsset asset={.base=17,.native_mode=1};asset.model_sha256[0]=7;
 for(unsigned i=0;i<129;++i)asset.native_seed[i]=asset.recipe.gamma[i]=i*1024;
 asset.recipe.matrix[0]=(int16_t)version;asset.recipe.cc1[2]=(int16_t)-(int)version;
 asset.recipe.grid[11]=(int8_t)version;return asset;
}
static unsigned sector_mode;
static AfJointAsset current_asset(unsigned version){
 AfJointAsset a=make_asset(version);
 if(sector_mode){a.matrix_mode=1;memset(a.recipe.matrix,0,sizeof a.recipe.matrix);
  for(unsigned i=0;i<288;++i)a.sector_matrix[i]=(int16_t)((int)(i%31)-15+(int)version);}
 return a;
}
static AfPreset make_preset(const unsigned char *image,size_t bytes){
 AfPreset p={.base=17,.kind=1,.params={-1,2,-3,4,-5,6,3,8}};
 assert(!af_sha256(image,bytes,p.payload_sha256));p.lut_sha256[0]=91;return p;
}
static void transmit(unsigned version){
 AfJointAsset asset=current_asset(version);unsigned char image[AF_JOINT_ASSET_MAX_BYTES],frame[128];size_t bytes=0;
 assert(!af_joint_asset_encode(&asset,image,sizeof image,&bytes)&&bytes==af_joint_asset_size(&asset));
 assert(!memcmp(image,sector_mode?"AJR3":"AJR2",4));
 AfPreset p=make_preset(image,bytes);AfRecipeTx tx;
 assert(!af_recipe_tx_init(&tx,71,version,target_slot,&p,image,bytes));
 for(unsigned i=0;i<af_recipe_tx_frames(&tx);++i){
  assert(!af_recipe_tx_frame(&tx,i,frame,sizeof frame));
  assert(af_cp_hs_receive(frame,0x80020002u,sizeof frame)==1);
 }
 /* 发送/解码的临时对象全部销毁，银行仍必须独立保持完整配方。 */
 memset(&asset,0,sizeof asset);memset(&p,0,sizeof p);memset(image,0,sizeof image);memset(&tx,0,sizeof tx);
}
static void acknowledgment(unsigned version,int status){
 AfRecipeAck value;assert(!af_recipe_ack_decode(reply,sizeof reply,&value));
 assert(value.session==71&&value.version==version&&value.slot==target_slot&&value.status==status);
 assert(af_cp_recipe406_last_result()==status);
}
static void check_active(unsigned version){
 AfCpNativeBanks406 *banks=af_cp_native406_banks();assert(banks->active>=1&&banks->active<=2);
 const AfCpNativeBank406 *b=&banks->banks[banks->active-1];
 AfJointAsset expected=current_asset(version);
 unsigned char image[AF_JOINT_ASSET_MAX_BYTES];size_t bytes=0;
 assert(!af_joint_asset_encode(&expected,image,sizeof image,&bytes));AfPreset p=make_preset(image,bytes);
 assert(b->valid&&b->version==version&&b->slot==target_slot);
 assert(b->asset.base==expected.base&&b->asset.native_mode==expected.native_mode);
 assert(!memcmp(b->asset.model_sha256,expected.model_sha256,32));
 assert(!memcmp(b->asset.native_tone,expected.native_tone,sizeof expected.native_tone));
 assert(!memcmp(b->asset.recipe.matrix,expected.recipe.matrix,sizeof expected.recipe.matrix));
 assert(!memcmp(b->asset.recipe.cc1,expected.recipe.cc1,sizeof expected.recipe.cc1));
 assert(!memcmp(b->asset.recipe.grid,expected.recipe.grid,sizeof expected.recipe.grid));
 assert(b->asset.matrix_mode==expected.matrix_mode);
 assert(!memcmp(b->asset.sector_matrix,expected.sector_matrix,576));
 assert(!memcmp(&b->preset,&p,sizeof p));
 const AfCpOverride406 *projection=test_active();
 assert(projection->mode==AF_CP_OVERRIDE_USER&&projection->version==version&&projection->slot==target_slot);
 assert(!projection->preset.kind&&projection->preset.base==p.base);
 assert(!memcmp(projection->preset.params,p.params,8));
 for(unsigned i=0;i<32;++i)assert(!projection->preset.payload_sha256[i]&&!projection->preset.lut_sha256[i]);
 assert(test_marker==1);
}
static AfCpNativeLease406 borrow(unsigned identity){
 /* 使用真实snapshot/copy版本伴随构造token，不按九值猜出version。 */
 const AfCpOverride406 *projection=test_active();
 AfCpInput406 observer={0};AfCpInput406Write write;AfCpInput406Token token;
 unsigned char raw[AF_CP_INPUT406_COPY_BYTES]={0},out[sizeof raw],marker=0;
 assert(!af_cp406_write_state(&projection->preset,raw,AF_CP_INPUT406_SNAPSHOT_BYTES,&marker));
 assert(!af_cp_input406_snapshot_begin(&observer,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&write));
 assert(!af_cp_input406_snapshot_end(&observer,&write,projection->version,target_slot,AF_CP_OVERRIDE_USER,
  &projection->preset,raw,AF_CP_INPUT406_SNAPSHOT_BYTES));
 assert(!af_cp_input406_copy_begin(&observer,AF_CP_INPUT406_COPY_A,AF_CP_INPUT406_SNAPSHOT,sizeof raw,42,&write));
 memcpy(out,raw,sizeof out);out[AF_CP_INPUT406_VD_OFFSET]=42;
 assert(!af_cp_input406_copy_end(&observer,&write,out,sizeof out));
 assert(!af_cp_input406_read(&observer,AF_CP_INPUT406_COPY_A,&token));
 AfCpNativeLease406 lease;assert(!test_lock(0x24));
 assert(!af_cp_native_bank406_borrow_locked(af_cp_native406_banks(),&token,identity,&lease));
 assert(!test_unlock(0x24));return lease;
}
static void completed(unsigned version){
 transmit(version);acknowledgment(version,AF_OK);check_active(version);
 assert(af_cp_hs_input_version==version&&af_cp_hs_input_slot==target_slot&&!af_cp_hs_input_fault);
 assert(!af_cp_recipe406_busy()&&!test_core_pending_copy()&&af_cp_native406_ready());
 AfRecipeLease lease;const AfRecipeOwned *pending=0;
 assert(af_cp_recipe406_pending(&lease,&pending)==AF_EMPTY);
}
static void bank_full(void){
 start();completed(1);AfCpNativeLease406 first=borrow(2);
 completed(2);AfCpNativeLease406 second=borrow(3);
 AfCpNativeBanks406 before=*af_cp_native406_banks();unsigned prior_acks=acks;
 transmit(3);acknowledgment(3,AF_EXHAUSTED);
 assert(acks==prior_acks+1&&af_cp_hs_input_version==2&&!af_cp_hs_input_fault);
 assert(!memcmp(&before,af_cp_native406_banks(),sizeof before));check_active(2);
 assert(!af_cp_recipe406_busy()&&!test_core_pending_copy());
 assert(!af_cp_native_bank406_release(af_cp_native406_banks(),&first));
 /* 新明确版本才重试，不回放已消费版本，也不自动重调未知提交。 */
 completed(4);assert(first.asset->recipe.grid[11]==4&&second.asset->recipe.grid[11]==2);
 assert(!af_cp_native_bank406_release(af_cp_native406_banks(),&second));
 assert(af_cp_native_bank406_release(af_cp_native406_banks(),&first)==AF_STALE);
}
static void rejects_hello(void){
 AfHandshake client={0};unsigned char hello[128];
 assert(!af_hs_begin(&client,71,AF_APPLY_PROTOCOL_REQUIRED,0,1000,hello));
 assert(!af_cp_hs_receive(hello,0x80020002u,sizeof hello));
 assert(!hellos&&!acks&&!af_cp_handshake.state);
}
int main(int argc,char **argv){
 assert(argc==2);setup();
#ifdef AF_CP_CAPTURE406
#ifdef TEST_BAD_CAPTURE_PAD
 assert(!strcmp(argv[1],"capture-padding"));
 assert(af_cp_hs_start_once()==AF_IO&&test_core_stage()==3);
 assert(!jobs_binds&&!component_binds&&!capture_binds&&!test_core_arena_used());
 rejects_hello();return 0;
#endif
 if(!strncmp(argv[1],"capture-region",14)){
  unsigned region=(unsigned)(argv[1][14]-'0');assert(region<8);
  const unsigned ends[8]={25,31,37,45,65,85,485,581};test_capture[ends[region]]^=1;
  assert(af_cp_hs_start_once()==AF_IO&&test_core_stage()==3);
  assert(!jobs_binds&&!component_binds&&!capture_binds&&!test_core_arena_used());
  rejects_hello();setup();assert(af_cp_hs_start_once()==AF_IO&&!capture_binds);return 0;
 }
 if(!strcmp(argv[1],"capture-bind")){
  capture_result=AF_IO;assert(af_cp_hs_start_once()==AF_IO&&test_core_stage()==3);
  assert(jobs_binds==1&&component_binds==1&&capture_binds==1&&!test_core_arena_used());
  rejects_hello();capture_result=AF_OK;assert(af_cp_hs_start_once()==AF_IO&&capture_binds==1);return 0;
 }
 if(!strcmp(argv[1],"capture-lost")){
  start();completed(1);unsigned prior_acks=acks,prior_locks=locks;
  capture_ready=0;assert(!af_cp_native406_ready()&&test_core_stage()==2);
  af_cp_native406_receive_finished();
  assert(test_core_stage()==3&&af_cp_hs_input_fault&&af_cp_override406_faulted());
  assert(!af_cp_native406_ready()&&!test_core_pending_copy()&&locks==prior_locks);
  check_active(1);capture_ready=1;assert(af_cp_native406_bind_once()==AF_IO);
  transmit(2);assert(acks==prior_acks&&locks==prior_locks&&af_cp_hs_input_version==1);
  return 0;
 }
#endif
 if(!strcmp(argv[1],"factor")||!strcmp(argv[1],"hook")){
  if(!strcmp(argv[1],"factor"))test_factor[287]^=1;
  else actual_hooks[AF_CP_NATIVE406_HOOKS-1][3]^=1;
  assert(af_cp_hs_start_once()==AF_IO&&test_core_stage()==3);
  assert(!jobs_binds&&!component_binds&&!test_core_arena_used()&&!af_cp_handshake.state);
  rejects_hello();setup();assert(af_cp_hs_start_once()==AF_IO&&!jobs_binds);return 0;
 }
 if(!strcmp(argv[1],"busy")){
  try_busy=1;assert(af_cp_hs_start_once()==AF_BUSY&&test_core_stage()==0);
  assert(!jobs_binds&&!component_binds&&!test_core_arena_used()&&!af_cp_override406_faulted());
  try_busy=0;start();completed(1);return 0;
 }
 if(!strcmp(argv[1],"partial")){
  component_result=AF_IO;assert(af_cp_hs_start_once()==AF_IO&&test_core_stage()==3);
  assert(jobs_binds==1&&component_binds==1&&!test_core_arena_used()&&!af_cp_handshake.state);
  component_result=AF_OK;assert(af_cp_hs_start_once()==AF_IO&&jobs_binds==1&&component_binds==1);return 0;
 }
 if(!strcmp(argv[1],"shot")){
  unsigned char from[19],to[sizeof from];memset(from,0x91,sizeof from);memset(to,0,sizeof to);
  af_cp_native406_shot_copy_target(to,from,sizeof from,0x313c75u);
  assert(copies==1&&after_copies==1&&!memcmp(to,from,sizeof to));return 0;
 }
 if(!strcmp(argv[1],"full")){bank_full();return 0;}
 if(!strcmp(argv[1],"legacy")){
  start_with(AF_APPLY_PROTOCOL_REQUIRED&~AF_APPLY_CAP_USER20);target_slot=1;transmit(1);
  assert(!acks&&af_cp_recipe406_last_result()==AF_INVALID&&!af_cp_hs_input_version);
  assert(!af_cp_recipe406_seen_version()&&!af_cp_recipe406_busy()&&!af_cp_hs_input_fault);
  target_slot=7;completed(2);assert(acks==1);return 0;
 }
 if(!strcmp(argv[1],"slot1"))target_slot=1;
 if(!strcmp(argv[1],"sector"))sector_mode=1;
 start();
 if(!strcmp(argv[1],"unknown")){
  unsigned prior=acks;fail_unlock=1;transmit(1);
  assert(acks==prior&&af_cp_recipe406_last_result()==AF_IO);
  assert(af_cp_hs_input_fault&&af_cp_override406_faulted()&&!af_cp_native406_ready());
  assert(test_core_stage()==3&&af_cp_hs_input_version==0&&lock_held);
  check_active(1); /* 已写入但解锁未知，不能宣称回滚。 */
  AfRecipeLease lease;const AfRecipeOwned *pending=0;
  assert(!af_cp_recipe406_pending(&lease,&pending)&&pending&&pending->message.version==1);
  assert(af_cp_recipe406_release(&lease)==AF_BUSY);
  unsigned previous_locks=locks;transmit(2);
  assert(acks==prior&&locks==previous_locks&&af_cp_hs_input_version==0);return 0;
 }
 assert(!strcmp(argv[1],"three")||!strcmp(argv[1],"slot1")||!strcmp(argv[1],"sector"));
 completed(1);completed(2);completed(3);
 /* 新USER20协商显式覆盖C01；原厂Backup不属于这条传输写入范围。 */
 assert(af_cp_handshake.required&AF_APPLY_CAP_USER20);target_slot=1;completed(4);
 assert(acks==4&&jobs_binds==1&&component_binds==1&&test_core_arena_used()==1);
 assert(locks==4&&!lock_held&&unlocks==tries+locks);return 0;
}
'''


def replace_required(body, replacements):
    for old, new in replacements.items():
        assert old in body, old
        body = body.replace(old, new)
    return body


def compile_native_binding(folder, capture, bad_padding=None, driver=None):
    ports = folder / "ports.h"
    ports.write_text(PORTS)
    core = replace_required((NATIVE / "af_cp_native406.c").read_text(), {
        "#if defined(__arm__) && defined(AF_CP_NATIVE406)": "#if defined(AF_CP_NATIVE406)",
        "(const volatile uint8_t *)(uintptr_t)0xbef718u": "test_factor",
        "(const volatile uint8_t *)(uintptr_t)a": "test_contract(a)",
        "(const volatile uint8_t *)(uintptr_t)starts[part]": "test_contract(starts[part])",
        "((int(*)(const void *,size_t,uint32_t))(uintptr_t)0x496181u)": "test_sender",
        "((void(*)(void *,const void *,size_t))(uintptr_t)0x5f51bcu)": "test_stock_copy",
    })
    core += "\nunsigned test_core_stage(void){return stage;}\nunsigned test_core_pending_copy(void){return pending_copy;}\nunsigned test_core_arena_used(void){return arena_used;}\n"
    overlay = replace_required((NATIVE / "af_cp_override406.c").read_text(), {
        "#if defined(__arm__) && defined(AF_SNAPSHOT_OVERLAY406)": "#if defined(AF_SNAPSHOT_OVERLAY406)",
        '__asm__ volatile("dmb sy" ::: "memory");': "__atomic_thread_fence(__ATOMIC_SEQ_CST);",
        "(const void *)(uintptr_t)0x898548u": "test_snapshot",
        "(uint8_t *)(uintptr_t)0x19c999du": "&test_marker",
        "((NativeLock)(uintptr_t)0x5b8d6cu)": "test_lock",
        "((NativeLock)(uintptr_t)0x5b8910u)": "test_unlock",
        "((NativeLock)(uintptr_t)0x5b8f58u)": "test_try",
        "(AfCpSnapshotCopy406)(uintptr_t)0x5f51bcu": "test_stock_copy",
    })
    # 只替换本次真实目标的固定端口；input中的原逻辑地址与第四记录身份保持。
    begin = overlay.index('void af_cp_override406_request_copy_target(void *dst,const void *source,size_t bytes){')
    end = overlay.index('\n#endif', begin)
    request_target = replace_required(overlay[begin:end], {
        '(uintptr_t)dst!=AF_CP_INPUT406_REQUEST': '(uintptr_t)dst!=(uintptr_t)test_request',
        '(uintptr_t)source!=0x157aa10u': '(uintptr_t)source!=(uintptr_t)test_live',
        '*(const volatile uint32_t *)(uintptr_t)0x163f3c8u': 'test_request_id',
    })
    overlay = overlay[:begin]+request_target+overlay[end:]
    overlay += r'''
void test_snapshot_init(void){
 for(unsigned i=0;i<sizeof snapshot_code;++i)test_snapshot[i]=snapshot_code[i];
 /* 独立固定BL前像：898568 -> befa28，ARM不执行。 */
 test_snapshot[32]=0x57;test_snapshot[33]=0xf3;test_snapshot[34]=0x5e;test_snapshot[35]=0xfa;
}
const AfCpOverride406 *test_active(void){return &active;}
AfCpInput406 *test_inputs(void){return &input_state;}
'''
    ingress = replace_required((NATIVE / "af_hs_cp406.c").read_text(), {
        "((Sender)(uintptr_t)0x496181u)": "((Sender)test_sender)",
    })
    sources = []
    for name, body in (("core", core), ("overlay", overlay), ("ingress", ingress), ("driver", DRIVER if driver is None else driver)):
        source = folder / (name + ".c")
        source.write_text(body)
        sources.append(str(source))
    binary = folder / ("native-binding-capture" if capture else "native-binding")
    actual = ("af_cp_native_bank406.c", "af_cp_input406.c", "af_cp_copy406.c", "af_cp406_state.c",
              "af_cp_recipe406.c", "af_recipe_transport.c", "af_joint_asset.c", "af_joint.c",
              "af_sha256.c", "af_slots.c", "af_handshake.c", "af_apply_wire.c")
    flags = ("AF_CP_NATIVE406", "AF_CP_PRESET406", "AF_RUNTIME406", "AF_FACTORY_RESTORE406",
             "AF_RECIPE_BRIDGE406", "AF_SNAPSHOT_OVERLAY406", "AF_CP_CARVE_BRANCH406",
             "AF_CP_CAPTURE_INPUT406", "AF_CP_CAPTURE_COPIES406")
    if capture:
        flags += ("AF_CP_CAPTURE406",)
    extra = [f'-DTEST_BAD_CAPTURE_PAD={bad_padding}'] if bad_padding is not None else []
    if driver is not None:
        extra.append('-Wno-unused-function')
    compiled = subprocess.run(
        ["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
         *["-D" + flag + "=1" for flag in flags], *extra, "-DAF_CP_SNAPSHOT_ENTRY406=0xbefa29u",
         "-I" + str(NATIVE), "-include", str(ports), *sources,
         *[str(NATIVE / name) for name in actual], "-o", str(binary)], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    return binary


@pytest.fixture(scope="module", params=[False, True], ids=["legacy", "capture"])
def native_binding_driver(tmp_path_factory, request):
    return compile_native_binding(tmp_path_factory.mktemp("cp-native-binding406"), request.param)


@pytest.mark.parametrize("scenario", ["factor", "hook", "busy", "partial", "three", "slot1", "legacy", "full", "unknown", "shot", "sector"])
def test_actual_native_binding_transport_and_lock_ownership(native_binding_driver, scenario):
    run = subprocess.run([str(native_binding_driver), scenario], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("scenario", ["capture-region0", "capture-region1", "capture-region2",
                                      "capture-region3", "capture-region4", "capture-region5",
                                      "capture-region6", "capture-region7", "capture-bind", "capture-lost"])
def test_capture_contract_binding_and_runtime_failure(native_binding_driver, scenario):
    if native_binding_driver.name != "native-binding-capture":
        pytest.skip("旧配置不绑定Capture通路")
    run = subprocess.run([str(native_binding_driver), scenario], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize('padding', [582, 583])
def test_capture_contract_storage_padding_is_checked_before_bind(tmp_path, padding):
    binary = compile_native_binding(tmp_path, True, padding)
    run = subprocess.run([str(binary), 'capture-padding'], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
