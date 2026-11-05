"""真实request目标的宿主端口集成；不执行ARM、ISP或设备操作。"""
import subprocess

import pytest

from test_cp_native_binding406 import DRIVER, compile_native_binding


REQUEST_DRIVER = r'''
extern AfCpInput406 *test_inputs(void);
void af_cp_override406_request_copy_target(void *,const void *,size_t);
static unsigned char live_before[AF_CP_INPUT406_SNAPSHOT_BYTES];
static void live_init(void){
 memset(test_live,0xa5,sizeof test_live);unsigned char marker=0;
 AfPreset stock={.base=0,.params={1,0,0,0,0,0,3,0}};
 assert(!af_cp406_write_state(&stock,test_live,sizeof test_live,&marker));
 memcpy(live_before,test_live,sizeof live_before);memset(test_request,0x6c,sizeof test_request);
}
static void invoke(const void *source,size_t bytes){
 unsigned before=copies;af_cp_override406_request_copy_target(test_request,source,bytes);
 assert(copies==before+1&&!memcmp(test_live,live_before,sizeof test_live));
}
static void projected(unsigned version){
 unsigned char expected[AF_CP_INPUT406_SNAPSHOT_BYTES],marker=0;
 memcpy(expected,live_before,sizeof expected);
 assert(!af_cp406_write_state(&test_active()->preset,expected,sizeof expected,&marker));
 assert(!memcmp(test_request,expected,sizeof expected)&&request_cached);
 AfCpInput406Token token={0};assert(!af_cp_override406_read_input(AF_CP_INPUT406_REQUEST,&token));
 assert(token.version==version&&token.source==AF_CP_INPUT406_REQUEST&&token.slot==7&&
  token.mode==AF_CP_OVERRIDE_USER&&token.flags==AF_CP_INPUT406_USER_VERSION&&!token.native_vd&&
  token.epoch&&!(token.epoch&1u)&&token.origin_snapshot_epoch==token.epoch);
 assert(token.version==request_token.version&&token.epoch==request_token.epoch&&
  !memcmp(&token.actual,&test_active()->preset,sizeof token.actual));
 AfJointAsset source=current_asset(version);AfCpRuntimeAsset406 expected_asset;
 af_cp_runtime_asset406_copy_validated(&expected_asset,&source);
 assert(!memcmp(&expected_asset,&request_asset,sizeof expected_asset));
}
static void empty_request(void){
 AfCpInput406Token token={0};assert(!request_cached);
 assert(af_cp_override406_read_input(AF_CP_INPUT406_REQUEST,&token)==AF_EMPTY);
}
int main(int argc,char **argv){
 assert(argc==2);setup();start();completed(1);live_init();
 if(!strcmp(argv[1],"independent")){
  /* 真实input公共API建立既有canonical记录；request不得夺用其epoch。 */
  AfCpInput406Write write;AfCpInput406Token canonical;unsigned char snapshot[AF_CP_INPUT406_SNAPSHOT_BYTES],marker=0;
  memcpy(snapshot,test_live,sizeof snapshot);
  assert(!af_cp406_write_state(&test_active()->preset,snapshot,sizeof snapshot,&marker));
  assert(!af_cp_input406_snapshot_begin(test_inputs(),AF_CP_INPUT406_SNAPSHOT,sizeof snapshot,&write));
  assert(!af_cp_input406_snapshot_end(test_inputs(),&write,1,7,AF_CP_OVERRIDE_USER,&test_active()->preset,snapshot,sizeof snapshot));
  assert(!af_cp_override406_read_input(AF_CP_INPUT406_SNAPSHOT,&canonical));
  invoke(test_live,sizeof test_live);projected(1);uint32_t first=request_token.epoch;
  invoke(test_live,sizeof test_live);projected(1);assert(request_token.epoch>first);
  AfCpInput406Token after;assert(!af_cp_override406_read_input(AF_CP_INPUT406_SNAPSHOT,&after));
  assert(after.version==canonical.version&&after.epoch==canonical.epoch&&after.source==canonical.source&&
   after.origin_snapshot_epoch==canonical.origin_snapshot_epoch&&!memcmp(&after.actual,&canonical.actual,sizeof after.actual));
  assert(request_publishes==2);return 0;
 }
 if(!strcmp(argv[1],"versions")){
  sector_mode=1;completed(2);invoke(test_live,sizeof test_live);projected(2);
  AfCpInput406Token first=request_token;AfCpRuntimeAsset406 old=request_asset;
  completed(3);invoke(test_live,sizeof test_live);projected(3);
  assert(!memcmp(&first.actual,&request_token.actual,sizeof first.actual)&&
   first.version!=request_token.version&&first.epoch<request_token.epoch);
  assert(memcmp(&old,&request_asset,sizeof old)&&request_publishes==2);return 0;
 }
 invoke(test_live,sizeof test_live);projected(1);unsigned publications=request_publishes,attempts=tries;
 if(!strcmp(argv[1],"busy")){
  try_busy=1;invoke(test_live,sizeof test_live);empty_request();
  assert(tries==attempts+1&&request_publishes==publications&&!lock_held&&
   !memcmp(test_request,test_live,sizeof test_live)&&!af_cp_override406_faulted());
  try_busy=0;invoke(test_live,sizeof test_live);projected(1);return 0;
 }
 if(!strcmp(argv[1],"source")||!strcmp(argv[1],"size")){
  unsigned char other[sizeof test_live];memcpy(other,test_live,sizeof other);other[3]^=0x31;
  size_t n=!strcmp(argv[1],"size")?sizeof test_live-1:sizeof test_live;
  const void *source=!strcmp(argv[1],"source")?other:test_live;
  memset(test_request,0x6c,sizeof test_request);invoke(source,n);empty_request();
  assert(!memcmp(test_request,source,n)&&tries==attempts&&request_publishes==publications);
  if(n<sizeof test_live)assert(test_request[n]==0x6c);
  assert(!af_cp_override406_faulted());invoke(test_live,sizeof test_live);projected(1);return 0;
 }
 if(!strcmp(argv[1],"cache-busy")||!strcmp(argv[1],"cache-fail")){
  request_result=!strcmp(argv[1],"cache-busy")?AF_BUSY:AF_IO;
  invoke(test_live,sizeof test_live);empty_request();
  assert(request_publishes==publications+1&&!lock_held&&!af_cp_override406_faulted());
  request_result=AF_OK;invoke(test_live,sizeof test_live);projected(1);return 0;
 }
 if(!strcmp(argv[1],"unlock")){
  fail_unlock=1;invoke(test_live,sizeof test_live);
  AfCpInput406Token token;assert(lock_held&&af_cp_override406_faulted()&&!request_cached&&
   af_cp_override406_read_input(AF_CP_INPUT406_REQUEST,&token)==AF_IO);
  attempts=tries;publications=request_publishes;invoke(test_live,sizeof test_live);
  assert(tries==attempts&&request_publishes==publications&&!request_cached&&
   !memcmp(test_request,test_live,sizeof test_live));
  af_cp_native406_receive_finished();assert(test_core_stage()==3&&af_cp_hs_input_fault);return 0;
 }
 assert(!strcmp(argv[1],"factory"));
 assert(!af_cp_override406_release(2)&&!af_cp_native406_banks()->active);
 invoke(test_live,sizeof test_live);assert(!request_cached&&!memcmp(test_request,test_live,sizeof test_live));
 AfCpInput406Token token;assert(!af_cp_override406_read_input(AF_CP_INPUT406_REQUEST,&token));
 assert(token.mode==AF_CP_OVERRIDE_NATIVE&&token.version==2&&!token.slot&&!token.flags&&!token.native_vd);
 assert(request_publishes==publications&&af_cp_native406_ready()&&!af_cp_override406_faulted());return 0;
}
'''


@pytest.fixture(scope='module')
def request_driver(tmp_path_factory):
    # 复用真实启动/握手/银行/消息fixture，仅去掉其旧main。
    driver = DRIVER.split('int main(int argc,char **argv)')[0]+REQUEST_DRIVER
    return compile_native_binding(tmp_path_factory.mktemp('cp-request-target406'), True, driver=driver)


@pytest.mark.parametrize('scenario', ['independent', 'versions', 'busy', 'source', 'size',
                                      'cache-busy', 'cache-fail', 'unlock', 'factory'])
def test_actual_request_projection_and_cache_publication(request_driver, scenario):
    run = subprocess.run([str(request_driver), scenario], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
