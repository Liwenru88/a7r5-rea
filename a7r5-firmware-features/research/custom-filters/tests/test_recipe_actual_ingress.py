"""同一进程贯通真实AP发送与CP入口；原端口为宿主边界，不证明相机像素。"""
from pathlib import Path
import subprocess


NATIVE = Path(__file__).resolve().parents[1] / "native"

DRIVER = r'''
#include "af_runtime_ap406.h"
#include "af_cp_recipe406.h"
#include "af_cp406_state.h"
#include "af_sha256.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
extern AfHandshake af_cp_handshake;
extern uint64_t af_cp_hs_input_version;
extern uint32_t af_cp_hs_input_slot,af_cp_hs_input_fault;
extern int af_cp_hs_last_prepare;
int af_cp_hs_start_once(void);
int af_cp_hs_receive(const void *,uint32_t,size_t);
int af_ap_runtime_next(uint32_t,void **);
int af_ap_runtime_reply(const void *,uint32_t,size_t);
static unsigned char message[128],hello[128],old_ack[128],image[AF_JOINT_ASSET_BYTES],expected[AF_JOINT_ASSET_BYTES];
static unsigned char state[AF_CP406_STATE_BYTES],marker;
static AfPreset expected_preset;
static AfJointAsset expected_asset;
static AfRecipeLease held;
static const AfRecipeOwned *borrowed;
static unsigned allocated,sent,fragments,consumed,acks,reentrant_acks,pure_prepares,heap_allocated;
static int hello_pending,in_end;
static int monotonic(int id,void *out){int64_t *t=out;assert(id==1);t[0]=0;t[1]=100000000;return 0;}
void *af_stock_dlsym(void *p,const char *name){assert(!p&&!strcmp(name,"clock_gettime"));return (void *)monotonic;}
int af_stock_open(const char *p,int flags,...){assert(!strcmp(p,"/dev/urandom")&&!flags);return 61;}
long af_stock_read(int fd,void *p,size_t n){assert(fd==61&&n==8);memset(p,0,n);((unsigned char *)p)[0]=71;return 8;}
int af_stock_close(int fd){assert(fd==61);return 0;}
int *af_stock_errno(void){static int e=4;return &e;}
int af_stock_usleep(unsigned n){(void)n;return 0;}
int af_stock_allocate(uint32_t queue,void **out,uint32_t bytes,int wait){
    assert(queue==0x90030001u&&bytes==128&&!wait);++allocated;*out=message;return 0;
}
void af_stock_source(void *p,uint32_t source){assert(p==message&&source==0x80020002u);}
int af_stock_receive(uint32_t queue,void **out,int wait){
    assert(queue==0x80020002u&&wait>=0&&wait<=50);*out=0;
    if(!hello_pending)return -1022;hello_pending=0;*out=hello;return 0;
}
int af_stock_send(uint32_t queue,void *p){
    assert(queue==0x90030001u&&p==message);++sent;
    if(message[2]=='P'){
        AfApplyPacket packet;assert(!af_apply_packet_decode(p,128,&packet));
        if(packet.operation==AF_APPLY_HELLO){
            /* 显式绕过真实CP入口中固定固件地址Sender；握手状态机仍为真实C实现。 */
            size_t bytes=0;
            assert(af_hs_server(&af_cp_handshake,p,128,0x80020002u,hello,sizeof hello,&bytes)==1&&bytes==128);
            hello_pending=1;return 0;
        }
        assert(packet.operation==AF_APPLY_PRESET);
        assert(af_cp_hs_receive(p,0x80020002u,128)==1&&af_cp_hs_last_prepare==AF_OK);return 0;
    }
    assert(!memcmp(message,"A7R1",4));++fragments;
    in_end=message[5]==AF_RECIPE_END;
    assert(af_cp_hs_receive(p,0x80020002u,128)==1);in_end=0;return 0;
}
int af_cp406_locked_prepare(const AfPreset *preset){
    /* 原锁/成像驱动为显式边界，只验证现有纯参数状态写入器的真实C实现。 */
    ++pure_prepares;return af_cp406_write_state(preset,state,sizeof state,&marker);
}
static void *heap_allocate(void *context,size_t bytes){
    assert(!context&&bytes==af_cp_recipe406_owner_bytes());++heap_allocated;return malloc(bytes);
}
static void heap_free(void *context,void *p){assert(!context);free(p);}
static int reply(void *context,const void *raw,size_t bytes,uint32_t destination){
    assert(!context&&bytes==128&&destination==0x80020002u);++acks;
    if(in_end)++reentrant_acks;
    if(acks==1)memcpy(old_ack,raw,128);
    /* 完整END尚未返回时同步进入真实AP回执入口。 */
    assert(af_ap_runtime_reply(raw,0x90030001u,bytes)==1);return 0;
}
static int consume(void *context,const AfRecipeOwned *value,const AfRecipeLease *lease){
    assert(!context&&value&&lease&&value->state==AF_RECIPE_TAKEN);
    assert(!memcmp(value->message.image,expected,sizeof expected));
    assert(!memcmp(&value->message.preset,&expected_preset,sizeof expected_preset));
    assert(value->asset.base==expected_asset.base);
    assert(!memcmp(value->asset.model_sha256,expected_asset.model_sha256,32));
    assert(!memcmp(&value->asset.recipe,&expected_asset.recipe,sizeof expected_asset.recipe));
    ++consumed;
    assert(value->message.session==71&&value->message.version==(consumed==1?2:4));
    held=*lease;borrowed=value;
    return consumed==1?AF_INVALID:AF_BUSY;
}
static void direct_pure_while_pending(const AfPreset *preset){
    AfApplyPacket packet={.operation=AF_APPLY_PRESET,.required=AF_APPLY_PROTOCOL_REQUIRED,
        .slot=7,.session=71,.version=5,.preset=*preset};
    unsigned char raw[128];size_t bytes=0;
    assert(!af_apply_packet_encode(&packet,raw,sizeof raw,&bytes)&&bytes==128);
    assert(af_cp_hs_receive(raw,0x80020002u,bytes)==1&&af_cp_hs_last_prepare==AF_BUSY);
}
int main(void){
    AfCpRecipe406Config cp={&af_cp_handshake,&af_cp_hs_input_version,&af_cp_hs_input_slot,
        &af_cp_hs_input_fault,heap_allocate,heap_free,reply,consume,0};
    assert(af_cp_hs_start_once()==AF_BUSY&&!af_cp_handshake.state);
    assert(!af_cp_recipe406_bind(&cp)&&heap_allocated==1&&!af_cp_hs_start_once());
    void *incoming=0;
    assert(af_ap_runtime_next(0x80020002u,&incoming)==1&&incoming==hello);
    assert(af_ap_runtime_reply(incoming,0x90030001u,128)==1);
    assert(af_ap_runtime_preset_capabilities()==AF_APPLY_PROTOCOL_REQUIRED&&af_cp_handshake.state==5);

    AfPreset pure={.base=18,.params={-3,4,-5,6,-7,8,3,2}};
    assert(!af_ap_runtime_send_preset(7,&pure)&&af_cp_hs_input_version==1&&pure_prepares==1);
    assert(state[0xa40]==20&&marker==1);
    expected_asset.base=17;
    for(unsigned i=0;i<32;++i)expected_asset.model_sha256[i]=(unsigned char)(i+1);
    for(unsigned i=0;i<129;++i)expected_asset.recipe.gamma[i]=i*1024;
    for(unsigned i=0;i<18;++i)expected_asset.recipe.matrix[i]=(int16_t)((int)i-9);
    for(unsigned i=0;i<24;++i)expected_asset.recipe.cc1[i]=(int16_t)((int)i-12);
    for(unsigned i=0;i<1215;++i)expected_asset.recipe.grid[i]=(int8_t)((int)(i%128)-64);
    size_t written=0;
    assert(!af_joint_asset_encode(&expected_asset,image,sizeof image,&written)&&written==sizeof image);
    memcpy(expected,image,sizeof image);
    expected_preset=(AfPreset){.base=17,.kind=1,.params={-1,2,-3,4,-5,6,3,8}};
    assert(!af_sha256(image,sizeof image,expected_preset.payload_sha256));expected_preset.lut_sha256[0]=91;
    AfPreset imported=expected_preset;

    assert(!af_ap_runtime_send_recipe(7,&imported,image,sizeof image,1000));
    AfRecipeAck acknowledgment;
    assert(!af_ap_runtime_recipe_result(&acknowledgment)&&acknowledgment.status==AF_INVALID);
    assert(acknowledgment.version==2&&acknowledgment.slot==7&&acks==1&&reentrant_acks==1);
    assert(af_cp_hs_input_version==1&&af_cp_recipe406_seen_version()==2&&!af_cp_recipe406_busy());
    assert(af_cp_recipe406_release(&held)==AF_STALE);
    assert(!af_ap_runtime_send_preset(7,&pure)&&af_cp_hs_input_version==3&&pure_prepares==2);

    assert(!af_ap_runtime_send_recipe(20,&imported,image,sizeof image,1000));
    assert(consumed==2&&acks==1&&af_cp_recipe406_busy()&&af_ap_runtime_last_attempted_version()==4);
    memset(image,0,sizeof image);memset(&imported,0,sizeof imported);
    assert(!memcmp(borrowed->message.image,expected,sizeof expected));
    assert(!memcmp(&borrowed->message.preset,&expected_preset,sizeof expected_preset));
    unsigned before=allocated;
    assert(af_ap_runtime_recipe_result(&acknowledgment)==AF_BUSY);
    assert(af_ap_runtime_send_preset(7,&pure)==AF_BUSY&&af_ap_runtime_release_preset()==AF_BUSY);
    assert(allocated==before&&af_cp_hs_input_version==3&&pure_prepares==2);
    direct_pure_while_pending(&pure);
    AfRecipeLease pending;const AfRecipeOwned *value=0;
    assert(!af_cp_recipe406_pending(&pending,&value)&&value==borrowed&&pending.lease==held.lease);
    assert(af_cp_recipe406_release(&held)==AF_BUSY);

    /* 这里只确认软件prepared决定；测试消费者不产生ISP表或相机图像。 */
    assert(!af_cp_recipe406_finish(AF_OK)&&acks==2&&reentrant_acks==1);
    assert(!af_ap_runtime_recipe_result(&acknowledgment)&&acknowledgment.status==AF_OK);
    assert(acknowledgment.version==4&&acknowledgment.slot==20);
    assert(!memcmp(acknowledgment.payload_sha256,expected_preset.payload_sha256,32));
    assert(af_cp_hs_input_version==4&&af_cp_hs_input_slot==20&&!af_cp_recipe406_busy());
    assert(!af_cp_recipe406_release(&held)&&af_cp_recipe406_release(&held)==AF_STALE);
    assert(!af_ap_runtime_send_preset(7,&pure)&&af_cp_hs_input_version==5&&pure_prepares==3);
    assert(af_ap_runtime_last_attempted_version()==5&&!af_cp_hs_input_fault);
    assert(af_ap_runtime_reply(old_ack,0x90030001u,128)==1);
    assert(!af_ap_runtime_recipe_result(&acknowledgment)&&acknowledgment.version==4);
    assert(fragments==56&&consumed==2&&sent==60&&allocated==60);
    return 0;
}
'''


def test_actual_ap_sender_to_cp_ingress_and_reentrant_software_ack(tmp_path):
    source, executable = tmp_path / "actual_ingress.c", tmp_path / "actual_ingress"
    source.write_text(DRIVER)
    files = ("af_runtime_ap406.c", "af_runtime.c", "af_handshake.c", "af_apply_wire.c",
             "af_cp_recipe406.c", "af_hs_cp406.c", "af_cp406_state.c", "af_recipe_transport.c",
             "af_joint_asset.c", "af_sha256.c", "af_joint.c", "af_slots.c")
    compiled = subprocess.run(
        ["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-DAF_CP_PRESET406=1",
         "-DAF_RUNTIME406=1", "-DAF_FACTORY_RESTORE406=1", "-DAF_RECIPE_BRIDGE406=1",
         "-I" + str(NATIVE), str(source), *[str(NATIVE / name) for name in files],
         "-o", str(executable)], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
