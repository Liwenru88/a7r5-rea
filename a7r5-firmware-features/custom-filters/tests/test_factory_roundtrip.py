"""完整原厂快照→既有cap HELLO/PRESET→CP整组准备，纯宿主C契约。"""
from pathlib import Path
import subprocess
import pytest

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
PROPOSAL=Path(__file__).resolve().parents[1]/'native'


@pytest.mark.parametrize('overlay', [False, True])
def test_same_factory_complete_restore_uses_slot_zero_and_same_version_stream(tmp_path, overlay):
    src=tmp_path/'roundtrip.c'
    src.write_text(r'''
#include "af_factory406.h"
#include "af_runtime_ap406.h"
#include "af_cp406_state.h"
#include <stdlib.h>
#include <string.h>
_Static_assert(AF_APPLY_ALL==0x1fff,"consumer mask must stay thirteen");
#define CHECK(x) do { if (!(x)) abort(); } while (0)
extern AfHandshake af_cp_handshake;
extern uint32_t af_cp_hs_input_slot;
extern uint64_t af_cp_hs_input_version;
int af_cp_hs_start_once(void);
int af_cp_hs_receive(const void *,uint32_t,size_t);
int af_ap_runtime_next(uint32_t,void **);
int af_ap_runtime_reply(const void *,uint32_t,size_t);
int af_ap_runtime_poll(void);
static unsigned char state[AF_CP406_STATE_BYTES],marker,storage[128],hello_reply[128];
static int pending,failed;static unsigned sends;
#ifdef AF_SNAPSHOT_OVERLAY406
static int installed;static unsigned published,released;
int af_cp_override406_ready(void){return installed;}
int af_cp_override406_prepare(uint64_t version,uint32_t slot,const AfPreset *p){CHECK(slot<=20 && version==published+released+1);++published;return af_cp406_write_state(p,state,sizeof state,&marker);}
int af_cp_override406_release(uint64_t version){CHECK(version==published+released+1);++released;return 0;}
#endif
int af_cp406_locked_prepare(const AfPreset *p) {return af_cp406_write_state(p,state,sizeof(state),&marker);}
static int monotonic(int clock,void *p) {int64_t *v=p;CHECK(clock==1);v[0]=0;v[1]=100000000;return 0;}
void *af_stock_dlsym(void *p,const char *name) {CHECK(!p && !strcmp(name,"clock_gettime"));return (void *)monotonic;}
int af_stock_open(const char *p,int flags,...) {CHECK(!strcmp(p,"/dev/urandom") && !flags);return 61;}
long af_stock_read(int fd,void *p,size_t n) {CHECK(fd==61 && n==8);memset(p,42,n);return (long)n;}
int af_stock_close(int fd) {CHECK(fd==61);return 0;}
int *af_stock_errno(void) {static int e=4;return &e;}
int af_stock_allocate(uint32_t q,void **p,uint32_t n,int wait) {CHECK(q==0x90030001u && n==128 && !wait);*p=storage;return 0;}
void af_stock_source(void *p,uint32_t q) {CHECK(p==storage && q==0x80020002u);}
int af_stock_send(uint32_t q,void *p) {
    AfApplyPacket packet;size_t n=0;CHECK(q==0x90030001u && p==storage);
    CHECK(af_apply_packet_decode(p,128,&packet)==AF_OK && packet.required==AF_APPLY_PROTOCOL_REQUIRED);
    ++sends;if(failed)return -7;
    if(packet.operation==AF_APPLY_HELLO) {
        CHECK(af_hs_server(&af_cp_handshake,p,128,0x80020002u,hello_reply,128,&n)==1 && n==128);pending=1;
    } else CHECK(af_cp_hs_receive(p,0x80020002u,128)==1);
    return 0;
}
int af_stock_receive(uint32_t q,void **p,int wait) {CHECK(q==0x80020002u && wait==50);if(!pending)return -1022;*p=hello_reply;pending=0;return 0;}
int af_stock_usleep(unsigned n) {(void)n;return 0;}
int main(void) {
    const unsigned fields[8]={0xa44,0xa46,0xa45,0xa47,0xa48,0xd2e,0xd2f,0xd30};
    uint32_t bases[18]={0,1,2,3,4,5,6,7,8,9,0,1,2,3,4,5,10,11};
    int32_t arrays[8][18];const int32_t *pointers[8];AfPreset factory,custom={.base=0,.params={-9,9,-8,7,6,5,4,3}};
    unsigned char saved[sizeof(arrays)],saved_bases[sizeof(bases)];void *incoming=0;AfApply bank={0};
    CHECK(af_apply_init(&bank,1,AF_APPLY_PROTOCOL_REQUIRED)==AF_INVALID && !bank.magic);
    CHECK(af_apply_init(&bank,1,AF_APPLY_ALL)==AF_OK && bank.required==AF_APPLY_ALL);
    for(unsigned p=0;p<8;++p) {pointers[p]=arrays[p];for(unsigned i=0;i<18;++i)arrays[p][i]=p==6?2:(int32_t)p+1;}
    memcpy(saved,arrays,sizeof(arrays));memcpy(saved_bases,bases,sizeof(bases));
    CHECK(af_ap_runtime_preset_capabilities()==0);
#ifdef AF_SNAPSHOT_OVERLAY406
    /* 未装快照gate时，不因配对模块已编译就响应新能力HELLO。 */
    CHECK(af_cp_hs_start_once()==AF_BUSY && !af_cp_handshake.state);installed=1;
#endif
    CHECK(af_cp_hs_start_once()==AF_OK);
    CHECK(af_cp_handshake.required==AF_APPLY_PROTOCOL_REQUIRED && af_ap_runtime_next(0x80020002u,&incoming)==1);
    CHECK(af_ap_runtime_reply(incoming,0x90030001u,128)==1);
    CHECK(af_ap_runtime_preset_capabilities()==AF_APPLY_PROTOCOL_REQUIRED);
    /* 同一FL3→C07→同一FL3，原AP数组不改；完整九字段一次PRESET恢复。 */
    CHECK(af_factory406_snapshot(18,bases,pointers,&factory)==AF_OK);
    CHECK(af_ap_runtime_send_preset(0,&factory)==AF_OK && af_cp_hs_input_slot==0 && af_cp_hs_input_version==1);
    CHECK(af_ap_runtime_send_preset(7,&custom)==AF_OK && af_cp_hs_input_slot==7 && af_cp_hs_input_version==2);
    CHECK(state[0xa40]==0 && state[0xa44]==(unsigned char)-9);
    CHECK(af_ap_runtime_send_preset(0,&factory)==AF_OK && af_cp_hs_input_slot==0 && af_cp_hs_input_version==3);
    CHECK(state[0xa40]==20 && marker==1);
    for(unsigned p=0;p<8;++p) CHECK(state[fields[p]]==(unsigned char)factory.params[p]);
    CHECK(!memcmp(saved,arrays,sizeof(arrays)) && !memcmp(saved_bases,bases,sizeof(bases)));
    CHECK(af_ap_runtime_last_attempted_version()==3 && sends==4);
#ifdef AF_SNAPSHOT_OVERLAY406
    CHECK(published==3 && !released);
    CHECK(af_ap_runtime_release_preset()==0 && released==1 && af_cp_hs_input_slot==0 && af_cp_hs_input_version==4);
    CHECK(af_ap_runtime_last_attempted_version()==4 && sends==5);
    /* 同一版本重放不再次退出；新版本的错误来源也不消费版本。 */
    CHECK(af_cp_hs_receive(storage,0x80020002u,128)==1 && released==1);
    CHECK(af_cp_hs_receive(storage,0x80020003u,128)==0 && released==1);
#else
    CHECK(af_ap_runtime_release_preset()==AF_INVALID && af_ap_runtime_last_attempted_version()==3);
#endif
    uint64_t previous=af_cp_hs_input_version;unsigned count=sends;
    failed=1;CHECK(af_ap_runtime_send_preset(7,&custom)==AF_IO && af_ap_runtime_preset_capabilities()==0);
    CHECK(af_cp_hs_input_slot==0 && af_cp_hs_input_version==previous && state[0xa40]==20);
    CHECK(af_ap_runtime_send_preset(7,&custom)==AF_IO && sends==count+1);
    CHECK(af_ap_runtime_release_preset()==AF_IO && sends==count+1);
    CHECK(af_ap_runtime_poll()==AF_INVALID);
    return 0;
}
''')
    binary=tmp_path/'roundtrip'
    sources=[PROPOSAL/n for n in ('af_factory406.c','af_apply_wire.c','af_handshake.c','af_runtime.c','af_runtime_ap406.c','af_hs_cp406.c')]+[NATIVE/n for n in ('af_slots.c','af_cp406_state.c','af_apply.c')]
    cmd=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-DAF_RUNTIME406=1','-DAF_CP_PRESET406=1','-DAF_FACTORY_RESTORE406=1','-I'+str(PROPOSAL),'-I'+str(NATIVE),str(src),*map(str,sources),'-o',str(binary)]
    if overlay:cmd.insert(1, '-DAF_SNAPSHOT_OVERLAY406=1')
    r=subprocess.run(cmd,capture_output=True,text=True);assert r.returncode==0,r.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True);assert run.returncode==0,run.stderr
