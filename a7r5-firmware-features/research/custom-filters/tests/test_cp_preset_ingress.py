"""既有PRESET在CP消息入口的准入；锁/原快照另由原ARM指令联验。"""
from pathlib import Path
import subprocess

ROOT=next(p for p in Path(__file__).resolve().parents
          if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
PROPOSAL=Path(__file__).resolve().parents[1]/'native'


def test_existing_packet_prepare_and_fail_closed(tmp_path):
    source=tmp_path/'contract.c'
    source.write_text(r'''
#include "af_handshake.h"
#include "af_cp406_state.h"
#include <string.h>
extern AfHandshake af_cp_handshake;
extern uint64_t af_cp_hs_input_version;
extern uint32_t af_cp_hs_input_slot,af_cp_hs_input_fault;
extern int af_cp_hs_last_prepare;
int af_cp_hs_configure(uint32_t);
int af_cp_hs_receive(const void *,uint32_t,size_t);
static unsigned calls;
static int failure;
static unsigned char state[AF_CP406_STATE_BYTES],marker;
int af_cp406_locked_prepare(const AfPreset *p) {
    ++calls;
    return failure?failure:af_cp406_write_state(p,state,sizeof(state),&marker);
}
#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)
static int encode(AfApplyPacket *p,unsigned char out[128]) {
    size_t n=0;return af_apply_packet_encode(p,out,128,&n) || n!=128;
}
int main(void) {
    AfApplyPacket packet={0};unsigned char wire[128],reply[128],before[sizeof(state)];size_t n;
    packet.operation=AF_APPLY_HELLO;packet.session=71;packet.required=0x1fff;
    CHECK(!encode(&packet,wire));CHECK(af_cp_hs_configure(0x1fff)==0);
    CHECK(af_cp_hs_input_version==0 && af_cp_hs_last_prepare==AF_EMPTY);
    /* 仅复用原HELLO状态函数，不在宿主调用固件固定发送地址。 */
    CHECK(af_hs_server(&af_cp_handshake,wire,128,0x80020002u,reply,128,&n)==1 && n==128);
    packet.operation=AF_APPLY_PRESET;packet.version=1;packet.slot=7;packet.preset.base=18;
    {int8_t values[8]={-3,4,-5,2,6,7,3,8};memcpy(packet.preset.params,values,8);}
    CHECK(!encode(&packet,wire));
    CHECK(af_cp_hs_receive(wire,0x80020002u,128)==1 && calls==1);
    CHECK(af_cp_hs_last_prepare==AF_OK && af_cp_hs_input_version==1 && af_cp_hs_input_slot==7);
    CHECK(state[0xa40]==20 && state[0xa44]==(unsigned char)-3 && state[0xd30]==8 && marker==1);
    memcpy(before,state,sizeof(state));marker=0;
    CHECK(af_cp_hs_receive(wire,0x80020002u,128)==1 && calls==1 && af_cp_hs_last_prepare==AF_STALE);
    wire[60]^=1;CHECK(af_cp_hs_receive(wire,0x80020002u,128)==1 && calls==1 && af_cp_hs_last_prepare==AF_INVALID);
    packet.version=2;packet.session=72;CHECK(!encode(&packet,wire));
    CHECK(af_cp_hs_receive(wire,0x80020002u,128)==1 && calls==1 && af_cp_hs_last_prepare==AF_INVALID);
    packet.session=71;CHECK(!encode(&packet,wire));
    CHECK(af_cp_hs_receive(wire,0x123,128)==0 && calls==1);
    CHECK(!marker && !memcmp(before,state,sizeof(state)) && af_cp_hs_input_version==1);
    failure=AF_IO;CHECK(af_cp_hs_receive(wire,0x80020002u,128)==1 && calls==2);
    CHECK(af_cp_hs_last_prepare==AF_IO && af_cp_hs_input_fault==1 && af_cp_hs_input_version==1);
    failure=0;packet.version=3;CHECK(!encode(&packet,wire));
    CHECK(af_cp_hs_receive(wire,0x80020002u,128)==1 && calls==2 && !memcmp(before,state,sizeof(state)));
    {unsigned char original[12]={5,0,0x2f,0x40};CHECK(af_cp_hs_receive(original,0x80020002u,12)==0);}
    return 0;
}
''')
    binary=tmp_path/'contract'
    cmd=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-DAF_CP_PRESET406=1',
         '-I'+str(NATIVE),str(source),str(PROPOSAL/'af_hs_cp406.c'),
         *[str(NATIVE/name) for name in ('af_slots.c','af_apply_wire.c','af_handshake.c','af_cp406_state.c')],'-o',str(binary)]
    result=subprocess.run(cmd,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.returncode


def test_busy_start_recovers_on_native_ingress_without_resetting_session(tmp_path):
    source=tmp_path/'startup.c'
    source.write_text(r'''
#include "af_handshake.h"
#include "af_cp_override406.h"
extern AfHandshake af_cp_handshake;
extern uint64_t af_cp_hs_input_version;
int af_cp_hs_start_once(void);
int af_cp_hs_configure(uint32_t);
int af_cp_hs_receive(const void *,uint32_t,size_t);
static int ready,checks,prepared;
int af_cp_override406_ready(void){checks++;return ready;}
int af_cp_override406_prepare(uint64_t version,uint32_t slot,const AfPreset *p){if(version!=4)return AF_STALE;(void)p;prepared++;return slot==7?AF_OK:AF_INVALID;}
int af_cp_override406_release(uint64_t version){return version?AF_OK:AF_INVALID;}
int af_cp406_locked_prepare(const AfPreset *p){(void)p;return AF_IO;}
#define CHECK(x) do{if(!(x))return __LINE__;}while(0)
int main(void){
 unsigned char ordinary[12]={5,0,0x2f,0x40},wire[128],reply[128];size_t n=0;
 CHECK(af_cp_hs_start_once()==AF_BUSY && !af_cp_handshake.state && checks==1);
 CHECK(af_cp_hs_receive(ordinary,0x80020002u,sizeof ordinary)==0 && !af_cp_handshake.state);
 ready=1;
 CHECK(af_cp_hs_receive(ordinary,0x80020002u,sizeof ordinary)==0);
 CHECK(af_cp_handshake.state && af_cp_handshake.required==AF_APPLY_PROTOCOL_REQUIRED);
 AfApplyPacket p={0};p.operation=AF_APPLY_HELLO;p.session=91;p.required=AF_APPLY_PROTOCOL_REQUIRED;
 CHECK(!af_apply_packet_encode(&p,wire,sizeof wire,&n));
 /* 只在宿主调用既有状态函数，避免调用固定原发送地址。 */
 CHECK(af_hs_server(&af_cp_handshake,wire,128,0x80020002u,reply,128,&n)==1 && n==128);
 p.operation=AF_APPLY_PRESET;p.version=4;p.slot=7;p.preset.base=18;p.preset.params[6]=3;
 CHECK(!af_apply_packet_encode(&p,wire,sizeof wire,&n));
 CHECK(af_cp_hs_receive(wire,0x80020002u,128)==1 && prepared==1 && af_cp_hs_input_version==4);
 int previous=checks;ready=0;
 CHECK(af_cp_hs_receive(ordinary,0x80020002u,sizeof ordinary)==0);
 CHECK(af_cp_handshake.session==91 && af_cp_handshake.state==5 && af_cp_hs_input_version==4 && checks==previous);
 CHECK(af_cp_hs_start_once()==AF_BUSY && af_cp_handshake.session==91 && checks==previous);
 CHECK(af_cp_hs_configure(AF_APPLY_PROTOCOL_REQUIRED)==AF_BUSY);
 CHECK(af_cp_handshake.session==91 && af_cp_hs_input_version==4 && checks==previous);
 return 0;
}
''')
    binary=tmp_path/'startup'
    cmd=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-DAF_CP_PRESET406=1',
         '-DAF_RUNTIME406=1','-DAF_FACTORY_RESTORE406=1','-DAF_SNAPSHOT_OVERLAY406=1',
         '-I'+str(NATIVE),str(source),str(NATIVE/'af_hs_cp406.c'),
         *[str(NATIVE/name) for name in ('af_slots.c','af_apply_wire.c','af_handshake.c')],'-o',str(binary)]
    result=subprocess.run(cmd,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.returncode
