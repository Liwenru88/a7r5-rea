"""两个真实驻留asset银行及原worker票据；仅宿主C执行，不运行设备或ARM。"""
from pathlib import Path
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'native'
DRIVER = r'''
#include "af_cp_native_bank406.h"
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <string.h>
static AfCpNativeBanks406 banks;
static AfCpOverride406 state;
static AfCpInput406 input;
static unsigned char raw[AF_CP_INPUT406_COPY_BYTES],copy[sizeof raw];
static AfPreset preset(void){
 AfPreset p={.base=17,.kind=1,.params={-1,2,-3,4,-5,6,3,8}};
 p.payload_sha256[0]=2;p.lut_sha256[0]=3;return p;
}
static AfJointAsset asset(unsigned n){
 AfJointAsset a={.base=17,.native_mode=1};a.model_sha256[0]=9;
 for(unsigned i=0;i<129;++i)a.recipe.gamma[i]=a.native_seed[i]=i*123;
 a.recipe.grid[0]=(int8_t)n;a.recipe.matrix[0]=(int16_t)n;a.recipe.cc1[0]=(int16_t)-n;
 return a;
}
static AfCpInput406Token token(uint64_t version,unsigned slot){
 AfCpInput406Write w;AfCpInput406Token t;
 AfPreset p=state.preset;unsigned char marker=0;
 assert(!af_cp406_write_state(&p,raw,AF_CP_INPUT406_SNAPSHOT_BYTES,&marker));
 assert(!af_cp_input406_snapshot_begin(&input,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&w));
 assert(!af_cp_input406_snapshot_end(&input,&w,version,slot,AF_CP_OVERRIDE_USER,&p,raw,AF_CP_INPUT406_SNAPSHOT_BYTES));
 assert(!af_cp_input406_copy_begin(&input,AF_CP_INPUT406_COPY_A,AF_CP_INPUT406_SNAPSHOT,sizeof raw,42,&w));
 memcpy(copy,raw,sizeof copy);copy[0xdc0]=42;copy[0xdc1]=copy[0xdc2]=copy[0xdc3]=0;
 assert(!af_cp_input406_copy_end(&input,&w,copy,sizeof copy));
 assert(!af_cp_input406_read(&input,AF_CP_INPUT406_COPY_A,&t));return t;
}
static void accept(uint64_t version,unsigned n){
 AfPreset p=preset();AfJointAsset a=asset(n);unsigned char marker=0;
 assert(!af_cp_native_bank406_accept_locked(&banks,&state,version,7,&p,&a,&marker)&&marker==1);
 assert(state.version==version&&state.mode==AF_CP_OVERRIDE_USER&&!state.preset.kind);
 for(unsigned i=0;i<32;++i)assert(!state.preset.payload_sha256[i]&&!state.preset.lut_sha256[i]);
}
static AfCpNativeLease406 borrow(AfCpInput406Token *t,unsigned worker){
 AfCpNativeLease406 v;
 assert(!af_cp_native_bank406_borrow_locked(&banks,t,worker,&v));
 assert(v.worker==worker&&v.version==t->version&&v.asset&&v.preset&&v.preset->kind==1);
 return v;
}
static int capacity(void){
 _Static_assert(sizeof(AfCpRuntimeAsset406)<sizeof(AfJointAsset),"运行银行不保留两份Gamma曲线");
 assert(af_cp_native_bank406_bytes()==sizeof banks);accept(1,1);
 AfCpInput406Token a=token(1,7);AfCpNativeLease406 first=borrow(&a,2);
 accept(2,2);AfCpInput406Token b=token(2,7);AfCpNativeLease406 second=borrow(&b,3);
 assert(first.bank!=second.bank&&first.asset->recipe.grid[0]==1&&second.asset->recipe.grid[0]==2);
 assert(first.asset->base==17&&first.asset->native_mode==1&&first.asset->model_sha256[0]==9);
 assert(first.asset->recipe.matrix[0]==1&&first.asset->recipe.cc1[0]==-1&&!first.asset->matrix_mode);
 for(unsigned i=0;i<288;++i)assert(!first.asset->sector_matrix[i]&&!second.asset->sector_matrix[i]);
 AfCpNativeBanks406 before=banks;AfCpOverride406 original=state;
 AfPreset p=preset();AfJointAsset value=asset(3);unsigned char marker=0;
 assert(af_cp_native_bank406_accept_locked(&banks,&state,3,7,&p,&value,&marker)==AF_BUSY);
 assert(!memcmp(&before,&banks,sizeof banks)&&!memcmp(&original,&state,sizeof state)&&!marker);
 assert(!af_cp_native_bank406_release(&banks,&first));accept(3,3);
 AfCpInput406Token c=token(3,7);AfCpNativeLease406 third=borrow(&c,2);
 assert(third.bank==first.bank&&third.generation!=first.generation&&third.ticket!=first.ticket);
 assert(af_cp_native_bank406_release(&banks,&first)==AF_STALE);
 assert(third.asset->recipe.grid[0]==3&&second.asset->recipe.grid[0]==2);
 assert(!af_cp_native_bank406_release(&banks,&second)&&!af_cp_native_bank406_release(&banks,&third));
 return 0;
}
static int versions(void){
 AfPreset p=preset();AfJointAsset value=asset(1);unsigned char marker=0;
 assert(!af_cp_native_bank406_accept_locked(&banks,&state,1,7,&p,&value,&marker));
 value.recipe.grid[0]=55;p.params[0]=5; /* 外部对象改变不能改已发布深拷贝。 */
 AfCpInput406Token old=token(1,7);AfCpNativeLease406 one=borrow(&old,2);
 assert(one.asset->recipe.grid[0]==1&&one.preset->params[0]==-1);
 accept(2,2);AfCpInput406Token fresh=token(2,7);AfCpNativeLease406 two=borrow(&fresh,3);
 assert(!memcmp(&old.actual,&fresh.actual,sizeof old.actual)&&one.version!=two.version);
 assert(one.asset->recipe.grid[0]==1&&two.asset->recipe.grid[0]==2);
 AfCpNativeLease406 untouched,copy_out;memset(&untouched,0xa5,sizeof untouched);copy_out=untouched;
 fresh.version=99;
 assert(af_cp_native_bank406_borrow_locked(&banks,&fresh,6,&untouched)==AF_STALE);
 assert(!memcmp(&untouched,&copy_out,sizeof untouched));
 fresh.version=2;fresh.actual.params[0]=1;
 assert(af_cp_native_bank406_borrow_locked(&banks,&fresh,6,&untouched)==AF_STALE);
 fresh.actual.params[0]=-1;fresh.mode=AF_CP_OVERRIDE_NATIVE;
 assert(af_cp_native_bank406_borrow_locked(&banks,&fresh,6,&untouched)==AF_INVALID);
 AfCpNativeBanks406 before=banks;AfCpOverride406 original=state;value=asset(3);p=preset();value.native_mode=0;marker=0;
 assert(af_cp_native_bank406_accept_locked(&banks,&state,3,7,&p,&value,&marker)==AF_JOINT_ASSET_UNSUPPORTED);
 assert(!memcmp(&before,&banks,sizeof banks)&&!memcmp(&original,&state,sizeof state)&&!marker);
 value.native_mode=1;value.recipe.gamma[10]+=1;
 assert(af_cp_native_bank406_accept_locked(&banks,&state,3,7,&p,&value,&marker)==AF_INVALID);
 assert(!memcmp(&before,&banks,sizeof banks)&&!memcmp(&original,&state,sizeof state)&&!marker);
 value=asset(3);
 assert(af_cp_native_bank406_accept_locked(&banks,&state,2,7,&p,&value,&marker)==AF_STALE);
 assert(!memcmp(&before,&banks,sizeof banks)&&!memcmp(&original,&state,sizeof state)&&!marker);
 assert(!af_cp_native_bank406_release(&banks,&one)&&!af_cp_native_bank406_release(&banks,&two));
 banks.generation=UINT64_MAX;value.native_mode=1;
 assert(af_cp_native_bank406_accept_locked(&banks,&state,3,7,&p,&value,&marker)==AF_EXHAUSTED);
 banks.next_lease=UINT64_MAX;fresh=token(2,7);
 assert(af_cp_native_bank406_borrow_locked(&banks,&fresh,6,&untouched)==AF_EXHAUSTED);
 assert(!memcmp(&untouched,&copy_out,sizeof untouched));
 return 0;
}
static int sector(void){
 AfPreset p=preset();AfJointAsset a=asset(0);unsigned char marker=0;
 a.matrix_mode=1;for(unsigned i=0;i<288;++i)a.sector_matrix[i]=(int16_t)(i%31-15);
 assert(!af_cp_native_bank406_accept_locked(&banks,&state,1,7,&p,&a,&marker));
 AfCpInput406Token t=token(1,7);AfCpNativeLease406 lease=borrow(&t,3);
 assert(lease.asset->matrix_mode==1&&!memcmp(lease.asset->sector_matrix,a.sector_matrix,576));
 a.sector_matrix[0]=55;assert(lease.asset->sector_matrix[0]==-15);
 assert(!af_cp_native_bank406_release(&banks,&lease));
 AfCpNativeBanks406 before=banks;AfCpOverride406 original=state;marker=0;
 a.recipe.matrix[0]=1;
 assert(af_cp_native_bank406_accept_locked(&banks,&state,2,7,&p,&a,&marker)==AF_INVALID);
 assert(!memcmp(&before,&banks,sizeof banks)&&!memcmp(&original,&state,sizeof state)&&!marker);
 a.recipe.matrix[0]=0;a.sector_matrix[0]=1025;
 assert(af_cp_native_bank406_accept_locked(&banks,&state,2,7,&p,&a,&marker)==AF_INVALID);
 assert(!memcmp(&before,&banks,sizeof banks)&&!memcmp(&original,&state,sizeof state)&&!marker);
 return 0;
}
static int monochrome(unsigned base,unsigned mode){
 AfPreset p=preset();p.base=(uint8_t)base;AfJointAsset a=asset(0);a.base=base;a.matrix_mode=mode;unsigned char marker=0;
 if(mode){for(unsigned e=0;e<3;++e)for(unsigned s=0;s<16;++s)a.sector_matrix[e*96+s*6]=(int16_t)(s+1);}
 else for(unsigned e=0;e<3;++e)a.recipe.matrix[6*e]=7;
 assert(!af_cp_native_bank406_accept_locked(&banks,&state,1,7,&p,&a,&marker));
 AfCpNativeBanks406 before=banks;AfCpOverride406 old=state;marker=0;
 if(mode)a.sector_matrix[96+7*6]++;else a.recipe.matrix[6]++;
 assert(af_cp_native_bank406_accept_locked(&banks,&state,2,7,&p,&a,&marker)==AF_JOINT_ASSET_UNSUPPORTED);
 assert(!memcmp(&before,&banks,sizeof banks)&&!memcmp(&old,&state,sizeof state)&&!marker);return 0;
}
static unsigned go;
static int result[3];
static AfCpNativeLease406 held[3];
static void *release_worker(void *arg){
 unsigned n=(unsigned)(uintptr_t)arg;
 while(!__atomic_load_n(&go,__ATOMIC_ACQUIRE))sched_yield();
 assert(held[n].asset->recipe.grid[0]==1);
 result[n]=af_cp_native_bank406_release(&banks,&held[n]);return 0;
}
static int threads(void){
 accept(1,1);AfCpInput406Token t=token(1,7);unsigned ids[3]={2,3,6};pthread_t workers[3];
 for(unsigned i=0;i<3;++i)held[i]=borrow(&t,ids[i]);
 AfCpNativeLease406 untouched,before;memset(&untouched,0xa5,sizeof untouched);before=untouched;
 assert(af_cp_native_bank406_borrow_locked(&banks,&t,2,&untouched)==AF_BUSY&&!memcmp(&before,&untouched,sizeof untouched));
 assert(!af_cp_native_bank406_clear_active_locked(&banks)&&!banks.active);
 accept(2,2);AfPreset p=preset();AfJointAsset a=asset(3);unsigned char marker=0;
 assert(af_cp_native_bank406_accept_locked(&banks,&state,3,7,&p,&a,&marker)==AF_BUSY);
 for(unsigned i=0;i<3;++i)assert(!pthread_create(&workers[i],0,release_worker,(void *)(uintptr_t)i));
 __atomic_store_n(&go,1,__ATOMIC_RELEASE);
 for(unsigned i=0;i<3;++i){assert(!pthread_join(workers[i],0)&&result[i]==AF_OK);assert(af_cp_native_bank406_release(&banks,&held[i])==AF_STALE);}
 accept(3,3);t=token(3,7);AfCpNativeLease406 next=borrow(&t,2);
 assert(af_cp_native_bank406_release(&banks,&held[0])==AF_STALE&&next.asset->recipe.grid[0]==3);
 assert(!af_cp_native_bank406_release(&banks,&next));
 assert(!af_cp_native_bank406_clear_active_locked(&banks)&&!banks.active);
 return 0;
}
int main(int argc,char **argv){assert(argc==2);if(!strcmp(argv[1],"mono18-BW"))return monochrome(8,0);if(!strcmp(argv[1],"mono18-SE"))return monochrome(9,0);if(!strcmp(argv[1],"mono288-BW"))return monochrome(8,1);if(!strcmp(argv[1],"mono288-SE"))return monochrome(9,1);return !strcmp(argv[1],"capacity")?capacity():!strcmp(argv[1],"versions")?versions():!strcmp(argv[1],"sector")?sector():threads();}
'''


@pytest.fixture(scope='module')
def bank_driver(tmp_path_factory):
    directory = tmp_path_factory.mktemp('cp-native-banks406')
    source = directory/'driver.c'
    source.write_text(DRIVER)
    binary = directory/'driver'
    sources = ('af_cp_native_bank406.c', 'af_cp_input406.c', 'af_cp_override406.c',
               'af_cp406_state.c', 'af_joint.c', 'af_slots.c')
    built = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread',
                            '-I'+str(NATIVE), str(source), *[str(NATIVE/n) for n in sources],
                            '-o', str(binary)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    return binary


@pytest.mark.parametrize('scenario', ['capacity', 'versions', 'threads', 'sector', 'mono18-BW', 'mono18-SE', 'mono288-BW', 'mono288-SE'])
def test_original_worker_native_asset_banks(bank_driver, scenario):
    run = subprocess.run([str(bank_driver), scenario], capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
