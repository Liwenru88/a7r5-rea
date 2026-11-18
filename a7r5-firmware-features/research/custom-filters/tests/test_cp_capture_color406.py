"""独立request到Capture颜色的真实C状态机；端口为宿主替代，不执行目标。"""
from pathlib import Path
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'native'
DRIVER = r'''
#include "af_cp_capture_color406.c"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static AfCpCaptureColor406 state;
static AfCpInput406Token request;
static AfCpRuntimeAsset406 asset;
static AfPreset actual[490];
static unsigned thread_id=22,request_id=7,request_fail,r_fail,r_race;
static uint32_t object=0x71000000u;
static int request_read(void *c,AfCpInput406Token *t,uint32_t *id){
 assert(c==&state&&!state.guard);if(request_fail)return AF_EMPTY;*t=request;*id=request_id;return AF_OK;
}
static int thread_read(void *c,uint32_t *id){assert(c==&state&&!state.guard);*id=thread_id;return AF_OK;}
static int r_read(void *c,uint32_t r,const AfPreset *p){
 assert(c==&state&&!state.guard);if(r_fail)return AF_IO;
 assert(r>=object+0x20&&!((r-object-0x20)%0x1000));
 unsigned i=(r-object-0x20)/0x1000;assert(i<490);
 if(actual[i].base!=p->base)return AF_STALE;
 const unsigned mapped[]={0,4,5,6,7};for(unsigned j=0;j<5;++j)if(actual[i].params[mapped[j]]!=p->params[mapped[j]])return AF_STALE;
 if(r_race){r_race=0;(void)af_cp_capture_color406_pool_reset(&state);}return AF_OK;
}
static void setup(void){
 AfCpCaptureColor406Ports ports={&state,request_read,thread_read,r_read};
 assert(af_cp_capture_color406_bytes()==sizeof state&&sizeof state+54880<65536);
 assert(!af_cp_capture_color406_init(&state,sizeof state,&ports));
 assert(af_cp_capture_color406_init(&state,sizeof state,&ports)==AF_EXISTS);
 assert(af_cp_capture_color406_ready(&state));
}
static void prepare(unsigned v){
 memset(&request,0,sizeof request);request.version=v;request.source=AF_CP_CAPTURE_COLOR406_REQUEST;
 request.epoch=request.origin_snapshot_epoch=v*2;request.slot=7;request.mode=AF_CP_OVERRIDE_USER;
 request.flags=AF_CP_INPUT406_USER_VERSION;request.actual.params[6]=3;
 memset(&asset,0,sizeof asset);asset.native_mode=1;asset.model_sha256[0]=8;
 asset.recipe.matrix[0]=(int16_t)v;asset.recipe.cc1[0]=(int16_t)-(int)v;asset.recipe.grid[7]=(int8_t)v;
}
static int publish(unsigned v){assert(!af_cp_capture_color406_request_invalidate(&state));prepare(v);return af_cp_capture_color406_request_publish(&state,&request,request_id,&asset);}
static void copy_r(unsigned index){
 AfCpCaptureColor406Write write;
 assert(!af_cp_capture_color406_r_begin(&state,object+index*0x1000,&write));
 actual[index]=request.actual;assert(!af_cp_capture_color406_r_end(&state,&write));
}
static AfCpCaptureColor406View begin(unsigned index,AfCpCaptureColor406Scope *scope){
 AfCpCaptureColor406View view;assert(!af_cp_capture_color406_scope_begin(&state,object+index*0x1000+0x20,scope));
 assert(!af_cp_capture_color406_view(&state,&view));return view;
}
static void success(void){
 assert(!af_cp_capture_color406_a_birth(&state,object));AfCpCaptureColor406Scope scope;
 assert(af_cp_capture_color406_scope_begin(&state,object+0x20,&scope)==AF_EMPTY&&scope.serial);
 assert(!af_cp_capture_color406_scope_end(&state,&scope));assert(!publish(1));copy_r(0);
 memset(&asset,0xa5,sizeof asset); /* 只借原请求copy，cache必须是独立深副本。 */
 AfCpCaptureColor406View view=begin(0,&scope);assert(view.version==1&&view.slot==7);
 assert(view.asset->recipe.matrix[0]==1&&view.asset->recipe.cc1[0]==-1&&view.asset->recipe.grid[7]==1);
 assert(!af_cp_capture_color406_current(&state,&view));
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
 assert(af_cp_capture_color406_current(&state,&view)==AF_STALE);
 assert(!af_cp_capture_color406_a_release(&state,object));
 assert(!af_cp_capture_color406_a_birth(&state,object));
 assert(af_cp_capture_color406_scope_begin(&state,object+0x20,&scope)==AF_EMPTY);
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
}
static void cache_full(void){
 assert(!af_cp_capture_color406_a_birth(&state,object));assert(!af_cp_capture_color406_a_birth(&state,object+0x1000));
 assert(!publish(1));copy_r(0);assert(!publish(2));copy_r(1);assert(publish(3)==AF_BUSY);
 AfCpCaptureColor406Scope scope;AfCpCaptureColor406View old=begin(0,&scope);assert(old.version==1);
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
 assert(!af_cp_capture_color406_a_release(&state,object));
 assert(!af_cp_capture_color406_request_publish(&state,&request,request_id,&asset));
 assert(!af_cp_capture_color406_a_birth(&state,object));copy_r(0);
 AfCpCaptureColor406View fresh=begin(0,&scope);assert(fresh.version==3);
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
 old=begin(1,&scope);assert(old.version==2);assert(!af_cp_capture_color406_scope_end(&state,&scope));
}
static void r_failure(unsigned change){
 assert(!af_cp_capture_color406_a_birth(&state,object));assert(!publish(1));copy_r(0);
 AfCpCaptureColor406Write write;assert(!af_cp_capture_color406_r_begin(&state,object,&write));
 actual[0]=request.actual;
 if(change==0)actual[0].params[0]=1;
 else if(change==1){assert(!publish(2));actual[0]=request.actual;}
 else if(change==2){request_id++;}
 else if(change==3)r_fail=1;
 else{assert(!af_cp_capture_color406_request_invalidate(&state));request.epoch+=2;request.origin_snapshot_epoch+=2;assert(!af_cp_capture_color406_request_publish(&state,&request,request_id,&asset));}
 assert(af_cp_capture_color406_r_end(&state,&write)<0);r_fail=0;
 AfCpCaptureColor406Scope scope;assert(af_cp_capture_color406_scope_begin(&state,object+0x20,&scope)==AF_EMPTY);
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
 assert(af_cp_capture_color406_ready(&state));
}
static void no_source(void){
 assert(!af_cp_capture_color406_a_birth(&state,object));assert(!publish(1));copy_r(0);
 request_fail=1;AfCpCaptureColor406Write write;memset(&write,0xa5,sizeof write);AfCpCaptureColor406Write before=write;
 assert(af_cp_capture_color406_r_begin(&state,object,&write)==AF_EMPTY&&!memcmp(&before,&write,sizeof write));
 request_fail=0;AfCpCaptureColor406Scope scope;assert(af_cp_capture_color406_scope_begin(&state,object+0x20,&scope)==AF_EMPTY);
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
}
static void reentry(unsigned kind){
 assert(!af_cp_capture_color406_a_birth(&state,object));assert(!publish(1));copy_r(0);
 AfCpCaptureColor406Scope a,b;AfCpCaptureColor406Write w;
 if(kind==0){assert(!af_cp_capture_color406_scope_begin(&state,object+0x20,&a));assert(af_cp_capture_color406_scope_begin(&state,0,&b)==AF_BUSY);}
 else if(kind==1){assert(!af_cp_capture_color406_r_begin(&state,object,&w));assert(af_cp_capture_color406_r_begin(&state,object,&w)==AF_BUSY);}
 else if(kind==2){assert(!af_cp_capture_color406_scope_begin(&state,object+0x20,&a));r_race=1;AfCpCaptureColor406View v;memset(&v,0xa5,sizeof v);AfCpCaptureColor406View before=v;assert(af_cp_capture_color406_view(&state,&v)<0&&!memcmp(&before,&v,sizeof v));}
 else {state.guard=1;assert(af_cp_capture_color406_request_invalidate(&state)==AF_BUSY);state.guard=0;}
 assert(!af_cp_capture_color406_ready(&state));
}
static void reset(void){
 assert(!af_cp_capture_color406_a_birth(&state,object));assert(!publish(1));copy_r(0);
 uint32_t prior=state.links[0].mark;assert(!af_cp_capture_color406_pool_reset(&state));
 assert(!state.banks[0].refs&&!state.banks[1].refs&&af_cp_capture_color406_ready(&state));
 assert(!af_cp_capture_color406_a_birth(&state,object)&&state.links[0].mark!=prior);
 AfCpCaptureColor406Scope scope;assert(af_cp_capture_color406_scope_begin(&state,object+0x20,&scope)==AF_EMPTY);
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
}
static void bad_publish(void){
 assert(!af_cp_capture_color406_request_invalidate(&state));prepare(1);asset.recipe.grid[0]=64;
 assert(af_cp_capture_color406_request_publish(&state,&request,request_id,&asset)==AF_INVALID&&!state.request_ready);
 prepare(1);request.source=AF_CP_INPUT406_COPY_A;
 assert(af_cp_capture_color406_request_publish(&state,&request,request_id,&asset)==AF_INVALID&&!state.request_ready);
}
static void collision(void){
 assert(!publish(1));assert(!af_cp_capture_color406_request_invalidate(&state));
 request.epoch+=2;request.origin_snapshot_epoch+=2;asset.recipe.grid[7]++;
 assert(af_cp_capture_color406_request_publish(&state,&request,request_id,&asset)==AF_STALE);
 assert(!af_cp_capture_color406_ready(&state));
}
static void capacity(void){
 for(unsigned i=0;i<490;++i)assert(!af_cp_capture_color406_a_birth(&state,object+i*0x1000));
 assert(af_cp_capture_color406_a_birth(&state,object+490*0x1000)==AF_EXHAUSTED);
 assert(!af_cp_capture_color406_a_release(&state,object));
 assert(!af_cp_capture_color406_a_birth(&state,object));state.next=LIMIT;
 assert(af_cp_capture_color406_request_invalidate(&state)==AF_EXHAUSTED&&!af_cp_capture_color406_ready(&state));
}
static void r_subset(void){
 assert(!af_cp_capture_color406_a_birth(&state,object));assert(!publish(1));copy_r(0);
 /* 原R没有复制的八值不可从空字段补造；真实端口只核实际子集。 */
 actual[0].params[1]=7;actual[0].params[2]=-7;actual[0].params[3]=3;
 AfCpCaptureColor406Scope scope;AfCpCaptureColor406View view=begin(0,&scope);
 thread_id++;assert(af_cp_capture_color406_current(&state,&view)==AF_STALE);thread_id--;
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
}
static void release_active(void){
 assert(!af_cp_capture_color406_a_birth(&state,object));assert(!publish(1));copy_r(0);
 AfCpCaptureColor406Scope scope;AfCpCaptureColor406View v=begin(0,&scope);
 assert(!af_cp_capture_color406_a_release(&state,object));
 assert(af_cp_capture_color406_current(&state,&v)==AF_IO&&!af_cp_capture_color406_ready(&state));
 assert(af_cp_capture_color406_scope_end(&state,&scope)==AF_IO);
}
static void reset_pending(void){
 assert(!af_cp_capture_color406_a_birth(&state,object));assert(!publish(1));
 AfCpCaptureColor406Write w;assert(!af_cp_capture_color406_r_begin(&state,object,&w));
 assert(af_cp_capture_color406_pool_reset(&state)==AF_IO&&!af_cp_capture_color406_ready(&state));
 assert(af_cp_capture_color406_r_end(&state,&w)==AF_IO);
}
static void invalidate_alive(unsigned active){
 assert(!af_cp_capture_color406_a_birth(&state,object));assert(!publish(1));copy_r(0);
 AfCpCaptureColor406Scope scope;uint32_t mark=state.links[0].mark;
 if(active){AfCpCaptureColor406View v=begin(0,&scope);(void)v;
  assert(af_cp_capture_color406_a_invalidate(&state,object)==AF_IO&&!af_cp_capture_color406_ready(&state));
  assert(af_cp_capture_color406_scope_end(&state,&scope)==AF_IO);return;}
 assert(!af_cp_capture_color406_a_invalidate(&state,object));
 assert(state.links[0].a==object&&state.links[0].mark!=mark);
 assert(af_cp_capture_color406_scope_begin(&state,object+0x20,&scope)==AF_EMPTY);
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
 copy_r(0);AfCpCaptureColor406View v=begin(0,&scope);assert(v.version==1);
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
}
static void begin_failure_stays_unqualified(void){
 assert(!af_cp_capture_color406_a_birth(&state,object));assert(!publish(1));copy_r(0);
 AfCpCaptureColor406Scope scope;AfCpCaptureColor406View view;
 r_fail=1;assert(af_cp_capture_color406_scope_begin(&state,object+0x20,&scope)==AF_IO&&scope.serial);
 r_fail=0;assert(af_cp_capture_color406_view(&state,&view)==AF_EMPTY);
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
}
static void stock_observer(void){
 AfCpCaptureColor406Scope scope,seen,before;memset(&seen,0xa5,sizeof seen);before=seen;
 assert(af_cp_capture_color406_scope_observe(&state,object+0x20,&seen)==AF_EMPTY&&!memcmp(&before,&seen,sizeof seen));
 assert(af_cp_capture_color406_scope_begin(&state,object+0x20,&scope)==AF_EMPTY&&scope.serial);
 assert(!af_cp_capture_color406_scope_observe(&state,object+0x20,&seen)&&seen.serial==scope.serial);
 thread_id++;assert(af_cp_capture_color406_scope_observe(&state,object+0x20,&seen)==AF_STALE);thread_id--;
 assert(!af_cp_capture_color406_scope_end(&state,&scope));
 assert(af_cp_capture_color406_scope_begin(&state,object+0x20,&scope)==AF_EMPTY);
 assert(af_cp_capture_color406_pool_reset(&state)==AF_IO);
 assert(af_cp_capture_color406_scope_observe(&state,object+0x20,&seen)==AF_IO);
 (void)af_cp_capture_color406_scope_end(&state,&scope);
}
int main(int argc,char **argv){assert(argc==2);setup();unsigned n=(unsigned)atoi(argv[1]);
 if(n==0)success();else if(n==1)cache_full();else if(n>=2&&n<=6)r_failure(n-2);
 else if(n==7)no_source();else if(n>=8&&n<=11)reentry(n-8);else if(n==12)reset();else if(n==13)bad_publish();else if(n==14)collision();else if(n==15)capacity();else if(n==16)r_subset();else if(n==17)release_active();else if(n==18)reset_pending();else if(n<=20)invalidate_alive(n-19);else if(n==21)begin_failure_stays_unqualified();else stock_observer();
 return 0;
}
'''


@pytest.fixture(scope='module')
def driver(tmp_path_factory):
    directory = tmp_path_factory.mktemp('capture-color406')
    source, binary = directory / 'driver.c', directory / 'driver'
    source.write_text(DRIVER)
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                             '-I' + str(NATIVE), str(source), str(NATIVE / 'af_slots.c'),
                             '-o', str(binary)], capture_output=True, text=True)
    assert not result.returncode, result.stderr
    return binary


@pytest.mark.parametrize('scenario', range(23), ids=['success','cache-full','R-mismatch','request-version-change',
    'request-id-change','R-port-failure','same-version-new-request','missing-source','scope-reentry',
    'R-reentry','reset-during-read','guard-contention','pool-reset','invalid-publish',
    'version-collision','capacity-wrap','R-real-subset','release-active','reset-pending','invalidate-rebind-alive','invalidate-active','failed-begin-no-regrant','stock-observer'])
def test_capture_color_request_lifetime_failure_and_cpu_scope(driver, scenario):
    result = subprocess.run([str(driver), str(scenario)], capture_output=True, text=True, timeout=10)
    assert not result.returncode, result.stderr
