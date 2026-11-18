"""真实独立Capture请求副本的宿主契约；不执行原指令或访问设备。"""
from pathlib import Path
import subprocess

import pytest

NATIVE=Path(__file__).resolve().parents[1]/'native'
DRIVER=r'''
#include "af_cp_input406.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static AfCpInput406 state;
static unsigned copies;
static void original_copy(void *d,const void *s,size_t n){++copies;memcpy(d,s,n);}
static uint8_t live[0xdbc],main_copy[0xdbc],request_copy[0xdbc];
static AfCpOverride406 active={.version=41,.slot=7,.mode=AF_CP_OVERRIDE_USER,
 .preset={.base=0,.params={1,-2,3,4,5,6,3,8}}};
static void transfer(uint32_t destination,void *out){
 assert(!af_cp_override406_snapshot_copy_locked(&active,live,out,sizeof live,&state,destination,original_copy));
}
int main(int argc,char **argv){
 assert(argc==2&&AF_CP_INPUT406_RECORDS==4);
 _Static_assert(AF_CP_INPUT406_REQUEST==0x163f3f0u,"实际请求副本地址");
 live[0xa40]=3;live[0xd2f]=3;
 transfer(AF_CP_INPUT406_SNAPSHOT,main_copy);
 AfCpInput406Token main,request,after;assert(!af_cp_input406_read(&state,AF_CP_INPUT406_SNAPSHOT,&main));
 if(!strcmp(argv[1],"independent")){
  active.version=42;active.preset.params[0]=4;transfer(AF_CP_INPUT406_REQUEST,request_copy);
  assert(copies==2&&!af_cp_input406_read(&state,AF_CP_INPUT406_REQUEST,&request));
  assert(request.source==AF_CP_INPUT406_REQUEST&&request.version==42&&request.actual.params[0]==4);
  assert(request.flags==AF_CP_INPUT406_USER_VERSION&&request.native_vd==0&&request.origin_snapshot_epoch==request.epoch);
  assert(!af_cp_input406_read(&state,AF_CP_INPUT406_SNAPSHOT,&after)&&after.version==main.version&&after.epoch==main.epoch);
  assert(live[0xa40]==3&&live[0xa44]==0); /* 原live与主副本均不被请求投影改写。 */
  assert(request_copy[0xa40]==0&&request_copy[0xa44]==4&&main_copy[0xa44]==1);
 }else if(!strcmp(argv[1],"overwrite")){
  transfer(AF_CP_INPUT406_REQUEST,request_copy);assert(!af_cp_input406_read(&state,AF_CP_INPUT406_REQUEST,&request));
  AfCpInput406Write first,second;
  assert(!af_cp_input406_snapshot_begin(&state,AF_CP_INPUT406_REQUEST,sizeof live,&first));
  assert(af_cp_input406_read(&state,AF_CP_INPUT406_REQUEST,&after)==AF_BUSY);
  assert(af_cp_input406_snapshot_begin(&state,AF_CP_INPUT406_REQUEST,sizeof live,&second)==AF_BUSY);
  assert(af_cp_input406_snapshot_end(&state,&first,41,7,AF_CP_OVERRIDE_USER,&active.preset,request_copy,sizeof live)==AF_STALE);
  active.version=43;transfer(AF_CP_INPUT406_REQUEST,request_copy);
  assert(!af_cp_input406_read(&state,AF_CP_INPUT406_REQUEST,&after)&&after.version==43&&after.epoch!=request.epoch);
  assert(!af_cp_input406_invalidate(&state,AF_CP_INPUT406_REQUEST));
  assert(af_cp_input406_read(&state,AF_CP_INPUT406_REQUEST,&after)==AF_EMPTY);
 }else{
  transfer(AF_CP_INPUT406_REQUEST,request_copy);AfCpInput406Write write;
  assert(af_cp_input406_copy_begin(&state,AF_CP_INPUT406_REQUEST,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_COPY_BYTES,7,&write)==AF_INVALID);
  assert(af_cp_input406_read(&state,AF_CP_INPUT406_REQUEST,&after)==AF_EMPTY);
  active.mode=AF_CP_OVERRIDE_NATIVE;active.slot=0;transfer(AF_CP_INPUT406_REQUEST,request_copy);
  assert(!af_cp_input406_read(&state,AF_CP_INPUT406_REQUEST,&after)&&!after.flags&&!after.slot);
 }
 return 0;
}
'''


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    directory=tmp_path_factory.mktemp('request-snapshot406')
    source=directory/'driver.c';source.write_text(DRIVER);target=directory/'driver'
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-DAF_CP_CAPTURE406=1','-DAF_CP_CAPTURE_INPUT406=1','-I'+str(NATIVE),str(source),
        *[str(NATIVE/name) for name in ('af_cp_input406.c','af_cp_override406.c','af_cp406_state.c','af_slots.c')],
        '-o',str(target)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return target


@pytest.mark.parametrize('scenario',['independent','overwrite','reject'])
def test_capture_request_has_its_own_copy_epoch_and_projection(binary,scenario):
    result=subprocess.run([str(binary),scenario],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
