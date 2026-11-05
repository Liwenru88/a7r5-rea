"""宿主端口运行原调用顺序和失败回退；Thumb仅编译与静态解码。"""
from pathlib import Path
import subprocess
import pytest

NATIVE=Path(__file__).resolve().parents[1]/'native'

@pytest.fixture(scope='module')
def component_binary(tmp_path_factory):
    directory=tmp_path_factory.mktemp('native-components')
    source=directory/'components.c'
    source.write_text(r'''
#include "af_cp_components406.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static AfCpComponents406 state;
static AfCpRuntimeAsset406 asset;
static AfCpJobs406View view;
static uint8_t root[8],prefix[0xe70],params[0x4e],record[576],output[0x470];
static uint8_t operation[0x360],calibration[16],pipe[24],grid_state[0x18a],context[0x6b4],stage[12],packed[1620];
static unsigned native_calls,private_calls,current_calls,change_at,allowed=1,query_calls,pack_calls,query_result=1,correct_worker=1;
static uint8_t shot[0x12d8],baseline[0x12d8],actual_a=7,actual_b=8;
static unsigned gamma_bank_selector,native_invalid;
static uint8_t source_image[84],shadow_image[84];
static unsigned source_calls,reset_calls,copy_calls,copy_race;
static void put(void *p,uint32_t n){uint8_t *b=p;for(unsigned i=0;i<4;++i)b[i]=(uint8_t)(n>>(8*i));}
static uint32_t get(const void *p){const uint8_t *b=p;return b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;}
static int snapshot(void *c,uint32_t id,AfCpJobs406View *out){(void)c;if(!allowed)return AF_EMPTY;*out=view;out->identity=id;return AF_OK;}
static int current(void *c,const AfCpJobs406View *v){(void)c;assert(v->asset==&asset);++current_calls;return change_at&&current_calls>=change_at?AF_STALE:AF_OK;}
static int read_memory(void *c,uint32_t a,void *out,size_t n){(void)c;
 if(a==0x1f0dd80&&n==1){*(uint8_t *)out=actual_a;return 0;}
 if(a==0x1f0ddb2&&n==1){*(uint8_t *)out=actual_b;return 0;}
 if(a==0x1f6a088&&n==84){memcpy(out,source_image,84);return 0;}
 if(a==0x2034&&n==1){*(uint8_t *)out=operation[0x34];return 0;}
 if(a==0x2004&&n==4){put(out,view.c4_address);return 0;}
 if(a==view.c4_address&&n==4){put(out,view.prefix_address);return 0;}
 if(a>=AF_CP_COMPONENTS406_GAMMA_TABLE&&a<AF_CP_COMPONENTS406_GAMMA_TABLE+51*28&&n==4){put(out,0xdcca0c);return 0;}
 if(a==0xdcca0c&&n==576){memcpy(out,record,576);return 0;}return AF_IO;
}
static uint32_t matrix(void *c,void *out,uint32_t sector,void *r,uint32_t profile){(void)c;assert(r==root&&sector<=16);++native_calls;for(unsigned i=0;i<27;++i)((int16_t *)out)[i]=(int16_t)(100+i+profile);return 101;}
static uint32_t cc1(void *c,void *out,uint32_t profile,void *r){(void)c;assert(r==root);++native_calls;for(unsigned i=0;i<24;++i)((int16_t *)out)[i]=(int16_t)(100+i+profile);return 102;}
static uint32_t gamma(void *c,uint32_t mode,const void *p,void *out){(void)c;(void)mode;assert(p==params);++native_calls;memcpy((uint8_t *)out+0x24c,record,516);if(native_invalid)memset((uint8_t *)out+0x24c,0,516);return 103;}
static uint32_t gamma_record(void *c,uint32_t mode,const void *p,void *out,const void *candidate){(void)c;assert(!mode&&p==params);++private_calls;
 assert(!memcmp((const uint8_t *)candidate+0x204,record+0x204,0x1c));
 assert(get((const uint8_t *)candidate+0x220)==get((const uint8_t *)candidate+512));
 memcpy((uint8_t *)out+0x24c,candidate,516);return 104;
}
static void *map(void *c,uint32_t a,size_t n){(void)c;
 if(a==0x2000&&n<=sizeof operation)return operation;
 if(a==0x2100&&n<=sizeof calibration)return calibration;
 if(a==0x5000&&n<=sizeof grid_state)return grid_state;
 if(a==0x6000&&n<=sizeof context)return context;
 if(a==0x7000&&n<=sizeof stage)return stage;
 if(a==0x8000&&n<=sizeof packed)return packed;
 if(a==0x9000&&n<=sizeof asset.recipe.grid)return asset.recipe.grid;
 return 0;
}
static int address(void *c,const void *p,size_t n,uint32_t *out){(void)c;
 if(p==asset.recipe.grid&&n==1215){*out=0x9000;return 0;}
 if(p==output&&n==AF_CP_COMPONENTS406_GAMMA_PACKED_BYTES){*out=gamma_bank_selector?AF_CP_COMPONENTS406_GAMMA_PACKED1:AF_CP_COMPONENTS406_GAMMA_PACKED0;return 0;}
 return AF_INVALID;
}
static uint32_t query(void *c,void *r,void *p){(void)c;assert(r==root&&p==pipe&&context[0x54]==255);++query_calls;context[0x54]=0;return query_result;}
static void pack(void *c,void *r,void *p){(void)c;assert(r==root&&p==pipe);++pack_calls;memset(packed,get(grid_state+0x184)==0x9000?37:12,sizeof packed);}
static int worker(void *c,uint32_t identity){(void)c;assert(identity==2||identity==3);return correct_worker?0:AF_EMPTY;}
static uint32_t source_build(void *c,const void *p){(void)c;assert(p==params);++source_calls;
 for(unsigned i=0;i<84;++i)source_image[i]=(uint8_t)(i+source_calls);return 105;}
static uint32_t source_reset(void *c,const void *p){(void)c;assert(p==params);++reset_calls;memset(source_image,0,84);memset(shadow_image,0,84);return 106;}
static void source_copy(void *c,void *d,const void *p,size_t n){(void)c;++copy_calls;memcpy(d,p,n);
 if(copy_race==1)(void)af_cp_components406_gamma_source(&state,params);
 if(copy_race==2)(void)af_cp_components406_gamma_reset(&state,params);
 if(copy_race==3)((uint8_t *)d)[7]^=1;
 if(copy_race==4){copy_race=0;assert(af_cp_components406_gamma_copy(&state,d,p,n,0x1f6a43c,0x1f6a088,0xaa697d)==AF_EMPTY);}
}
int main(int argc,char **argv){
 assert(argc==2);int which=atoi(argv[1]);
 AfCpComponents406Ports ports={0,snapshot,current,read_memory,matrix,cc1,gamma,gamma_record,map,query,pack,0x100001,address,worker,source_build,source_reset,source_copy};
 assert(!af_cp_components406_init(&state,&ports));assert(af_cp_components406_init(&state,&ports)==AF_INVALID);
 asset.native_mode=1;view.asset=&asset;view.lease.asset=&asset;view.lease.version=9;view.input.version=9;
 view.c4_address=0x3000;view.prefix_address=0x4000;view.prefix=prefix;put(root,0x2000);
 put(params+0x30,0);params[0x38]=6;
 for(unsigned i=0;i<129;++i)put(record+4*i,i*1000);
 for(unsigned i=0x204;i<576;++i)record[i]=(uint8_t)(i*13);
 put(record+0x220,128000);
 if(which==0){
  asset.recipe.matrix[0]=7;asset.recipe.matrix[1]=-2;asset.recipe.cc1[0]=13;
  int16_t out[29];out[27]=1234;out[28]=4321;
  assert(af_cp_components406_matrix(&state,out,7,root,0)==101&&out[0]==105&&out[1]==94&&out[2]==104&&out[27]==1234&&out[28]==4321);
  assert(af_cp_components406_cc1(&state,out,0,root)==102&&out[0]==113&&out[1]==101);
  /* FL2/FL3及旧六由原包装器处理，私有端点不进入。 */
  for(unsigned profile=54;profile<=55;++profile){assert(af_cp_components406_matrix(&state,out,7,root,profile)==101&&out[0]==100+(int)profile);}
  allowed=0;assert(af_cp_components406_cc1(&state,out,0,root)==102&&out[0]==100);
  assert(native_calls==5);
 }else if(which==1){
  int16_t out[27];asset.recipe.matrix[0]=30;change_at=2;
  assert(af_cp_components406_matrix(&state,out,7,root,0)==101&&out[0]==100&&native_calls==1);
  change_at=0;asset.native_mode=0;assert(af_cp_components406_cc1(&state,out,0,root)==102&&out[0]==100);
  asset.native_mode=1;put(root,0x1234);assert(af_cp_components406_cc1(&state,out,0,root)==102&&out[0]==100);
  put(root,0x2000);put(prefix+0x238,1);asset.native_tone[0]=128;
  assert(af_cp_components406_matrix(&state,out,7,root,0)==101&&out[0]==100);
  assert(af_cp_components406_cc1(&state,out,0,root)==102&&out[0]==100);
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==103);
  assert(native_calls==6&&!private_calls&&!memcmp(output+0x24c,record,516));
 }else if(which==2){
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==104);
  assert(!memcmp(output+0x24c,record,516)&&private_calls==1&&!native_calls);
  asset.native_tone[0]=128;
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==104);
  assert(get(output+0x24c+256)>get(record+256));
  /* 非column6仍保留该实际记录；不拿seed/最终绝对Gamma覆盖。 */
  params[0x38]=2;for(unsigned i=0;i<129;++i)put(record+4*i,i*900);put(record+0x220,128*900);
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==104&&get(output+0x24c+256)>57600);
  assert(!state.gamma_busy&&private_calls==3);
 }else if(which==3){
  asset.native_tone[0]=128;change_at=2;
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==103);
  assert(private_calls==1&&native_calls==1&&!memcmp(output+0x24c,record,516));
  change_at=0;put(params+0x30,51);
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==103&&private_calls==1);
  put(params+0x30,0);params[0x38]=7;
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==103&&private_calls==1);
  params[0x38]=6;asset.native_mode=0;
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==103&&private_calls==1);
  asset.native_mode=1;
  assert(af_cp_components406_gamma(&state,1,params,AF_CP_COMPONENTS406_FORMATTER,output)==103);
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER+4,output)==103);
  assert(!state.gamma_busy);
 }else if(which==4){
  put(root+4,0x2100);put(pipe+8,0x5000);put(pipe+12,0x6000);put(pipe+16,0x7000);put(context+0x6b0,0x8000);
  operation[0x2f]=8;put(grid_state+0x184,0xa000);grid_state[0x188]=0;grid_state[0x189]=0;grid_state[0x18]=1;
  uint32_t lr=0x123457;
  assert(af_cp_components406_grid_enter(&state,root,pipe,&lr)==0x230f23&&lr==ports.grid_cleanup);
  assert(query_calls==1&&pack_calls==1&&packed[0]==37&&get(grid_state+0x184)==0x9000&&state.grid_banks[0].private_packed);
  assert(!af_cp_components406_grid_enter(&state,root,pipe,&lr)&&query_calls==1);
  assert(af_cp_components406_grid_leave(&state)==0x123457&&get(grid_state+0x184)==0xa000&&!grid_state[0x188]&&!grid_state[0x189]);
  /* 同指针新配方每次强制原query和packer；无缓存命中假成功。 */
  lr=0x123457;assert(af_cp_components406_grid_enter(&state,root,pipe,&lr)==0x230f23&&query_calls==2&&pack_calls==2);
  assert(af_cp_components406_grid_leave(&state)==0x123457);
  /* 切回原厂必须真实重包；恢复raw指针本身不清packed标记。 */
  allowed=0;lr=0x123457;assert(af_cp_components406_grid_enter(&state,root,pipe,&lr)==0x230f23&&packed[0]==12);
  assert(query_calls==3&&pack_calls==3&&!state.grid_banks[0].private_packed);
  assert(af_cp_components406_grid_leave(&state)==0x123457);
  lr=0x123457;assert(!af_cp_components406_grid_enter(&state,root,pipe,&lr)&&lr==0x123457&&query_calls==3);
 }else if(which==5){
  put(root+4,0x2100);put(pipe+8,0x5000);put(pipe+12,0x6000);put(pipe+16,0x7000);put(context+0x6b0,0x8000);
  operation[0x2f]=8;put(grid_state+0x184,0xa000);grid_state[0x18]=1;uint32_t lr;
  operation[0x2f]=0;lr=0x123457;assert(!af_cp_components406_grid_enter(&state,root,pipe,&lr)&&lr==0x123457&&!query_calls);operation[0x2f]=8;
  for(unsigned q=0;q<=4;q+=4){
   query_result=q;lr=0x123457;
   assert(af_cp_components406_grid_enter(&state,root,pipe,&lr)==0x230f63&&lr==ports.grid_cleanup);
   assert(!pack_calls&&!state.grid_banks[0].private_packed&&context[0x54]==255&&get(grid_state+0x184)==0xa000);
   assert(af_cp_components406_grid_leave(&state)==0x123457);
  }
  /* 原query已执行才失效：恢复原源后执行既定packer一次，不再次query。 */
  query_result=1;change_at=current_calls+2;lr=0x123457;
  correct_worker=0;assert(!af_cp_components406_grid_enter(&state,root,pipe,&lr)&&query_calls==2&&lr==0x123457);correct_worker=1;
  assert(af_cp_components406_grid_enter(&state,root,pipe,&lr)==0x230f23&&pack_calls==1&&query_calls==3&&packed[0]==12);
  assert(!state.grid_banks[0].private_packed&&af_cp_components406_grid_leave(&state)==0x123457);
 }else if(which==6){
  put(root+4,0x2100);put(pipe+8,0x5000);put(pipe+12,0x6000);put(pipe+16,0x7000);put(context+0x6b0,0x8000);
  operation[0x2f]=8;put(grid_state+0x184,0xa000);grid_state[0x18]=1;uint32_t lr=0x123457;
  assert(af_cp_components406_grid_enter(&state,root,pipe,&lr)==0x230f23);
  assert(query_calls==1&&pack_calls==1&&state.grid_banks[0].private_packed);
  assert(af_cp_components406_grid_leave(&state)==0x123457);
  allowed=0;operation[0x2e]=249;lr=0x123457;
  /* 返回0仍沿原BEF550，但借原savedLR收口；本helper不得提前query/pack。 */
  assert(!af_cp_components406_grid_enter(&state,root,pipe,&lr)&&lr==ports.grid_cleanup);
  assert(query_calls==1&&pack_calls==1&&context[0x54]==255);
  /* 显式模拟原selector产生另一原生raw，然后原query/packer各一次。 */
  put(grid_state+0x184,0xb000);grid_state[0x188]=1;grid_state[0x189]=2;
  assert(query(0,root,pipe)==1);pack(0,root,pipe);
  assert(af_cp_components406_grid_leave(&state)==0x123457);
  assert(get(grid_state+0x184)==0xb000&&grid_state[0x188]==1&&grid_state[0x189]==2);
  /* 本helper没观察到原packer完成，保持待重包标记，不能虚报恢复。 */
  assert(state.grid_banks[0].private_packed&&query_calls==2&&pack_calls==2);
  lr=0x123457;assert(!af_cp_components406_grid_enter(&state,root,pipe,&lr));grid_state[0x18]=0;
  assert(af_cp_components406_grid_leave(&state)==0x123457&&!state.grid_banks[0].private_packed);
 }else if(which==7){
  asset.recipe.matrix[0]=27;asset.recipe.cc1[0]=11;
  uint8_t before[sizeof prefix];memcpy(before,prefix,sizeof prefix);
  assert(!af_cp_components406_prepare(&state,3));
  /* 同九值新LUT版本只换真实票据；prepare不靠改AE/WB/八值强造native dirty。 */
  view.lease.version=view.input.version=10;asset.recipe.matrix[0]=38;
  assert(!af_cp_components406_prepare(&state,3)&&!memcmp(prefix,before,sizeof prefix));
  assert(!af_cp_components406_prepare(&state,2));
  change_at=current_calls+1;assert(af_cp_components406_prepare(&state,3)==AF_STALE);
  change_at=0;put(prefix+0x238,1);assert(af_cp_components406_prepare(&state,3)==AF_EMPTY);
  put(prefix+0x238,0);assert(af_cp_components406_prepare(&state,6)==AF_EMPTY);
  allowed=0;assert(af_cp_components406_prepare(&state,3)==AF_EMPTY);
 }else if(which==8){
  memset(baseline,0x65,sizeof baseline);memcpy(shot,baseline,sizeof shot);
  assert(!af_cp_components406_shot_after(&state,shot,AF_CP_COMPONENTS406_SHOT,AF_CP_COMPONENTS406_SHOT_BASELINE,sizeof shot,AF_CP_COMPONENTS406_SHOT_COPY_LR));
  assert(shot[0x920]!=actual_a&&shot[0x920]!=actual_b&&shot[0x920]<=2&&shot[0xb]==0x65);
  for(unsigned i=0;i<sizeof shot;++i)if(i!=0x920)assert(shot[i]==baseline[i]);
  /* 任意两个原byte，固定3值集合总有代表；不写共享aux或原baseline。 */
  for(unsigned a=0;a<256;++a)for(unsigned b=0;b<256;++b){
   actual_a=(uint8_t)a;actual_b=(uint8_t)b;shot[0x920]=baseline[0x920];
   assert(!af_cp_components406_shot_after(&state,shot,AF_CP_COMPONENTS406_SHOT,AF_CP_COMPONENTS406_SHOT_BASELINE,sizeof shot,AF_CP_COMPONENTS406_SHOT_COPY_LR));
   assert(shot[0x920]!=actual_a&&shot[0x920]!=actual_b&&shot[0x920]<=2);
  }
  memcpy(shot,baseline,sizeof shot);correct_worker=0;
  assert(af_cp_components406_shot_after(&state,shot,AF_CP_COMPONENTS406_SHOT,AF_CP_COMPONENTS406_SHOT_BASELINE,sizeof shot,AF_CP_COMPONENTS406_SHOT_COPY_LR)==AF_EMPTY&&!memcmp(shot,baseline,sizeof shot));
  correct_worker=1;change_at=current_calls+2;
  assert(af_cp_components406_shot_after(&state,shot,AF_CP_COMPONENTS406_SHOT,AF_CP_COMPONENTS406_SHOT_BASELINE,sizeof shot,AF_CP_COMPONENTS406_SHOT_COPY_LR)==AF_STALE&&!memcmp(shot,baseline,sizeof shot));
  change_at=0;
  assert(af_cp_components406_shot_after(&state,shot,AF_CP_COMPONENTS406_SHOT,AF_CP_COMPONENTS406_SHOT_BASELINE,sizeof shot,AF_CP_COMPONENTS406_SHOT_COPY_LR+4)==AF_INVALID);
  assert(af_cp_components406_shot_after(&state,shot,AF_CP_COMPONENTS406_SHOT+4,AF_CP_COMPONENTS406_SHOT_BASELINE,sizeof shot,AF_CP_COMPONENTS406_SHOT_COPY_LR)==AF_INVALID);
  assert(af_cp_components406_shot_after(&state,shot,AF_CP_COMPONENTS406_SHOT,AF_CP_COMPONENTS406_SHOT_BASELINE+4,sizeof shot,AF_CP_COMPONENTS406_SHOT_COPY_LR)==AF_INVALID);
  assert(af_cp_components406_shot_after(&state,shot,AF_CP_COMPONENTS406_SHOT,AF_CP_COMPONENTS406_SHOT_BASELINE,sizeof shot-4,AF_CP_COMPONENTS406_SHOT_COPY_LR)==AF_INVALID);
  assert(!memcmp(shot,baseline,sizeof shot));
  /* 两个原Gamma银行分别真正走原formatter，才能结束原厂回退的持续失效。 */
  for(unsigned i=0;i<2;++i){gamma_bank_selector=i;assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==104);}
  assert(state.gamma_private_mask==3);allowed=0;
  assert(!af_cp_components406_shot_after(&state,shot,AF_CP_COMPONENTS406_SHOT,AF_CP_COMPONENTS406_SHOT_BASELINE,sizeof shot,AF_CP_COMPONENTS406_SHOT_COPY_LR));
  assert(state.gamma_private_mask==3);gamma_bank_selector=0;
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==103&&state.gamma_private_mask==2);
  gamma_bank_selector=1;native_invalid=1;
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==103&&state.gamma_private_mask==2);
  native_invalid=0;
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER+4,output)==103&&state.gamma_private_mask==2);
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==103&&!state.gamma_private_mask);
  memcpy(shot,baseline,sizeof shot);
  assert(af_cp_components406_shot_after(&state,shot,AF_CP_COMPONENTS406_SHOT,AF_CP_COMPONENTS406_SHOT_BASELINE,sizeof shot,AF_CP_COMPONENTS406_SHOT_COPY_LR)==AF_EMPTY&&!memcmp(shot,baseline,sizeof shot));
 }else if(which==18){
  asset.matrix_mode=1;int16_t out[29];out[27]=1234;out[28]=4321;
  for(unsigned e=0;e<3;++e)for(unsigned sector=0;sector<16;++sector)
   asset.sector_matrix[(16*e+sector)*6]=(int16_t)(sector+e*16+1);
  for(unsigned sector=0;sector<16;++sector){
   assert(af_cp_components406_matrix(&state,out,sector,root,0)==101);
   for(unsigned e=0;e<3;++e){assert(out[9*e]==100+(int)(9*e)+(int)sector+(int)e*16+1);
    assert(out[9*e+1]==101+(int)(9*e)-(int)sector-(int)e*16-1);}
   assert(out[27]==1234&&out[28]==4321);
  }
  assert(native_calls==16);
  assert(af_cp_components406_matrix(&state,out,16,root,0)==101&&out[0]==100);
  asset.sector_matrix[0]=1025;assert(af_cp_components406_matrix(&state,out,0,root,0)==101&&out[0]==100);
  asset.sector_matrix[0]=1;change_at=current_calls+2;
  assert(af_cp_components406_matrix(&state,out,0,root,0)==101&&out[0]==100);
  change_at=0;
  for(unsigned profile=54;profile<=55;++profile)assert(af_cp_components406_matrix(&state,out,0,root,profile)==101&&out[0]==100+(int)profile);
  allowed=0;assert(af_cp_components406_matrix(&state,out,0,root,0)==101&&out[0]==100);
 }else if(which>=9&&which<=17){
  AfCpGamma406Tone stamp={0};asset.native_tone[0]=128;asset.native_tone[1]=-32;
  view.input.source=AF_CP_INPUT406_COPY_A;view.input.epoch=18;view.input.origin_snapshot_epoch=12;
  view.input.slot=7;view.ticket=37;
  assert(af_cp_components406_gamma_shadow(&state,&stamp)==AF_EMPTY);
  if(which==16)allowed=0;
  assert(af_cp_components406_gamma_source(&state,params)==105&&source_calls==1);
  allowed=1;
  if(which==17){view.input.version=view.lease.version=10;view.ticket=38;}
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==104);
  if(which==10)copy_race=1;
  if(which==11)copy_race=2;
  if(which==12)copy_race=3;
  if(which==13)copy_race=4;
  if(which==14){state.gamma_handoff.epoch=UINT32_MAX;assert(af_cp_components406_gamma_source(&state,params)==105);}
  if(which==15){state.gamma_handoff.guard=1;assert(af_cp_components406_gamma_source(&state,params)==105);state.gamma_handoff.guard=0;}
  assert(af_cp_components406_gamma_copy(&state,shadow_image,source_image,84,0x1f6a43c,0x1f6a088,0xaa697d)==(which==9?AF_OK:which>=14?AF_EMPTY:AF_STALE));
  assert(copy_calls==(which==13?2:1));
  if(which!=9){assert(af_cp_components406_gamma_shadow(&state,&stamp)==AF_EMPTY);return 0;}
  assert(!af_cp_components406_gamma_shadow(&state,&stamp));
  assert(stamp.version==9&&stamp.input_source==AF_CP_INPUT406_COPY_A&&stamp.input_epoch==18&&stamp.snapshot_epoch==12&&stamp.slot==7&&stamp.ticket==37);
  assert(stamp.tone[0]==128&&stamp.tone[1]==-32&&!stamp.tone[2]);
  /* 复制后不借用asset；同九值新配方按原构造代号发布，不读取全局最新。 */
  asset.native_tone[0]=256;view.lease.version=view.input.version=10;view.ticket=38;
  assert(!af_cp_components406_gamma_shadow(&state,&stamp)&&stamp.version==9&&stamp.tone[0]==128);
  assert(af_cp_components406_gamma_source(&state,params)==105);
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==104);
  assert(!af_cp_components406_gamma_copy(&state,shadow_image,source_image,84,0x1f6a43c,0x1f6a088,0xaa697d));
  assert(!af_cp_components406_gamma_shadow(&state,&stamp)&&stamp.version==10&&stamp.tone[0]==256);
  /* 原厂重建撤销source身份；真实copy撤销shadow，不凭相同参数延用LUT。 */
  assert(af_cp_components406_gamma_source(&state,params)==105);allowed=0;
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==103);
  assert(af_cp_components406_gamma_copy(&state,shadow_image,source_image,84,0x1f6a43c,0x1f6a088,0xaa697d)==AF_EMPTY);
  assert(af_cp_components406_gamma_shadow(&state,&stamp)==AF_EMPTY&&copy_calls==3);
  allowed=1;assert(af_cp_components406_gamma_source(&state,params)==105);
  assert(af_cp_components406_gamma(&state,0,params,AF_CP_COMPONENTS406_FORMATTER,output)==104);
  assert(!af_cp_components406_gamma_copy(&state,shadow_image,source_image,84,0x1f6a43c,0x1f6a088,0xaa697d));
  assert(af_cp_components406_gamma_reset(&state,params)==106&&reset_calls==1);
  assert(af_cp_components406_gamma_shadow(&state,&stamp)==AF_EMPTY);
 }else return 2;
 return 0;
}
''')
    binary=directory/'components'
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-I'+str(NATIVE),str(source),*[str(NATIVE/name) for name in
        ('af_cp_components406.c','af_joint.c','af_color406.c')],'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return binary

@pytest.mark.parametrize('scenario',range(19),ids=['native-endpoints-factory','changed-view','real-column-tones','gamma-fallback','grid-repack-switchback','grid-no-repeated-callees','grid-legacy-selector-switchback','worker-prepare-identity-not-image-success','shot-copy-dirty-and-both-factory-banks','gamma-native-shadow-version','gamma-source-copy-race','gamma-reset-copy-race','gamma-copy-corruption','gamma-copy-reentry','gamma-epoch-exhausted','gamma-nonblocking-contention','gamma-constructor-without-worker-view','gamma-constructor-previous-ticket','all-sixteen-sectors-and-native-fallback'])
def test_native_component_ports(component_binary,scenario):
    result=subprocess.run([str(component_binary),str(scenario)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr

def test_thumb_components_compile_and_original_gamma_frame(tmp_path):
    for name in ('af_cp_components406.c','af_cp_components406.S'):
        result=subprocess.run(['clang','--target=armv7a-none-eabi','-mthumb','-march=armv7-a','-Oz',
            '-ffreestanding','-fno-builtin','-Wall','-Wextra','-Werror','-DAF_CP_COMPONENTS406_TARGET=1',
            '-c',str(NATIVE/name),'-o',str(tmp_path/(name+'.o'))],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    result=subprocess.run(['nm','-u',str(tmp_path/'af_cp_components406.c.o')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert '__aeabi_' not in result.stdout and '__atomic_' not in result.stdout
    # 检查实际Thumb编码与帧布局；不执行ARM。
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    from elftools.elf.elffile import ELFFile
    with (tmp_path/'af_cp_components406.S.o').open('rb') as stream:
        elf=ELFFile(stream);section=elf.get_section_by_name('.text');raw=section.data()
        symbols={s.name:s.entry for s in elf.get_section_by_name('.symtab').iter_symbols()}
        def decode(name):
            e=symbols[name];start=e['st_value']&~1
            return [(i.mnemonic,i.op_str) for i in Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(raw[start:start+e['st_size']],start)]
        inner=decode('af_cp_components406_gamma_inner')
        assert inner[:2]==[('push.w','{r4, r5, r6, r7, r8, sb, sl, fp, lr}'),('sub','sp, #4')]
        assert ('sub.w','sp, sp, #0x240') in inner and b'\xaf\xf9\xbe\x00' in raw
        gate=decode('af_cp_components406_grid_gate')
        assert ('add','r2, sp, #0x44') in gate
        assert ('msr','apsr_nzcvq, ip') in gate
        assert any(op.startswith('ldr') and args=='pc, [sp], #0x20' for op,args in gate)

def test_fixed_cp_controller_frame_and_real_gamma_route_source():
    """固定原字节、完整控制器SP控制流与实际producer；不执行目标指令。"""
    import hashlib
    import sys
    import struct
    import importlib.util
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    root=NATIVE.parents[1]
    packaging=root/'custom-filters'/'experiments'/'packaging406'
    spec=importlib.util.spec_from_file_location('component_fixed_preflight',packaging/'candidate_preflight.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    cp=module.read_cpio(root.parent/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio',{'cp/cpapp-b.bin'})['cp/cpapp-b.bin']
    assert hashlib.sha256(cp).hexdigest()=='18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
    base=0x108000
    assert hashlib.sha256(cp[0x230da8-base:0x231216-base]).hexdigest()=='895431c0cd8bf8776b401485bd759656565a76182c0ecc645e31b8020c42ad0e'
    decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    def instruction(at):
        return next(decoder.disasm(cp[at-base:at-base+4],at))
    pins={
        0x230da8:('push','{r4, r5, r6, r7, lr}'),0x230dac:('push.w','{r8, sb, sl, fp}'),
        0x230db0:('sub','sp, #4'),0x230f0c:('b.w','#0xbef550'),
        0x230f12:('bl','#0x231234'),0x230f1e:('bl','#0x231654'),
        0x2310f8:('add','sp, #4'),0x2310fa:('pop.w','{r8, sb, sl, fp}'),
        0x2310fe:('pop.w','{r4, r5, r6, r7, lr}'),0x231102:('b.w','#0xb0de92'),
        0x231106:('add','sp, #4'),0x231108:('pop.w','{r8, sb, sl, fp}'),
        0x23110c:('pop','{r4, r5, r6, r7, pc}'),
        0xaa831c:('str','r0, [r8, #0x30]!'),0xaa8442:('cmp','r0, #0x33'),
        0xaa84ba:('strb.w','r0, [r4, #0x38]'),
        0x41364e:('ldr.w','r1, [sb, #0x30]'),0x413652:('ldrb.w','r2, [sb, #0x38]'),
        0x24119a:('ldr.w','lr, [r8, #0xa40]'),0x24119e:('ldr.w','ip, [r8, #0x238]'),
        0x2411d2:('cmp.w','ip, #0'),0x2411dc:('movs','r2, #8'),
        0x241212:('ldr.w','r2, [r8, #0xa54]'),0x241258:('ldrb.w','r2, [r8, #0x23c]'),
        0x24125c:('strb.w','r2, [fp, #0x2f]'),
        0xbef9b6:('bl','#0xbef8bc'),0xbef9ba:('add.w','sp, sp, #0x240'),
        0xbef9be:('add','sp, #4'),0xbef9c0:('pop.w','{r4, r5, r6, r7, r8, sb, sl, fp, pc}'),
    }
    for at,expected in pins.items():
        i=instruction(at);assert (i.mnemonic,i.op_str)==expected,(hex(at),i.mnemonic,i.op_str)
    # ST look0、source238==0的TBB index0实际到241212，再经241228回2411DC常量8。
    assert 0x2411ea+2*cp[0x2411ea-base]==0x241212
    assert instruction(0x241228).op_str=='#0x2411dc'
    # 原header第二RO描述符(相对源偏移,字节,VA)，不是凭扫描END猜的RO边界。
    assert struct.unpack_from('<III',cp,0x128130-base)==(0xac8000,0x48f000,0xbf0000)
    assert 0xbf0000+0x48f000==0x107f000
    arm=Cs(CS_ARCH_ARM,0)
    ro=list(arm.disasm(cp[0x1084d8-base:0x1084f4-base],0x1084d8))
    assert [(i.mnemonic,i.op_str) for i in ro][-2:]==[('mov','r3, #0xd'),('bl','#0x108768')]
    # 限定原函数及两处已安装的无新栈尾跳；switch容量来自紧邻CMP3/CMP4。
    switches={0x230e1e:4,0x230f4c:5}
    pending=[(0x230da8,0)];seen=set();exits=set();gates=set()
    while pending:
        at,sp=pending.pop()
        if (at,sp) in seen:continue
        seen.add((at,sp));assert len(seen)<1000
        assert 0x230da8<=at<0x231216 or 0xbef53e<=at<0xbef580 or 0xbef5a8<=at<0xbef5d0,hex(at)
        i=instruction(at);op,args=i.mnemonic,i.op_str
        if op.startswith('push'):sp-=4*len(args.strip('{}').split(','))
        if op.startswith('pop'):
            sp+=4*len(args.strip('{}').split(','))
            if 'pc' in args:assert sp==0;exits.add(at);continue
        if args.startswith('sp, #') and op in ('add','sub'):
            amount=int(args.split('#')[1],0);sp+=amount if op=='add' else -amount
        if at==0xbef550:assert sp==-40;gates.add(sp)
        if op=='tbh':
            for index in range(switches[at]):
                delta=struct.unpack_from('<H',cp,at+4-base+2*index)[0]
                pending.append((at+4+2*delta,sp))
            continue
        if op in ('b','b.w'):
            target=int(args[1:],16)
            if target==0xb0de92:assert sp==0;exits.add(at);continue
            pending.append((target,sp));continue
        if op.startswith('b') and op not in ('bl','blx','bic','bfi','bfc'):
            pending.append((int(args[1:],16),sp))
        if op in ('cbz','cbnz'):pending.append((int(args.split('#')[1],16),sp))
        pending.append((at+i.size,sp))
    assert gates=={-40} and exits=={0x23110c,0x231102}
    # 原LR在entry SP-4，gate SP=entry SP-40，所以实际savedLR为gate SP+36。
    assert -4-(-40)==0x24
    # 实际id3正常组件链不按旧八值相等跳过endpoint；r5=0走原平滑。
    for at,target in {0x719686:0x23091c,0x230be6:0x240d34,0x230bee:0x73edc8,
                      0x719f06:0x231eb8,0x719f0e:0x71d37c,0x719f16:0x230da8,
                      0x71b8bc:0x71e670,0x71d6f8:0x71e41e}.items():
        i=instruction(at);assert i.mnemonic=='bl' and int(i.op_str[1:],16)==target
    for at,target in {0x73f10e:0x719ef6,0x73f174:0x719ef6,0x73f1e4:0x719ef6,
                      0x73f278:0x719ef6,0x73f2e6:0x719ef6,0x73f3f4:0x719ef6,
                      0x73f4c6:0x719ef6}.items():
        i=instruction(at);assert i.mnemonic=='bl' and int(i.op_str[1:],16)==target
    assert struct.unpack_from('<I',cp,0xd0fc78+20*4-base)[0]==0x73f49f
    assert instruction(0x73f49e).mnemonic=='bx'  # 原旁路保持旁路，不能套相邻22函数。
    assert instruction(0x2324c4).mnemonic=='cbnz'  # dirty0不是跳constructor，而是平滑路径。
    assert instruction(0x23257c).op_str=='r2, [ip, #0x11]'
    # 实际working-shot原copy、两个getter与原cache比较/回写。与源const tuple共同核对。
    assert cp[0x313c70-base:0x313c74-base].hex()=='e1f2a4ea'
    for at,expected in {
        0x313c68:('mov','r1, r4'),0x313c6a:('movw','r2, #0x12d8'),
        0x313c6e:('mov','r0, sb'),0x313c70:('blx','#0x5f51bc'),
        0x834946:('movw','r0, #0xa830'),0x83494a:('movt','r0, #0x1f0'),
        0x834a36:('movw','r0, #0xa50'),0x834a3a:('movt','r0, #0x1f1'),
        0x8349be:('movw','r0, #0xd2f0'),0x8349c2:('movt','r0, #0x1f0'),
        0x859154:('add.w','r0, r5, #0xa90'),0x859164:('addweq','r0, r5, #0xac2'),
        0x859168:('ldrb.w','r1, [r4, #0x920]'),0x85916c:('ldrb','r0, [r0]'),
        0x85916e:('cmp','r1, r0'),0x859170:('bne','#0x859178'),
        0x85917a:('strb','r1, [r4, #0xb]'),0x85917c:('strb.w','r0, [r4, #0x920]'),
        0x8591a2:('strb','r0, [r4, #0xb]'),0x85920e:('strb','r0, [r4, #0xb]'),
        0x859228:('strb','r0, [r4, #0xb]'),0x859238:('strb','r0, [r4, #0xb]'),
        0x859336:('strb.w','sl, [r4, #0xb]'),
        0x4139f4:('str.w','r6, [fp, #0x460]'),
        0x413b86:('strb.w','r0, [r3, #0x464]'),0x413b8e:('strb.w','r0, [r3, #0x465]'),
    }.items():
        i=instruction(at)
        # 单独反汇编IT中的一条不携带EQ后缀，因此这里只核其实际ADDW与寄存器。
        if at==0x859164:assert i.mnemonic=='addw' and i.op_str=='r0, r5, #0xac2'
        else:assert (i.mnemonic,i.op_str)==expected,(hex(at),i.mnemonic,i.op_str)
    # 原stock constructor完整CFG：从真实prologue后进入，不把被重定向的入口
    # 当作外尾；所有条件双分支都保留，因而覆盖mode0及其debug/fallback。
    start,end=0x413640,0x413d8a
    conditions={'beq','bne','bhs','blo','bmi','bpl','bvs','bvc','bhi','bls','bge','blt','bgt','ble'}
    todo=[start];graph={};gamma={};returns=set()
    while todo:
        at=todo.pop()
        if at in graph:continue
        assert start<=at<end,hex(at)
        i=instruction(at);gamma[at]=i;op=i.mnemonic.split('.')[0];following=at+i.size
        if op in ('bl','blx'):targets=[following]
        elif op=='pop' and 'pc' in i.op_str:targets=[];returns.add(at)
        elif op=='b':targets=[int(i.op_str[1:],16)]
        elif op in conditions:targets=[following,int(i.op_str[1:],16)]
        elif op in ('cbz','cbnz'):targets=[following,int(i.op_str.rsplit('#',1)[1],16)]
        else:
            assert op not in ('tbb','tbh','bx'),(hex(at),op)
            targets=[following]
        graph[at]=targets;todo.extend(targets)
    assert len(graph)==636 and returns=={0x413d88}
    def reachable(cut):
        found=set();todo=[start]
        while todo:
            at=todo.pop()
            if at in found or at in cut:continue
            found.add(at);todo.extend(graph[at])
        return found
    writers={0x413b5e,0x413b74,0x413ce2,0x413d48,0x413d78}
    assert not returns.intersection(reachable(writers))
    # 各循环计数器从0开始；初始化支配对应writer，之后只按原+1递增。
    # 通常两路在写index128后退出，其余三路写0..128并CMP129后退出。
    for writer,initialize,register in [(0x413b5e,0x413a3e,'sb'),(0x413ce2,0x413bcc,'r8'),
                                       (0x413b74,0x413b66,'r0'),(0x413d48,0x413d2c,'r5'),
                                       (0x413d78,0x413d72,'r1')]:
        assert writer not in reachable({initialize})
        assert gamma[initialize].mnemonic in ('mov','mov.w','movs')
        assert gamma[initialize].op_str==f'{register}, #0'
    for at,expected in {
        0x41365a:('add.w','r4, fp, #0x24c'),0x41369c:('str','r4, [sp, #0x30]'),
        0x413a7e:('add.w','sb, sb, #1'),0x413b5a:('cmp.w','sb, #0x80'),
        0x413b50:('ldrd','r2, r1, [sp, #0x2c]'),0x413b62:('bne','#0x413a7c'),
        0x413b6c:('ldrd','r3, r1, [sp, #0x2c]'),0x413b78:('adds','r0, #1'),
        0x413b7a:('cmp','r0, #0x81'),0x413b7c:('bne','#0x413b70'),
        0x413c04:('add.w','r8, r8, #1'),0x413cdc:('ldr','r1, [sp, #0x30]'),
        0x413cde:('cmp.w','r8, #0x80'),0x413ce8:('bne','#0x413bfe'),
        0x413d2a:('ldr','r4, [sp, #0x30]'),0x413d4c:('adds','r5, #1'),
        0x413d4e:('cmp','r5, #0x81'),0x413d50:('bne','#0x413d44'),
        0x413d7c:('adds','r1, #1'),0x413d7e:('cmp','r1, #0x81'),0x413d80:('bne','#0x413d74'),
    }.items():
        assert (gamma[at].mnemonic,gamma[at].op_str)==expected
