"""真实 Capture 来源缓存到颜色组件；宿主端口替代原调用，不执行 ARM。"""
from pathlib import Path
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'native'
DRIVER = r'''
#include "af_cp_capture406.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static AfCpCaptureColor406 *color;
static AfCpComponents406 state;
static AfCpInput406Token request;
static AfCpRuntimeAsset406 asset,main_asset;
static AfPreset actual[2];
static AfCpJobs406View main_view;
static uint8_t root[8],prefix[0xe70],operation[0x360],calibration[0x30],pipe[24];
static uint8_t raw_state[0x18a],context[0x6b4],stage[13],packed[3*1620];
static const int8_t *held_raw;
static uint32_t thread_id=22,request_id=7,object=0x71000000u;
static unsigned main_mode,qualified=1,query_calls,pack_calls,native_calls,query_result=1,test_base;
static unsigned query_loss,native_loss,nested,worker_ok=1,native_mode_change,mono_ready,mono_mode,mono_bad,native_profile_change;
static void put(void *p,uint32_t n){uint8_t *b=p;for(unsigned i=0;i<4;++i)b[i]=(uint8_t)(n>>(8*i));}
static uint32_t word(const void *p){const uint8_t *b=p;return b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;}
static int request_read(void *c,AfCpInput406Token *out,uint32_t *id){(void)c;*out=request;*id=request_id;return AF_OK;}
static int thread_read(void *c,uint32_t *id){(void)c;*id=thread_id;return AF_OK;}
static int r_matches(void *c,uint32_t r,const AfPreset *p){(void)c;
 if(r<object+0x20||(r-object-0x20)%0x1000)return AF_STALE;
 unsigned i=(r-object-0x20)/0x1000;if(i>=2||actual[i].base!=p->base)return AF_STALE;
 const unsigned indices[]={0,4,5,6,7};for(unsigned j=0;j<5;++j)if(actual[i].params[indices[j]]!=p->params[indices[j]])return AF_STALE;return AF_OK;
}
int af_cp_capture406_color_view_target(AfCpCaptureColor406View *out){return qualified?af_cp_capture_color406_view(color,out):AF_EMPTY;}
int af_cp_capture406_color_current_target(const AfCpCaptureColor406View *v){return qualified?af_cp_capture_color406_current(color,v):AF_STALE;}
int af_cp_capture406_color_scope_target(uint32_t r){AfCpCaptureColor406Scope seen;return af_cp_capture_color406_scope_observe(color,r,&seen);}
void af_cp_capture406_reset_target(void){}
int af_cp_capture406_read_target(uint32_t f,uint32_t o,AfCpGamma406Tone *tone,AfCpCapture406Token *t,uint8_t image[78]){
 (void)f;(void)o;(void)tone;(void)t;(void)image;return AF_EMPTY;
}
int af_cp_capture406_current_target(const AfCpCapture406Token *t){(void)t;return AF_EMPTY;}
static int view(void *c,uint32_t identity,AfCpJobs406View *out){(void)c;if(!main_mode)return AF_EMPTY;*out=main_view;out->identity=identity;return AF_OK;}
static int current(void *c,const AfCpJobs406View *v){(void)c;return main_mode&&qualified&&v->asset==&main_asset?AF_OK:AF_STALE;}
static int read_memory(void *c,uint32_t a,void *out,size_t n){(void)c;
 if(a==0x2125&&n==1){*(uint8_t *)out=calibration[0x25];return AF_OK;}
 if(a>=0x2000&&a-0x2000<=sizeof operation&&n<=sizeof operation-(a-0x2000)){memcpy(out,operation+(a-0x2000),n);return AF_OK;}
 if(a==0x3000&&n==4){put(out,0x4000);return AF_OK;}return AF_IO;
}
static uint32_t matrix(void *c,void *out,uint32_t sector,void *r,uint32_t profile){(void)c;assert(r==root&&sector<=16);++native_calls;
 for(unsigned i=0;i<27;++i)((int16_t *)out)[i]=(int16_t)(100+i+profile);if(native_loss)qualified=0;if(native_mode_change)operation[0x34]=3;return 101;
}
static uint32_t cc1(void *c,void *out,uint32_t profile,void *r){(void)c;assert(r==root);++native_calls;
 for(unsigned i=0;i<24;++i)((int16_t *)out)[i]=(int16_t)(100+i+profile);if(native_loss)qualified=0;if(native_mode_change)operation[0x34]=3;return 102;
}
static uint32_t gamma(void *c,uint32_t mode,const void *p,void *out){(void)c;(void)mode;(void)p;(void)out;return 103;}
static uint32_t gamma_record(void *c,uint32_t mode,const void *p,void *out,const void *record){(void)c;(void)mode;(void)p;(void)out;(void)record;return 104;}
static void *map(void *c,uint32_t a,size_t n){(void)c;
 if(a==0x2000&&n<=sizeof operation)return operation;if(a==0x2100&&n<=sizeof calibration)return calibration;
 if(a==0x5000&&n<=sizeof raw_state)return raw_state;if(a==0x6000&&n<=sizeof context)return context;
 if(a==0x7000&&n<=sizeof stage)return stage;
 if(a>=0x8000&&a-0x8000<=sizeof packed&&n<=sizeof packed-(a-0x8000))return packed+(a-0x8000);return 0;
}
static int address(void *c,const void *p,size_t n,uint32_t *out){(void)c;if(n!=AF_GRID_BYTES)return AF_INVALID;held_raw=p;*out=0x9000;return AF_OK;}
static uint32_t query(void *c,void *r,void *p){(void)c;assert(r==root&&p==pipe&&context[0x54+stage[11]]==255);++query_calls;context[0x54+stage[11]]=0;
 if(nested){uint32_t nested_lr=0x876543;uint32_t owner=state.grid.original_lr;unsigned before=query_calls;
  thread_id++;assert(!af_cp_components406_grid_enter(&state,root,pipe,&nested_lr));thread_id--;
  assert(nested_lr==0x876543&&state.grid.original_lr==owner&&query_calls==before&&state.grid.active);}
 if(query_loss)qualified=0;return query_result;
}
static void pack(void *c,void *r,void *p){(void)c;assert(r==root&&p==pipe);++pack_calls;uint8_t *dst=packed+1620*stage[11];
 if(word(raw_state+0x184)==0x9000){assert(raw_state[0x188]==1&&raw_state[0x189]==2&&held_raw);
  for(unsigned i=0;i<405;++i)put(dst+4*i,((uint32_t)held_raw[i]&127)<<22|((uint32_t)held_raw[i+405]&127)<<12|((uint32_t)held_raw[i+810]&127)<<2);
 }else memset(dst,12,1620);
}
static int worker(void *c,uint32_t identity){(void)c;assert(identity==2||identity==3);return main_mode&&worker_ok?AF_OK:AF_EMPTY;}
static uint32_t source(void *c,const void *p){(void)c;(void)p;return 105;}
static void source_copy(void *c,void *d,const void *p,size_t n){(void)c;memcpy(d,p,n);}
static void mono_asset(AfCpRuntimeAsset406 *a){
 a->matrix_mode=mono_mode;memset(a->recipe.matrix,0,sizeof a->recipe.matrix);memset(a->sector_matrix,0,sizeof a->sector_matrix);
 if(mono_mode){for(unsigned e=0;e<3;++e)for(unsigned s=0;s<16;++s){a->sector_matrix[e*96+s*6]=(int16_t)(s+1);a->sector_matrix[e*96+s*6+1]=-2;}
  if(mono_bad)a->sector_matrix[96+7*6]++;
 }else{for(unsigned e=0;e<3;++e){a->recipe.matrix[6*e]=7;a->recipe.matrix[6*e+1]=-2;}if(mono_bad)a->recipe.matrix[6]++;}
}
static uint32_t matrix9_native(void *out,const void *src){++native_calls;memcpy(out,src,18);if(native_loss)qualified=0;if(native_profile_change)calibration[0x25]=54;return 107;}
static int publish(unsigned v){
 assert(!af_cp_capture_color406_request_invalidate(color));memset(&request,0,sizeof request);
 request.version=v;request.source=AF_CP_CAPTURE_COLOR406_REQUEST;request.epoch=request.origin_snapshot_epoch=v*2;
 request.slot=7;request.mode=AF_CP_OVERRIDE_USER;request.flags=AF_CP_INPUT406_USER_VERSION;request.actual.params[6]=3;request.actual.base=(uint8_t)test_base;
 memset(&asset,0,sizeof asset);asset.base=test_base;asset.native_mode=1;asset.model_sha256[0]=8;
 asset.recipe.matrix[0]=(int16_t)(7*v);asset.recipe.matrix[1]=(int16_t)(-2*(int)v);asset.recipe.cc1[0]=(int16_t)(13*v);
 if(mono_ready)mono_asset(&asset);
 for(unsigned i=0;i<AF_GRID_BYTES;++i)asset.recipe.grid[i]=(int8_t)(v+i/405);
 return af_cp_capture_color406_request_publish(color,&request,request_id,&asset);
}
static void bind(unsigned index){AfCpCaptureColor406Write w;assert(!af_cp_capture_color406_a_birth(color,object+index*0x1000));
 assert(!af_cp_capture_color406_r_begin(color,object+index*0x1000,&w));actual[index]=request.actual;assert(!af_cp_capture_color406_r_end(color,&w));}
static AfCpCaptureColor406Scope begin(unsigned index,int expected){AfCpCaptureColor406Scope scope;
 assert(af_cp_capture_color406_scope_begin(color,object+index*0x1000+0x20,&scope)==expected);return scope;}
static void configure_capture(unsigned index){main_mode=0;operation[1]=1;put(operation+4,0);put(operation+8,object+index*0x1000+0x20);stage[11]=1;stage[12]=11;calibration[12]=11;}
static void initialize(void){
 color=calloc(1,af_cp_capture_color406_bytes());assert(color);AfCpCaptureColor406Ports cp={0,request_read,thread_read,r_matches};
 assert(!af_cp_capture_color406_init(color,af_cp_capture_color406_bytes(),&cp));
 AfCpComponents406Ports ports={0,view,current,read_memory,matrix,cc1,gamma,gamma_record,map,query,pack,0x100001,address,worker,source,source,source_copy};
 assert(!af_cp_components406_init(&state,&ports));put(root,0x2000);put(root+4,0x2100);
 put(pipe+8,0x5000);put(pipe+12,0x6000);put(pipe+16,0x7000);put(context+0x6b0,0x8000);
 operation[0x2f]=8;put(raw_state+0x184,0xa000);raw_state[0x18]=1;memset(packed,0xa5,sizeof packed);
 main_asset.native_mode=1;main_asset.recipe.matrix[0]=7;main_asset.recipe.matrix[1]=-2;main_asset.recipe.cc1[0]=13;
 main_view.asset=main_view.lease.asset=&main_asset;main_view.input.version=main_view.lease.version=9;
 main_view.c4_address=0x3000;main_view.prefix_address=0x4000;main_view.prefix=prefix;configure_capture(0);
}
static void endpoints(unsigned v){int16_t out[29];out[27]=1234;out[28]=4321;
 assert(af_cp_components406_matrix(&state,out,7,root,0)==101&&out[0]==100+5*(int)v&&out[1]==101-7*(int)v);
 assert(out[27]==1234&&out[28]==4321);
 assert(af_cp_components406_cc1(&state,out,0,root)==102&&out[0]==100+13*(int)v&&out[1]==101);
}
static void packed_private(unsigned v){uint32_t lr=0x123457;unsigned q=query_calls,p=pack_calls;
 assert(af_cp_components406_grid_enter(&state,root,pipe,&lr)==0x230f23&&lr==0x100001);
 assert(query_calls==q+1&&pack_calls==p+1&&word(raw_state+0x184)==0x9000);
 unsigned s=stage[11];assert(word(packed+s*1620)==(v<<22|(v+1)<<12|(v+2)<<2));
 assert(af_cp_components406_grid_leave(&state)==0x123457&&word(raw_state+0x184)==0xa000&&!raw_state[0x188]&&!raw_state[0x189]);
 for(unsigned i=0;i<3;++i)if(i!=s)for(unsigned j=0;j<1620;++j)assert(packed[i*1620+j]==0xa5);
}
static void packed_stock(void){uint32_t lr=0x123457;unsigned q=query_calls,p=pack_calls;
 assert(af_cp_components406_grid_enter(&state,root,pipe,&lr)==0x230f23&&lr==0x100001);
 assert(query_calls==q+1&&pack_calls==p+1&&packed[stage[11]*1620]==12);
 assert(af_cp_components406_grid_leave(&state)==0x123457);
 lr=0x123457;assert(!af_cp_components406_grid_enter(&state,root,pipe,&lr)&&lr==0x123457&&query_calls==q+1);
}
static void copied_generation(void){assert(!publish(1));bind(0);assert(!publish(2));bind(1);memset(&asset,0xa5,sizeof asset);
 configure_capture(0);AfCpCaptureColor406Scope scope=begin(0,AF_OK);endpoints(1);packed_private(1);assert(!af_cp_capture_color406_scope_end(color,&scope));
 configure_capture(1);scope=begin(1,AF_OK);endpoints(2);packed_private(2);assert(!af_cp_capture_color406_scope_end(color,&scope));assert(native_calls==4);
}
static void factory_clear(unsigned fault){assert(!publish(1));bind(0);AfCpCaptureColor406Scope scope=begin(0,AF_OK);packed_private(1);
 if(fault){assert(af_cp_capture_color406_pool_reset(color)==AF_IO);assert(af_cp_capture_color406_scope_end(color,&scope)==AF_IO);
  scope=begin(0,AF_IO);assert(!scope.serial);}
 else{assert(!af_cp_capture_color406_scope_end(color,&scope));assert(!af_cp_capture_color406_a_invalidate(color,object));scope=begin(0,AF_EMPTY);}
 endpoints(0);packed_stock();if(scope.serial)assert(!af_cp_capture_color406_scope_end(color,&scope));
}
static void wrong_source(unsigned kind){assert(!publish(1));bind(0);AfCpCaptureColor406Scope scope=begin(0,AF_OK);int16_t out[27];
 if(kind==0)put(operation+8,object+0x1020);else if(kind==1)put(operation+4,0x3000);else if(kind==2)operation[1]=2;
 else if(kind==3)actual[0].params[0]++;else if(kind==4)thread_id++;else if(kind==5)qualified=0;
 if(kind<6){endpoints(0);uint32_t lr=0x123457;assert(!af_cp_components406_grid_enter(&state,root,pipe,&lr)&&lr==0x123457&&!query_calls);}
 else{for(unsigned profile=54;profile<=55;++profile){assert(af_cp_components406_matrix(&state,out,7,root,profile)==101&&out[0]==100+(int)profile);
  assert(af_cp_components406_cc1(&state,out,profile,root)==102&&out[0]==100+(int)profile);}}
 if(kind==4)thread_id--;assert(!af_cp_capture_color406_scope_end(color,&scope));
}
static void unsupported_stage(unsigned kind){assert(!publish(1));bind(0);AfCpCaptureColor406Scope scope=begin(0,AF_OK);
 if(kind==0)stage[11]=2;else if(kind==1)stage[12]=10;else if(kind==2)calibration[6]=1;else if(kind==3)operation[0x2f]=0;
 else if(kind==4){stage[11]=3;stage[12]=6;}else if(kind==5)calibration[12]=8;
 else if(kind==6)calibration[12]=0;else stage[12]=7;
 uint32_t lr=0x123457;assert(!af_cp_components406_grid_enter(&state,root,pipe,&lr)&&lr==0x123457&&!query_calls&&!pack_calls&&!state.grid.active);
 assert(!af_cp_capture_color406_scope_end(color,&scope));
}
static void query_failure(unsigned q){assert(!publish(1));bind(0);AfCpCaptureColor406Scope scope=begin(0,AF_OK);query_result=q;
 uint32_t lr=0x123457;assert(af_cp_components406_grid_enter(&state,root,pipe,&lr)==0x230f63&&lr==0x100001);
 assert(query_calls==1&&!pack_calls&&word(raw_state+0x184)==0xa000&&context[0x55]==255&&!state.grid_banks[0].private_packed);
 assert(af_cp_components406_grid_leave(&state)==0x123457);assert(!af_cp_capture_color406_scope_end(color,&scope));
}
static void lost_source(void){assert(!publish(1));bind(0);AfCpCaptureColor406Scope scope=begin(0,AF_OK);
 native_loss=1;endpoints(0);native_loss=0;qualified=1;query_loss=1;
 uint32_t lr=0x123457;assert(af_cp_components406_grid_enter(&state,root,pipe,&lr)==0x230f23&&lr==0x100001);
 assert(query_calls==1&&pack_calls==1&&packed[1620]==12&&word(raw_state+0x184)==0xa000&&!state.grid_banks[0].private_packed);
 assert(af_cp_components406_grid_leave(&state)==0x123457);assert(!af_cp_capture_color406_scope_end(color,&scope));
}
static void competition(void){assert(!publish(1));bind(0);AfCpCaptureColor406Scope scope=begin(0,AF_OK);nested=1;packed_private(1);
 assert(query_calls==1&&pack_calls==1);assert(!af_cp_capture_color406_scope_end(color,&scope));
}
static void native_main(void){main_mode=1;operation[1]=0;put(operation+4,0x3000);stage[11]=0;endpoints(1);
 for(unsigned i=0;i<AF_GRID_BYTES;++i)main_asset.recipe.grid[i]=(int8_t)(1+i/405);packed_private(1);
 main_mode=0; /* 原id3任务身份丢失不借Capture结构授权。 */
 uint32_t lr=0x123457;assert(!af_cp_components406_grid_enter(&state,root,pipe,&lr)&&lr==0x123457);
}
static void second_rebuild(void){assert(!publish(1));bind(0);
 AfCpCaptureColor406Scope scope=begin(0,AF_OK);endpoints(1);packed_private(1);
 assert(!af_cp_capture_color406_scope_end(color,&scope));
 /* 普通Capture同一R再由真实719EF6调用进入mode6，仍取同来源cache。 */
 stage[12]=6;scope=begin(0,AF_OK);endpoints(1);packed_private(1);
 assert(!af_cp_capture_color406_scope_end(color,&scope));assert(query_calls==2&&pack_calls==2&&native_calls==4);
}
/* 提供真实基底和原实参的非零增量结果；不把profile当AfPreset.base。 */
static AfCpCaptureColor406Scope base_source(int capture){
 AfCpCaptureColor406Scope scope={0};
 if(capture){assert(!publish(1));bind(0);scope=begin(0,AF_OK);}
 else{main_mode=1;operation[1]=0;put(operation+4,0x3000);main_asset.base=test_base;main_view.input.actual.base=(uint8_t)test_base;if(mono_ready)mono_asset(&main_asset);}
 return scope;
}
static void base_endpoints(unsigned profile,int capture){
 AfCpCaptureColor406Scope scope=base_source(capture);
 if(!test_base&&profile==49)operation[0x34]=3;
 int16_t out[29];out[27]=1234;out[28]=4321;
 assert(af_cp_components406_matrix(&state,out,7,root,profile)==101);
 /* BW/SE原矩阵另走9项构造；27项包装器不得对53误写。 */
 int matrix_delta=profile!=53;
 assert(out[0]==100+(int)profile+(matrix_delta?5:0)&&out[1]==101+(int)profile-(matrix_delta?7:0));
 assert(out[27]==1234&&out[28]==4321);
 assert(af_cp_components406_cc1(&state,out,profile,root)==102);
 assert(out[0]==100+(int)profile+13&&out[1]==101+(int)profile&&native_calls==2);
 if(capture)assert(!af_cp_capture_color406_scope_end(color,&scope));
}
static void rejected_profile(unsigned profile,int capture,int variant){
 AfCpCaptureColor406Scope scope=base_source(capture);operation[0x34]=(uint8_t)variant;
 int16_t out[29];out[27]=1234;out[28]=4321;
 assert(af_cp_components406_matrix(&state,out,7,root,profile)==101&&out[0]==100+(int)profile&&out[1]==101+(int)profile);
 assert(out[27]==1234&&out[28]==4321);operation[0x34]=(uint8_t)variant;
 assert(af_cp_components406_cc1(&state,out,profile,root)==102&&out[0]==100+(int)profile&&out[1]==101+(int)profile&&native_calls==2);
 if(capture)assert(!af_cp_capture_color406_scope_end(color,&scope));
}
static void monochrome9(unsigned kind,int capture){
 mono_ready=1;mono_mode=kind&1u;mono_bad=kind==2||kind==3;
 AfCpCaptureColor406Scope scope=base_source(capture);calibration[0x25]=kind==7?54:53;native_profile_change=kind==8;
 int16_t input[9],out[11];for(unsigned i=0;i<9;++i)input[i]=(int16_t)(100+i);out[9]=1234;out[10]=4321;
 if(kind==4)put(operation+4,0x9999);if(kind==5)native_loss=1;
 unsigned sector=kind==6?16:7;int applied=!mono_bad&&kind<4;
 assert(af_cp_components406_matrix9(&state,out,input,root,sector,matrix9_native)==107&&native_calls==1);
 int value=mono_mode?8:7;
 for(unsigned i=0;i<9;++i){int delta=i==0?value-2:i==1?-value:i==2?2:0;assert(out[i]==input[i]+(applied?delta:0));}
 assert(out[9]==1234&&out[10]==4321);
 if(capture)assert(!af_cp_capture_color406_scope_end(color,&scope));
}
int main(int argc,char **argv){assert(argc==2||argc==4);initialize();unsigned n=(unsigned)atoi(argv[1]);
 if(argc==4){test_base=(unsigned)atoi(argv[2]);unsigned profile=(unsigned)atoi(argv[3]);
  if(n==35||n==36)monochrome9(profile,n==36);else if(n==27||n==28)base_endpoints(profile,n==28);else{native_mode_change=n==33||n==34;rejected_profile(profile,n==30||n==32||n==34,n==31||n==32?3:0);}
  free(color);return 0;}

 if(n==0)copied_generation();else if(n<=2)factory_clear(n-1);else if(n<=9)wrong_source(n-3);
 else if(n<=13)unsupported_stage(n-10);else if(n<=15)query_failure(n==14?0:4);else if(n==16)lost_source();else if(n==17)competition();else if(n==18)native_main();
 else if(n==19)second_rebuild();else if(n<=21){stage[12]=6;factory_clear(n-20);}
 else if(n<=25)unsupported_stage(n-18);else{stage[12]=6;query_failure(0);}
 free(color);return 0;
}
'''


@pytest.fixture(scope='module')
def capture_components_driver(tmp_path_factory):
    directory = tmp_path_factory.mktemp('capture-color-components406')
    source, binary = directory / 'driver.c', directory / 'driver'
    source.write_text(DRIVER)
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                             '-DAF_CP_CAPTURE406=1', '-I' + str(NATIVE), str(source),
                             *[str(NATIVE / name) for name in ('af_cp_components406.c',
                                 'af_cp_capture_color406.c', 'af_joint.c', 'af_color406.c', 'af_slots.c')],
                             '-o', str(binary)], capture_output=True, text=True)
    assert not result.returncode, result.stderr
    return binary


@pytest.mark.parametrize('scenario', range(27), ids=['copied-generations', 'factory-repack', 'fault-repack',
    'wrong-R', 'wrong-C4', 'wrong-domain', 'R-changed', 'wrong-thread', 'no-view', 'factory-profiles',
    'stage2', 'wrong-mode', 'calibration-bypass', 'zero-level', 'query-zero', 'query-four',
    'source-lost-after-native', 'cross-task-CAS', 'main-id3-unchanged', 'mode11-then-mode6',
    'mode6-factory-repack', 'mode6-fault-repack', 'final-stage3', 'native-stage2-mismatch',
    'native-default-stage3-mismatch', 'unsupported-mode7', 'mode6-query-failure'])
def test_capture_color_components(capture_components_driver, scenario):
    result = subprocess.run([str(capture_components_driver), str(scenario)], capture_output=True, text=True, timeout=10)
    assert not result.returncode, result.stderr


@pytest.mark.parametrize('base,profile', [(0,0),(1,6),(2,2),(3,1),(4,42),(5,41),(6,43),(7,44),(8,53),(9,53),(17,54),(18,55),(0,49)],
                         ids=['ST','PT','NT','VV','VV2','FL','IN','SH','BW-CC1','SE-CC1','FL2','FL3','ST-variant49'])
@pytest.mark.parametrize('capture', [False, True], ids=['main','capture'])
def test_existing_base_private_deltas(capture_components_driver, base, profile, capture):
    result = subprocess.run([str(capture_components_driver), '28' if capture else '27', str(base), str(profile)],
                            capture_output=True, text=True, timeout=10)
    assert not result.returncode, result.stderr


@pytest.mark.parametrize('base,profile,variant', [(1,0,False),(17,0,False),(18,54,False),(0,6,False),
    (1,54,False),(17,52,False),(18,56,False),(0,255,False),(0,49,False),(0,0,True)],
    ids=['PT-as-ST','FL2-as-ST','FL3-as-FL2','ST-as-PT','PT-as-FL2','unsupported52','unknown56','unknown255',
         'ST-missing-variant','ST-variant-as-normal'])
@pytest.mark.parametrize('capture', [False, True], ids=['main','capture'])
def test_wrong_profile_keeps_stock_once(capture_components_driver, base, profile, variant, capture):
    scenario = 31 + int(capture) if variant else 29 + int(capture)
    result = subprocess.run([str(capture_components_driver), str(scenario), str(base), str(profile)],
                            capture_output=True, text=True, timeout=10)
    assert not result.returncode, result.stderr


@pytest.mark.parametrize('base', [10,16,19,255])
def test_unknown_main_asset_base_keeps_stock(capture_components_driver, base):
    result = subprocess.run([str(capture_components_driver), '29', str(base), '0'],
                            capture_output=True, text=True, timeout=10)
    assert not result.returncode, result.stderr


@pytest.mark.parametrize('capture', [False, True], ids=['main','capture'])
def test_native_mode_changed_before_delta_keeps_stock(capture_components_driver, capture):
    result = subprocess.run([str(capture_components_driver), '34' if capture else '33', '0', '0'],
                            capture_output=True, text=True, timeout=10)
    assert not result.returncode, result.stderr


@pytest.mark.parametrize('base', [8,9], ids=['BW','SE'])
@pytest.mark.parametrize('capture', [False,True], ids=['main','capture'])
@pytest.mark.parametrize('kind', range(9), ids=['equal18','equal288','ambiguous18','ambiguous288','wrong-root','source-lost','bad-sector','wrong-calibration-profile','profile-changed-in-copy'])
def test_monochrome9_source_and_representability(capture_components_driver, base, capture, kind):
    result = subprocess.run([str(capture_components_driver), '36' if capture else '35', str(base), str(kind)],
                            capture_output=True, text=True, timeout=10)
    assert not result.returncode, result.stderr
