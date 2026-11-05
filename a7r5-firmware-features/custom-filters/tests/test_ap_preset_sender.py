"""UI发送复用已发布会话，不跨线程改AfRuntime；无真实系统服务。"""
from pathlib import Path
import subprocess

ROOT=next(p for p in Path(__file__).resolve().parents
          if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
PROPOSAL=Path(__file__).resolve().parents[1]/'native'


def test_ui_preset_sender_session_versions_and_failure_close(tmp_path):
    src=tmp_path/'sender.c'
    src.write_text(r'''
#include "af_runtime_ap406.h"
#include <pthread.h>
#include <string.h>
#include <stdlib.h>
extern AfRuntime af_ap_runtime;
int af_ap_runtime_reply(const void *,uint32_t,size_t);
int af_ap_runtime_poll(void);
static unsigned char storage[128];
static uint64_t accepted_version;
static unsigned sends,allocations;
static int failure;
static int64_t now=100;
#define CHECK(x) do { if (!(x)) abort(); } while (0)
static int monotonic(int id,void *out) {
    int64_t *v=out;CHECK(id==1);v[0]=now/1000;v[1]=(now%1000)*1000000;return 0;
}
void *af_stock_dlsym(void *p,const char *name) { CHECK(!p && !strcmp(name,"clock_gettime"));return (void *)monotonic; }
int af_stock_open(const char *p,int flags,...) { (void)p;(void)flags;return -1; }
long af_stock_read(int fd,void *p,size_t n) { (void)fd;(void)p;(void)n;return -1; }
int af_stock_close(int fd) { (void)fd;return 0; }
int *af_stock_errno(void) { static int e=4;return &e; }
int af_stock_allocate(uint32_t q,void **p,uint32_t n,int wait) {
    CHECK(q==0x90030001u && n==128 && wait==0);++allocations;
    if (failure==1) return -1;*p=storage;return 0;
}
void af_stock_source(void *p,uint32_t source) { CHECK(p==storage && source==0x80020002u); }
int af_stock_send(uint32_t q,void *p) {
    AfApplyPacket parsed;CHECK(q==0x90030001u && p==storage);
    CHECK(af_apply_packet_decode(p,128,&parsed)==0 && parsed.operation==AF_APPLY_PRESET);
    CHECK(parsed.session==71 && parsed.required==0x1fff && parsed.slot==7 && parsed.preset.base==18);
    CHECK(parsed.version==accepted_version+1);accepted_version=parsed.version;++sends;
    return failure==2?-1:0;
}
int af_stock_receive(uint32_t q,void **out,int wait) { (void)q;(void)out;(void)wait;return -1022; }
int af_stock_usleep(unsigned n) { (void)n;return 0; }
static AfPreset preset={.base=18,.params={-3,4,-5,2,6,7,3,8}};
static void *ui(void *p) {
    (void)p;
    for (int i=0;i<100;++i) { int result=af_ap_runtime_send_preset(7,&preset);CHECK(result==AF_OK || result==AF_BUSY); }
    return 0;
}
int main(int argc,char **argv) {
    unsigned char hello[128];size_t n;pthread_t workers[8];
    AfApplyPacket h={.operation=AF_APPLY_HELLO,.required=0x1fff,.session=71};
    CHECK(argc==2 && af_ap_runtime_send_preset(7,&preset)==AF_BUSY && allocations==0);
    af_ap_runtime.attempted=1;af_ap_runtime.last_now=100;
    af_ap_runtime.hello=(AfHandshake){.session=71,.deadline=1100,.required=0x1fff,.state=1};
    if (atoi(argv[1])==3) {
        now=1100;CHECK(af_ap_runtime_poll()==AF_STALE && af_ap_runtime.fault==0);
        CHECK(af_ap_runtime_poll()==AF_STALE && af_ap_runtime.fault==0);
        CHECK(af_ap_runtime_send_preset(7,&preset)==AF_IO && !allocations);return 0;
    }
    CHECK(af_apply_packet_encode(&h,hello,sizeof(hello),&n)==0);
    CHECK(af_ap_runtime_reply(hello,0x90030001u,128)==1 && af_ap_runtime.hello.state==2);
    for (int i=0;i<8;++i) CHECK(!pthread_create(&workers[i],0,ui,0));
    for (int i=0;i<8;++i) CHECK(!pthread_join(workers[i],0));
    CHECK(sends>0 && sends<=800 && allocations==sends && af_ap_runtime_last_attempted_version()==sends);
    {AfPreset lut=preset;lut.kind=1;CHECK(af_ap_runtime_send_preset(7,&lut)==AF_INVALID);}
    CHECK(af_ap_runtime_send_preset(0,&preset)==AF_INVALID && af_ap_runtime_last_attempted_version()==sends);
    failure=atoi(argv[1]);CHECK(failure==1 || failure==2);
    {unsigned old=allocations;uint64_t version=af_ap_runtime_last_attempted_version();
     CHECK(af_ap_runtime_send_preset(7,&preset)==AF_IO && allocations==old+1);
     CHECK(af_ap_runtime_last_attempted_version()==version+1 && af_ap_runtime.fault==0);
     CHECK(af_ap_runtime_send_preset(7,&preset)==AF_IO && allocations==old+1);}
    CHECK(af_ap_runtime_poll()==AF_INVALID && af_ap_runtime.fault==AF_RT_SEND && af_ap_runtime.hello.state==3);
    return 0;
}
''')
    binary=tmp_path/'sender'
    args=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-DAF_CP_PRESET406=1','-I'+str(PROPOSAL),'-I'+str(NATIVE),'-pthread',str(src),str(PROPOSAL/'af_runtime_ap406.c'),*[str(NATIVE/n) for n in ('af_slots.c','af_apply_wire.c','af_handshake.c','af_runtime.c')],'-o',str(binary)]
    build=subprocess.run(args,capture_output=True,text=True)
    assert build.returncode==0,build.stderr
    for failure in ('1','2','3'):
        result=subprocess.run([str(binary),failure],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
