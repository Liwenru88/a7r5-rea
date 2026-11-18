"""原C4、分段队列与worker生命周期的宿主端口验证；不执行目标。"""
from pathlib import Path
import io
import subprocess
import sys
import pytest

NATIVE=Path(__file__).resolve().parents[1]/"native"
DRIVER=r'''
#include "af_cp_jobs406.h"
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdlib.h>
#include <string.h>
static AfCpJobs406 state;
static AfCpNativeBanks406 banks;
static AfCpRuntimeAsset406 asset;
static AfCpOverride406 override_state;
static AfCpInput406 real_input;
static unsigned real_bank;
static AfPreset preset={.base=0,.params={0,0,0,0,0,0,3,0}};
static unsigned char source[2][0xe70],c4source[2][0xc4],destination[3][0xc4],completion[3][20];
static uint32_t ids[3]={2,3,6},idword[3];
static _Thread_local uint32_t taskid,queueid;
static const uint32_t tasks[3]={0x55,0x4b,0x5b},queues[3]={0x172d308,0x16bac50,0x1774d44};
static const uint32_t dsts[3]={0x15787e4,0x1214e98,0x157c278};
static const uint32_t comp[3]={0x15788a8,0x1214f5c,0x157c33c},idaddr[3]={0x15787e0,0x1214f70,0x157c350};
static const uint32_t nativefn[3]={0x8847c1,0x71965b,0x907251},copylr[3]={0x88476b,0x719605,0x9071fb};
static const uint32_t caller[3]={0x884799,0x719633,0x907229},reject[3]={0x8847b9,0x719653,0x907249};
static unsigned copies,borrows,releases,callbacks,invocations,reads,mutate,missing_callback,release_fail,denied,deny_during,task_error,rejected_run;
static unsigned leased[3];
static uint32_t word(const void *v){const unsigned char*p=v;return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put(void *v,uint32_t x){unsigned char*p=v;for(unsigned i=0;i<4;++i)p[i]=(unsigned char)(x>>(8*i));}
static int ix(uint32_t id){for(unsigned i=0;i<3;++i)if(ids[i]==id)return (int)i;return -1;}
static void *map(void *ctx,uint32_t a,size_t n){(void)ctx;
 for(unsigned i=0;i<2;++i){if(a==(i?0x16589e0u:0x1653c68u)&&n==0xe70)return source[i];}
 for(unsigned i=0;i<3;++i){if(a==comp[i]&&n==20)return completion[i];if(a==idaddr[i]&&n==4)return &idword[i];}
 return 0;
}
static int input(void *ctx,uint32_t address,AfCpInput406Token *out){(void)ctx;++reads;memset(out,0,sizeof *out);
 if(real_bank)return af_cp_input406_read(&real_input,address,out);
 out->version=41+(mutate&&reads>1);out->source=address;out->epoch=2;out->origin_snapshot_epoch=2;
 out->slot=7;out->mode=AF_CP_OVERRIDE_USER;out->flags=3;out->native_vd=53;out->actual=preset;return AF_OK;
}
static int borrow(void *ctx,AfCpNativeBanks406 *b,const AfCpInput406Token*t,uint32_t id,AfCpNativeLease406*out){
 (void)ctx;assert(b==&banks&&t->version==41);int j=ix(id);assert(j>=0&&!leased[j]);leased[j]=1;++borrows;
 if(real_bank)return af_cp_native_bank406_borrow_locked(b,t,id,out);
 *out=(AfCpNativeLease406){.worker=id,.bank=0,.generation=1,.version=41,.ticket=100+id,.asset=&asset,.preset=&preset};return AF_OK;
}
static int release(void *ctx,AfCpNativeBanks406*b,const AfCpNativeLease406*t){(void)ctx;assert(b==&banks);int j=ix(t->worker);
 if(release_fail)return AF_IO;
 if(real_bank){int r=af_cp_native_bank406_release(b,t);assert(!r&&j>=0&&leased[j]);leased[j]=0;__atomic_fetch_add(&releases,1,__ATOMIC_SEQ_CST);return r;}
 assert(j>=0&&leased[j]&&t->ticket==100+t->worker);leased[j]=0;++releases;return AF_OK;
}
static void copy(void*ctx,void*d,const void*s,size_t n){(void)ctx;++copies;memcpy(d,s,n);}
static int task(void*ctx,uint32_t*t,uint32_t*q){(void)ctx;*t=taskid;*q=queueid;return task_error?AF_IO:AF_OK;}
static int allowed(void*ctx){(void)ctx;return !denied;}
static void complete(void*ctx,uint32_t id){(void)ctx;assert(ix(id)>=0);__atomic_fetch_add(&callbacks,1,__ATOMIC_SEQ_CST);}
static void invoke(void*ctx,uint32_t id,uint32_t fn){(void)ctx;int j=ix(id);assert(j>=0&&fn==nativefn[j]);__atomic_fetch_add(&invocations,1,__ATOMIC_SEQ_CST);
 if(rejected_run){AfCpJobs406View v,before;memset(&v,0xa5,sizeof v);before=v;assert(state.fault&&state.jobs[j].state==AF_CP_JOB406_PINNED);
 assert(af_cp_jobs406_current_view(&state,id,&v)==AF_IO&&!memcmp(&v,&before,sizeof v));assert(af_cp_jobs406_complete(&state,id,0x2aec303)==AF_IO);assert(callbacks==1&&invocations==1&&!releases&&leased[j]);return;}
 AfCpJobs406View v;int current=af_cp_jobs406_current_view(&state,id,&v);if(!denied){assert(!current);assert(v.asset==(real_bank?&banks.banks[v.lease.bank].asset:&asset)&&v.input.version==41);
 assert(v.prefix_address==word(destination[j])&&v.prefix_address+0xe18==word(destination[j]+8));
 assert(v.prefix[0xa40]==0&&v.prefix[0xd2f]==3&&word(v.prefix+0xdc0)==53);
 assert(!af_cp_jobs406_current(&state,&v));
 AfCpJobs406View altered=v;altered.original_source^=4;assert(af_cp_jobs406_current(&state,&altered)==AF_STALE);}else assert(current==AF_IO);
 if(deny_during)denied=1;
 if(!missing_callback){assert(!af_cp_jobs406_complete(&state,id,0x2aec303));if(denied){AfCpJobs406View out,before;memset(&out,0xa5,sizeof out);before=out;assert(af_cp_jobs406_current_view(&state,id,&out)==AF_IO&&!memcmp(&out,&before,sizeof out));}else assert(!af_cp_jobs406_current(&state,&v));}
}
static void init(void){
 AfCpJobs406Config c={.banks=&banks,.map=map,.read_input=input,.borrow_locked=borrow,.release=release,
 .copy=copy,.allowed=allowed,.task=task,.invoke=invoke,.complete=complete,.completion_address=0x2aec201,.after_native_lr=0x2aec303};
 for(unsigned i=0;i<3;++i){c.worker_address[i]=0x2aec101+i*4;for(unsigned k=0;k<2;++k)c.prefix_address[i][k]=0x3000000+(i*2+k)*0x1000;}
 assert(!af_cp_jobs406_init(&state,&c));assert(af_cp_jobs406_init(&state,&c)==AF_EXISTS);
 assert(af_cp_jobs406_bind_target(&banks)==AF_IO);
 for(unsigned k=0;k<2;++k){memset(source[k],0x7a,sizeof source[k]);put(source[k]+0xa40,0);for(unsigned j=0;j<8;++j){unsigned o[8]={0xa44,0xa46,0xa45,0xa47,0xa48,0xd2e,0xd2f,0xd30};source[k][o[j]]=(unsigned char)preset.params[j];}put(source[k]+0xdc0,53);
 uint32_t a=k?0x16589e0:0x1653c68;memset(c4source[k],0x6b,sizeof c4source[k]);put(c4source[k],a);put(c4source[k]+4,a+0xdc0);put(c4source[k]+8,a+0xe18);}
 if(real_bank){AfPreset lut=preset;lut.kind=1;lut.payload_sha256[0]=1;lut.lut_sha256[0]=2;
 AfJointAsset full={.native_mode=1};full.model_sha256[0]=1;
 for(unsigned i=0;i<129;++i)full.native_seed[i]=full.recipe.gamma[i]=i*123;unsigned char marker=0;
 assert(!af_cp_native_bank406_accept_locked(&banks,&override_state,41,7,&lut,&full,&marker));
 AfCpInput406Write w;assert(!af_cp_input406_snapshot_begin(&real_input,AF_CP_INPUT406_SNAPSHOT,0xdbc,&w));
 assert(!af_cp_input406_snapshot_end(&real_input,&w,41,7,AF_CP_OVERRIDE_USER,&preset,source[0],0xdbc));
 for(unsigned k=0;k<2;++k){uint32_t a=k?0x16589e0:0x1653c68;assert(!af_cp_input406_copy_begin(&real_input,a,AF_CP_INPUT406_SNAPSHOT,0xe70,53,&w));assert(!af_cp_input406_copy_end(&real_input,&w,source[k],0xe70));}}
}
static int capture(unsigned j,unsigned k){put(completion[j],0x60daa5);put(completion[j]+4,0);put(completion[j]+8,0x4bf3e1);put(completion[j]+12,0);put(completion[j]+16,0);idword[j]=ids[j];reads=0;
 return af_cp_jobs406_c4_copy_locked(&state,destination[j],dsts[j],c4source[k],k?0x165d820:0x192b070,0xc4,copylr[j]);
}
static void frame(unsigned char *s,unsigned j){memset(s,0,0xc0);put(s+0x54,0x4e8abf);put(s+0x48,queues[j]);put(s+0x50,0x50000ac);put(s+0xa4,caller[j]);put(s+0x68,0x719e37);put(s+0x70,nativefn[j]);put(s+0xac,0x719e37);put(s+0xb4,nativefn[j]);}
static int path(unsigned j,unsigned k,unsigned split){init();assert(!capture(j,k));assert(copies==1&&borrows==1);assert(word(completion[j]+8)==0x2aec201);
 assert(!memcmp(destination[j]+12,c4source[k]+12,0xc4-12));memset(source[k],0x11,sizeof source[k]);
 unsigned char stack[0xc0],message[28];frame(stack,j);AfCpJobs406QueueFrame f={stack,sizeof stack,0x5000000};
 if(split){assert(!af_cp_jobs406_queue_copy(&state,message,stack+0x68,split,0x5c3864,&f));assert(!af_cp_jobs406_queue_copy(&state,message+split,stack+0x68+split,28-split,0x5c388c,&f));}
 else assert(!af_cp_jobs406_queue_copy(&state,message,stack+0x68,28,0x5c36e4,&f));
 assert(word(message+8)==0x2aec101+j*4&&borrows==1);taskid=tasks[j];queueid=queues[j];assert(!af_cp_jobs406_run(&state,ids[j]));
 assert(invocations==1&&callbacks==1&&releases==1&&!leased[j]&&state.jobs[j].executed==1);
 AfCpJobs406View v,before;memset(&v,0x55,sizeof v);before=v;assert(af_cp_jobs406_current_view(&state,ids[j],&v)!=AF_OK&&!memcmp(&v,&before,sizeof v));return 0;
}
static int failure(unsigned mode){init();unsigned j=1;
 if(mode==6){mutate=1;release_fail=1;assert(capture(j,0)==AF_IO);assert(copies==1&&borrows==1&&!releases&&leased[j]&&state.fault);assert(state.jobs[j].view.lease.asset==&asset);return 0;}
 if(mode==7){put(c4source[0]+8,0x1653c68+0xe70);assert(capture(j,0)==AF_INVALID);assert(copies==1&&!borrows&&!releases&&word(destination[j]+8)==0x1653c68+0xe70);return 0;}
 if(mode==0){mutate=1;assert(capture(j,0)==AF_STALE);assert(copies==1&&borrows==1&&releases==1);assert(word(destination[j])==0x1653c68&&word(completion[j]+8)==0x4bf3e1);return 0;}
 assert(!capture(j,0));
 if(mode==1){assert(!af_cp_jobs406_complete(&state,ids[j],reject[j]));assert(releases==1&&callbacks==1&&!state.jobs[j].executed);return 0;}
 if(mode==2){unsigned char stack[0xc0],message[28];frame(stack,j);put(stack+0x54,0);AfCpJobs406QueueFrame f={stack,sizeof stack,0x5000000};assert(af_cp_jobs406_queue_copy(&state,message,stack+0x68,28,0x5c36e4,&f)!=AF_OK);assert(word(message+8)==nativefn[j]&&copies==2);taskid=tasks[j];queueid=queues[j];assert(!af_cp_jobs406_complete(&state,ids[j],0x4e8c0b));assert(releases==1&&!state.jobs[j].executed);return 0;}
 if(mode==3){assert(af_cp_jobs406_complete(&state,ids[j],0x12345)==AF_IO);assert(state.fault&&leased[j]&&!releases&&callbacks==1);return 0;}
 unsigned char stack[0xc0],message[28];frame(stack,j);AfCpJobs406QueueFrame f={stack,sizeof stack,0x5000000};assert(!af_cp_jobs406_queue_copy(&state,message,stack+0x68,28,0x5c388c,&f));
 if(mode==8||mode==9){taskid=tasks[j];queueid=queues[j];denied=mode==9;deny_during=mode==8;assert(af_cp_jobs406_run(&state,ids[j])==AF_IO);assert(invocations==1&&callbacks==1&&releases==1&&!leased[j]&&!state.jobs[j].executed&&state.jobs[j].state==AF_CP_JOB406_FREE);return 0;}
 if(mode==12){assert(af_cp_jobs406_run(&state,99)==AF_INVALID&&!invocations&&!callbacks&&!releases);return 0;}
 taskid=tasks[j];queueid=mode==4?0:queues[j];missing_callback=mode==5;rejected_run=mode==4||mode==10||mode==11;task_error=mode==10;
 if(mode==11)__atomic_store_n(&state.jobs[j].state,AF_CP_JOB406_CAPTURED,__ATOMIC_SEQ_CST);
 assert(af_cp_jobs406_run(&state,ids[j])==AF_IO);assert(state.fault&&leased[j]&&!releases&&!state.jobs[j].executed);
 if(rejected_run)assert(invocations==1&&callbacks==1);return 0;
}
static unsigned start_workers;
static void *run_worker(void*arg){unsigned i=(unsigned)(uintptr_t)arg;taskid=tasks[i];queueid=queues[i];while(!__atomic_load_n(&start_workers,__ATOMIC_ACQUIRE))sched_yield();assert(!af_cp_jobs406_run(&state,ids[i]));return 0;}
static int parallel(void){init();pthread_t workers[3];for(unsigned i=0;i<3;++i){assert(!capture(i,i%2));unsigned char stack[0xc0],message[28];frame(stack,i);AfCpJobs406QueueFrame f={stack,sizeof stack,0x5000000};assert(!af_cp_jobs406_queue_copy(&state,message,stack+0x68,28,0x5c388c,&f));assert(!pthread_create(&workers[i],0,run_worker,(void*)(uintptr_t)i));}
 __atomic_store_n(&start_workers,1,__ATOMIC_RELEASE);for(unsigned i=0;i<3;++i){assert(!pthread_join(workers[i],0));assert(state.jobs[i].executed==1&&!leased[i]);}assert(releases==3&&callbacks==3&&invocations==3&&!state.fault&&!banks.banks[0].refs&&!banks.banks[1].refs);return 0;}
int main(int argc,char**argv){assert(argc>=3);unsigned mode=(unsigned)atoi(argv[1]);real_bank=mode==2||mode==3;if(mode==3)return parallel();if(mode==0||mode==2){assert(argc==5);return path((unsigned)atoi(argv[2]),(unsigned)atoi(argv[3]),(unsigned)atoi(argv[4]));}return failure((unsigned)atoi(argv[2]));}
'''

@pytest.fixture(scope="module")
def executable(tmp_path_factory):
    folder=tmp_path_factory.mktemp("cp-jobs406");source=folder/"driver.c";binary=folder/"driver";source.write_text(DRIVER)
    sources=("af_cp_jobs406.c","af_cp_native_bank406.c","af_cp_input406.c","af_cp_override406.c","af_cp406_state.c","af_joint.c","af_slots.c")
    r=subprocess.run(["clang","-std=c11","-O2","-Wall","-Wextra","-Werror","-pthread","-I"+str(NATIVE),str(source),*[str(NATIVE/n)for n in sources],"-o",str(binary)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    return binary

@pytest.mark.parametrize("worker,source,split",[(0,0,0),(1,0,4),(2,0,8),(0,1,12),(1,1,24),(2,1,0)])
def test_real_job_prefix_and_complete_queue_copy(executable,worker,source,split):
    r=subprocess.run([str(executable),"0",str(worker),str(source),str(split)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr

@pytest.mark.parametrize("mode",range(13),ids=["source-refresh","queue-reject","bad-frame-native-tail","unknown-lr-pin","wrong-task","missing-completion","uncertain-release-pin","wrong-e70-alias","fault-during-work","fault-before-work","task-api-reject","work-state-mismatch","unknown-identity"])
def test_job_rejection_preserves_stock_copy_and_ownership(executable,mode):
    r=subprocess.run([str(executable),"1",str(mode)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr

def test_actual_input_token_and_native_bank_to_worker_return(executable):
    r=subprocess.run([str(executable),"2","1","1","12"],capture_output=True,text=True)
    assert r.returncode==0,r.stderr

def test_three_original_tasks_hold_independent_prefixes_and_bank_tickets(executable):
    r=subprocess.run([str(executable),"3","0"],capture_output=True,text=True,timeout=10)
    assert r.returncode==0,r.stderr

def test_actual_thumb_jobs_and_fixed_after_native_abi(tmp_path):
    target=tmp_path/"jobs.o";assembly=tmp_path/"jobs-asm.o"
    flags=["clang","--target=armv7a-none-eabi","-mthumb","-march=armv7-a","-mfpu=none","-mfloat-abi=soft","-Oz","-ffreestanding","-fno-builtin","-fstack-usage","-Wall","-Wextra","-Werror"]
    r=subprocess.run([*flags,"-DAF_CP_NATIVE_JOBS406=1","-DAF_CP_CAPTURE_INPUT406=1","-I"+str(NATIVE),"-c",str(NATIVE/"af_cp_jobs406.c"),"-o",str(target)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    undefined=subprocess.run(["nm","-u",str(target)],capture_output=True,text=True)
    assert undefined.returncode==0,undefined.stderr
    assert not any(word in undefined.stdout for word in("__aeabi","__atomic","__sync")),undefined.stdout
    r=subprocess.run([*flags,"-c",str(NATIVE/"af_cp_jobs406.S"),"-o",str(assembly)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    root=NATIVE.parents[2]
    sys.path.insert(0,str(root/"a7r5-desktop/prepared/engine/site"))
    from elftools.elf.elffile import ELFFile
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    elf=ELFFile(io.BytesIO(assembly.read_bytes()));section=elf.get_section_by_name(".text.af_cp_jobs406");raw=section.data()
    symbols={s.name:int(s["st_value"])for s in elf.get_section_by_name(".symtab").iter_symbols()}
    invoke=symbols["af_cp_jobs406_invoke_native"]&~1;after=symbols["af_cp_jobs406_after_native"]
    code=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(raw[invoke:],invoke))
    assert(code[0].mnemonic,code[0].op_str)==("push","{r4, lr}")
    assert(code[1].mnemonic,code[1].op_str)==("blx","r0")
    assert after==(code[1].address+code[1].size)|1
    assert(code[2].mnemonic,code[2].op_str)==("pop","{r4, pc}")
    stack=(target.with_suffix(".su")).read_text()
    assert all(int(line.split("\t")[1])<512 for line in stack.splitlines())

def test_unbound_actual_target_known_wrapper_delegates_stock_once(tmp_path):
    # 仅将真实target C控制流的ARM条件与原callback固定地址适配为宿主端口。
    body=(NATIVE/"af_cp_jobs406.c").read_text()
    branch="#if defined(__arm__) && defined(AF_CP_NATIVE_JOBS406)"
    callback="((void(*)(uint32_t))(uintptr_t)0x4bf3e1u)(id);"
    assert branch in body and callback in body
    body=body.replace(branch,"#if defined(AF_CP_NATIVE_JOBS406)").replace(callback,"host_stock_complete(id);")
    prefix=r'''
#include "af_cp_jobs406.h"
#include <assert.h>
static unsigned native_calls,stock_completions,last_id,prepare_calls;
static void host_stock_complete(uint32_t id){++stock_completions;last_id=id;}
'''
    suffix=r'''
void af_cp_jobs406_worker2(void){af_cp_jobs406_worker_target(2);}
void af_cp_jobs406_worker3(void){af_cp_jobs406_worker_target(3);}
void af_cp_jobs406_worker6(void){af_cp_jobs406_worker_target(6);}
void af_cp_jobs406_completion(void){}
void af_cp_jobs406_after_native(void){}
void af_cp_jobs406_invoke_native(uint32_t fn){
 uint32_t id=fn==0x8847c1?2:fn==0x71965b?3:fn==0x907251?6:0;
 assert(id);assert(prepare_calls==(id==2?1:2));++native_calls;af_cp_jobs406_completion_target(id,0x12345);
}
int af_cp_components406_prepare_target(uint32_t id){assert(id==2||id==3);++prepare_calls;return id==2?AF_OK:AF_IO;}
int main(void){assert(!af_cp_jobs406_target_state());
 const unsigned ids[3]={2,3,6};for(unsigned i=0;i<3;++i){af_cp_jobs406_worker_target(ids[i]);assert(native_calls==i+1&&stock_completions==i+1&&last_id==ids[i]);}
 af_cp_jobs406_worker_target(99);assert(native_calls==3&&stock_completions==3&&!target.magic&&target.fault);return 0;
}
'''
    source=tmp_path/"target_fallback.c";binary=tmp_path/"target_fallback";source.write_text(prefix+body+suffix)
    sources=("af_cp_native_bank406.c","af_cp_input406.c","af_cp_override406.c","af_cp406_state.c","af_joint.c","af_slots.c")
    r=subprocess.run(["clang","-std=c11","-O2","-Wall","-Wextra","-Werror","-DAF_CP_NATIVE_JOBS406=1","-DAF_CP_CAPTURE_INPUT406=1","-I"+str(NATIVE),str(source),*[str(NATIVE/n)for n in sources],"-o",str(binary)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    r=subprocess.run([str(binary)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
