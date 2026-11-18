"""真实CP C入口的软件接线；消费者决定不是相机像素结果。"""
from pathlib import Path
import hashlib
import struct
import subprocess
import zlib

import pytest

from test_recipe_transport import api as transport_api, transaction

NATIVE = Path(__file__).resolve().parents[1] / "native"

DRIVER = r'''
#include "af_cp_recipe406.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do {if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 91;}}while(0)
#define ASSERT(x) do {if(!(x))abort();}while(0)
extern AfHandshake af_cp_handshake;
extern uint64_t af_cp_hs_input_version;
extern uint32_t af_cp_hs_input_slot,af_cp_hs_input_fault;
extern int af_cp_hs_last_prepare;
int af_cp_hs_receive(const void *,uint32_t,size_t);
int af_cp_hs_start_once(void);
static unsigned char frames[2][28][128],image[1943],ack[128];
static unsigned allocated,freed,calls,sends,pure_calls;
static int decision,send_failure,allocation_failure;
static AfRecipeLease held[2];static const AfRecipeOwned *borrowed[2];
static void *allocate(void *c,size_t n){ASSERT(!c && n==af_cp_recipe406_owner_bytes());++allocated;return allocation_failure?0:malloc(n);}
static void release(void *c,void *p){ASSERT(!c);++freed;free(p);}
static int send_ack(void *c,const void *p,size_t n,uint32_t source){
    ASSERT(!c && n==128 && source==0x80020002u);memcpy(ack,p,128);++sends;return send_failure?-9:0;
}
static int consumer(void *c,const AfRecipeOwned *value,const AfRecipeLease *lease){
    ASSERT(!c && calls<2 && value && lease && value->state==AF_RECIPE_TAKEN);
    ASSERT(!memcmp(value->message.image,image,1943));
    ASSERT(value->message.preset.base==17 && value->message.preset.kind==1);
    ASSERT(value->message.preset.params[0]==-1 && value->message.preset.params[6]==3);
    ASSERT(value->asset.base==17 && value->asset.recipe.matrix[0]==-9);
    ASSERT(!memcmp(value->asset.model_sha256,image+64,32));
    held[calls]=*lease;borrowed[calls]=value;++calls;return decision;
}
int af_cp406_locked_prepare(const AfPreset *preset){ASSERT(preset->kind==0);++pure_calls;return AF_OK;}
static AfCpRecipe406Config config(void){
    return (AfCpRecipe406Config){&af_cp_handshake,&af_cp_hs_input_version,&af_cp_hs_input_slot,
        &af_cp_hs_input_fault,allocate,release,send_ack,consumer,0};
}
static int hello(void){
    AfApplyPacket p={.operation=AF_APPLY_HELLO,.required=AF_APPLY_PROTOCOL_REQUIRED,.session=0x1122334455667788ull};
    unsigned char raw[128],reply[128];size_t n=0,size=0;
    CHECK(af_apply_packet_encode(&p,raw,sizeof raw,&n)==0 && n==128);
    /* HELLO走真实公共服务；避免在宿主执行原固件固定地址Sender。 */
    CHECK(af_hs_server(&af_cp_handshake,raw,128,0x80020002u,reply,128,&size)==1 && size==128);
    CHECK(af_cp_handshake.state==5 && af_cp_handshake.session==p.session);
    return 0;
}
static int pure(uint64_t v,int expected){
    AfApplyPacket p={.operation=AF_APPLY_PRESET,.required=AF_APPLY_PROTOCOL_REQUIRED,.slot=7,
        .session=0x1122334455667788ull,.version=v,.preset={.base=0,.params={0,0,0,0,0,0,1,0}}};
    unsigned char raw[128];size_t n=0;
    CHECK(af_apply_packet_encode(&p,raw,sizeof raw,&n)==0 && n==128);
    CHECK(af_cp_hs_receive(raw,0x80020002u,n)==1 && af_cp_hs_last_prepare==expected);
    return 0;
}
static int receive(unsigned which){
    for(unsigned i=0;i<28;++i)CHECK(af_cp_hs_receive(frames[which][i],0x80020002u,128)==1);
    return 0;
}
static int check_ack(int status,uint64_t v){
    AfRecipeAck decoded;CHECK(af_recipe_ack_decode(ack,sizeof ack,&decoded)==0);
    CHECK(decoded.status==status && decoded.version==v && decoded.slot==7);
    CHECK(decoded.session==0x1122334455667788ull);
    CHECK(!memcmp(decoded.payload_sha256,frames[v-1][0]+60,32));return 0;
}
int main(int argc,char **argv){
    CHECK(argc==3);FILE *f=fopen(argv[2],"rb");CHECK(f);
    CHECK(fread(frames,1,sizeof frames,f)==sizeof frames && fclose(f)==0);
    unsigned at=0;for(unsigned i=1;i<27;++i){unsigned n=i==26?43:76;memcpy(image+at,frames[0][i]+48,n);at+=n;}
    CHECK(at==1943 && (AF_APPLY_PROTOCOL_REQUIRED&AF_APPLY_CAP_FULL_RECIPE));
    CHECK(af_cp_hs_start_once()==AF_BUSY && !af_cp_handshake.state);
    CHECK(af_cp_hs_receive(frames[0][0],0x80020003u,128)==0);
    CHECK(af_cp_hs_receive(frames[0][0],0x80020002u,128)==1 && !af_cp_handshake.state);
    AfCpRecipe406Config c=config();
    if(!strcmp(argv[1],"binding")){
        c.consume=0;CHECK(af_cp_recipe406_bind(&c)==AF_INVALID && !allocated);
        c=config();c.input_fault=c.input_slot;CHECK(af_cp_recipe406_bind(&c)==AF_INVALID && !allocated);
        c=config();allocation_failure=1;CHECK(af_cp_recipe406_bind(&c)==AF_EXHAUSTED && allocated==1);
        CHECK(!af_cp_recipe406_ready(&af_cp_handshake));allocation_failure=0;
        CHECK(af_cp_recipe406_bind(&c)==0 && af_cp_recipe406_ready(&af_cp_handshake));
        CHECK(af_cp_recipe406_bind(&c)==AF_BUSY && allocated==2);
        CHECK(af_cp_recipe406_unbind()==0 && freed==1 && !af_cp_recipe406_ready(&af_cp_handshake));return 0;
    }
    CHECK(af_cp_recipe406_bind(&c)==0 && allocated==1 && !freed);
    CHECK(af_cp_hs_start_once()==0 && af_cp_handshake.state==4);
    CHECK(af_cp_hs_receive(frames[0][0],0x80020002u,128)==1);
    CHECK(af_cp_recipe406_last_result()==AF_BUSY && !af_cp_recipe406_seen_version() && !calls);
    CHECK(hello()==0 && af_cp_recipe406_unbind()==AF_BUSY);
    if(!strcmp(argv[1],"reject")){
        decision=AF_INVALID;CHECK(receive(0)==0 && calls==1 && sends==1);
        CHECK(check_ack(AF_INVALID,1)==0 && !af_cp_hs_input_version && af_cp_recipe406_seen_version()==1);
        CHECK(!af_cp_recipe406_busy() && af_cp_recipe406_release(&held[0])==AF_STALE);
        CHECK(pure(1,AF_STALE)==0 && !pure_calls);CHECK(pure(2,AF_OK)==0 && pure_calls==1);
    }else if(!strcmp(argv[1],"pending")){
        decision=AF_BUSY;CHECK(receive(0)==0 && calls==1 && !sends && af_cp_recipe406_busy());
        AfRecipeLease lease;const AfRecipeOwned *value=0;
        CHECK(af_cp_recipe406_pending(&lease,&value)==0 && value==borrowed[0] && lease.lease==held[0].lease);
        memset(frames[0][1],0,128);CHECK(!memcmp(value->message.image,image,1943));
        CHECK(pure(2,AF_BUSY)==0 && !pure_calls);
        CHECK(af_cp_hs_receive(frames[1][0],0x80020002u,128)==1 && calls==1 && !sends);
        CHECK(af_cp_recipe406_release(&lease)==AF_BUSY);
        CHECK(af_cp_recipe406_finish(AF_INVALID)==0 && sends==1 && !af_cp_recipe406_busy());
        CHECK(check_ack(AF_INVALID,1)==0 && pure(1,AF_STALE)==0 && pure(2,AF_OK)==0);
    }else if(!strcmp(argv[1],"accept")){
        decision=AF_OK;CHECK(receive(0)==0 && calls==1 && sends==1);
        CHECK(check_ack(0,1)==0 && af_cp_hs_input_version==1 && af_cp_hs_input_slot==7);
        CHECK(receive(1)==0 && calls==2 && sends==2 && af_cp_hs_input_version==2);
        CHECK(check_ack(0,2)==0 && !memcmp(borrowed[0]->message.image,image,1943));
        CHECK(borrowed[0]->state==AF_RECIPE_RETIRED && borrowed[1]->state==AF_RECIPE_ACTIVE);
        CHECK(af_cp_recipe406_release(&held[0])==0 && af_cp_recipe406_release(&held[0])==AF_STALE);
        CHECK(af_cp_recipe406_release(&held[1])==0 && pure(2,AF_STALE)==0);
    }else if(!strcmp(argv[1],"unknown")){
        decision=AF_IO;CHECK(receive(0)==0 && calls==1 && !sends && af_cp_hs_input_fault);
        CHECK(af_cp_recipe406_busy() && af_cp_recipe406_release(&held[0])==AF_BUSY);
        CHECK(receive(1)==0 && calls==1 && !sends && pure(2,AF_IO)==0);
        CHECK(!memcmp(borrowed[0]->message.image,image,1943) && !af_cp_hs_input_version);
        /* 只有测试消费者作出明确后续决定，才允许释放；故障标志仍保持关闭。 */
        CHECK(af_cp_recipe406_finish(AF_INVALID)==0 && sends==1 && af_cp_hs_input_fault);
        CHECK(check_ack(AF_INVALID,1)==0 && !af_cp_recipe406_busy());
    }else if(!strcmp(argv[1],"send_failure")){
        decision=AF_OK;send_failure=1;CHECK(receive(0)==0 && calls==1 && sends==1);
        CHECK(af_cp_hs_input_version==1 && af_cp_hs_input_fault && af_cp_recipe406_last_send()==-9);
        CHECK(borrowed[0]->state==AF_RECIPE_ACTIVE && af_cp_recipe406_finish(0)==AF_EMPTY);
        CHECK(receive(1)==0 && calls==1 && sends==1 && pure(2,AF_IO)==0);
        CHECK(af_cp_recipe406_release(&held[0])==0);
    }else if(!strcmp(argv[1],"malformed")){
        unsigned char bad[128];memcpy(bad,frames[0][0],128);
        CHECK(af_cp_hs_receive(bad,0x80020002u,127)==1 && af_cp_recipe406_last_result()==AF_INVALID);
        bad[50]^=1;CHECK(af_cp_hs_receive(bad,0x80020002u,128)==1 && !af_cp_recipe406_seen_version());
        CHECK(af_cp_hs_receive(frames[0][0],0x80020002u,128)==1 && af_cp_recipe406_seen_version()==1);
        CHECK(af_cp_hs_receive(frames[0][2],0x80020002u,128)==1 && af_cp_recipe406_last_result()==AF_STALE);
        CHECK(!calls && !sends && pure(2,AF_BUSY)==0);
        decision=AF_INVALID;for(unsigned i=1;i<28;++i)CHECK(af_cp_hs_receive(frames[0][i],0x80020002u,128)==1);
        CHECK(calls==1 && sends==1 && check_ack(AF_INVALID,1)==0);
    }else if(!strcmp(argv[1],"pure_first")){
        CHECK(pure(2,AF_OK)==0 && af_cp_hs_input_version==2);
        CHECK(receive(0)==0 && receive(1)==0 && !calls && !sends && !af_cp_recipe406_seen_version());
    }else if(!strcmp(argv[1],"payload_bad")){
        CHECK(receive(0)==0 && !calls && sends==1);
        CHECK(check_ack(AF_INVALID,1)==0 && !af_cp_hs_input_version && !af_cp_recipe406_busy());
        CHECK(af_cp_recipe406_seen_version()==1 && pure(1,AF_STALE)==0);
    }else if(!strcmp(argv[1],"missing_cap")){
        /* 同会话旧HELLO不是完整配方能力证明。 */
        af_cp_handshake.required&=~AF_APPLY_CAP_FULL_RECIPE;
        CHECK(receive(0)==0 && !calls && !sends && !af_cp_recipe406_seen_version());
    }else return 92;
    CHECK(!freed);return 0;
}
'''


@pytest.fixture(scope="module")
def ingress_driver(tmp_path_factory):
    folder = tmp_path_factory.mktemp("cp-recipe406")
    src = folder / "driver.c"
    src.write_text(DRIVER)
    binary = folder / "driver"
    names = ("af_cp_recipe406.c", "af_hs_cp406.c", "af_recipe_transport.c",
             "af_joint_asset.c", "af_sha256.c", "af_joint.c", "af_slots.c",
             "af_handshake.c", "af_apply_wire.c")
    result = subprocess.run(
        ["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
         "-DAF_RECIPE_BRIDGE406=1", "-DAF_RUNTIME406=1", "-DAF_CP_PRESET406=1",
         "-I" + str(NATIVE), str(src), *map(str, (NATIVE / n for n in names)),
         "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("scenario", ["binding", "reject", "pending", "accept", "unknown",
                                      "send_failure", "malformed", "pure_first", "missing_cap", "payload_bad"])
def test_real_cp_ingress_complete_recipe_owns_bytes_and_requires_explicit_decision(
        ingress_driver, transport_api, tmp_path, scenario):
    frames = transaction(transport_api, version=1)[1] + transaction(transport_api, version=2)[1]
    if scenario == "payload_bad":
        # 外层摘要和各片CRC正确，AJR1内部CP身份损坏；必须由完整验证拒绝。
        image = bytearray(b"".join(f[48:48 + struct.unpack_from("<H", f, 36)[0]] for f in frames[1:27]))
        image[32] ^= 1
        for i in range(27):
            frame = bytearray(frames[i])
            if i == 0:
                frame[60:92] = hashlib.sha256(image).digest()
            else:
                n = struct.unpack_from("<H", frame, 36)[0]
                frame[48:48 + n] = image[(i - 1) * 76:(i - 1) * 76 + n]
            struct.pack_into("<I", frame, 124, zlib.crc32(frame[:124]))
            frames[i] = bytes(frame)
    source = tmp_path / "messages.bin"
    source.write_bytes(b"".join(frames))
    result = subprocess.run([str(ingress_driver), scenario, str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
