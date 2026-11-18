"""实际AP发送／回执入口；原系统服务为显式宿主边界，无目标或设备执行。"""
from pathlib import Path
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'native'
HARNESS = r'''
#include "af_runtime_ap406.h"
#include "af_sha256.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
extern AfRuntime af_ap_runtime;
int af_ap_runtime_reply(const void *,uint32_t,size_t);
int af_ap_runtime_poll(void);
int af_ap_runtime_next(uint32_t,void **);
static uint64_t now=100,seen;
static int mode,waited,allocations,sends,frames;
static uint8_t storage[128],acknowledgment[128];
static AfRecipeRx receiver;
static AfJointAssetDecodeWork work;
static int monotonic(int id,void *out){int64_t *t=out;assert(id==1);t[0]=(int64_t)(now/1000);t[1]=(int64_t)(now%1000)*1000000;return 0;}
void *af_stock_dlsym(void *p,const char *name){assert(!p&&!strcmp(name,"clock_gettime"));return (void *)monotonic;}
int af_stock_open(const char *p,int f,...){(void)p;(void)f;return -1;}
long af_stock_read(int f,void *p,size_t n){(void)f;(void)p;(void)n;return -1;}
int af_stock_close(int f){(void)f;return 0;}
int *af_stock_errno(void){static int e=4;return &e;}
int af_stock_usleep(unsigned n){(void)n;return 0;}
int af_stock_allocate(uint32_t q,void **p,uint32_t n,int wait){
 assert(q==0x90030001u&&n==128&&wait==0);++allocations;*p=storage;
 if(mode==5&&allocations==28){now=1100;(void)af_ap_runtime_poll();}
 return 0;
}
void af_stock_source(void *p,uint32_t source){assert(p==storage&&source==0x80020002u);}
int af_stock_receive(uint32_t q,void **out,int wait){assert(q==0x80020002u&&wait>=0&&wait<=50);waited=wait;now+=(unsigned)wait;*out=0;return -1022;}
int af_stock_send(uint32_t q,void *p){
 assert(q==0x90030001u&&p==storage);++sends;
 if(storage[2]=='P'){
  AfApplyPacket v;assert(!af_apply_packet_decode(p,128,&v)&&v.version==seen+1);seen=v.version;return 0;
 }
 assert(storage[2]=='R');++frames;
 if(mode==3&&frames==5)return -1;
 if(mode==6&&storage[5]==AF_RECIPE_END){now=1100;(void)af_ap_runtime_poll();}
 assert(!af_recipe_rx_frame(&receiver,p,128));
 if(storage[5]==AF_RECIPE_END){
  AfRecipeLease lease;const AfRecipeOwned *owned;
  assert(!af_recipe_rx_validate(&receiver,&work)&&!af_recipe_rx_take(&receiver,&lease,&owned));
  assert(owned->message.session==71&&owned->message.version==seen+1);
  seen=owned->message.version;
  assert(!af_recipe_rx_finish(&receiver,&lease,mode==1?AF_INVALID:AF_OK,acknowledgment,128));
  assert(!af_recipe_rx_release(&receiver,&lease));
 }
 return 0;
}
static void connect(uint32_t caps){
 uint8_t hello[128];size_t bytes=0;
 AfApplyPacket p={.operation=AF_APPLY_HELLO,.session=71,.required=caps};
 af_ap_runtime.attempted=1;af_ap_runtime.last_now=now;
 af_ap_runtime.hello=(AfHandshake){.session=71,.deadline=1100,.required=caps,.state=1};
 assert(!af_apply_packet_encode(&p,hello,128,&bytes));
 assert(af_ap_runtime_reply(hello,0x90030001u,128)==1&&af_ap_runtime.hello.state==2);
}
static int capture(void *context,uint32_t slot,const AfPreset *preset,uint64_t session,uint64_t version,AfRecipeTx *out){
 assert(context&&slot==7&&session==71&&version==1&&!allocations);
 AfPreset native={.params={0,0,0,0,0,0,3,0}};
 assert(af_ap_runtime_send_preset(7,&native)==AF_BUSY);
 if(mode==8)return AF_IO;
 int result=af_recipe_tx_init(out,session,version,slot,preset,context,AF_JOINT_ASSET_BYTES);
 if(!result&&mode==9)out->message.version++;
 return result;
}
int main(int argc,char **argv){
 assert(argc==2);mode=atoi(argv[1]);
 AfJointAsset asset={0};uint8_t image[AF_JOINT_ASSET_BYTES];size_t written=0;
 AfPreset preset={.base=0,.kind=1},native={.base=17};native.params[6]=3;
 asset.model_sha256[0]=19;
 for(unsigned i=0;i<129;++i)asset.recipe.gamma[i]=i*1000;
 assert(!af_joint_asset_encode(&asset,image,sizeof image,&written)&&written==sizeof image);
 assert(!af_sha256(image,sizeof image,preset.payload_sha256));preset.lut_sha256[0]=41;preset.params[6]=3;
 assert(af_ap_runtime_send_recipe(7,&preset,image,sizeof image,1000)==AF_BUSY&&!allocations);
 assert(af_ap_runtime_preset_status()==AF_BUSY);
 connect(mode==4?(AF_APPLY_PROTOCOL_REQUIRED&~(AF_APPLY_CAP_FULL_RECIPE|AF_APPLY_CAP_USER20|AF_APPLY_CAP_SECTOR_MATRIX)):
  mode==11?(AF_APPLY_PROTOCOL_REQUIRED&~AF_APPLY_CAP_USER20):AF_APPLY_PROTOCOL_REQUIRED);
 assert(af_ap_runtime_preset_status()==AF_OK);
 if(mode==4){assert(af_ap_runtime_send_recipe(7,&preset,image,sizeof image,1000)==AF_INVALID&&!allocations);return 0;}
 assert(af_ap_runtime_send_recipe(0,&preset,image,sizeof image,1000)==AF_INVALID&&!allocations);
 if(mode==11)assert(af_ap_runtime_send_recipe(1,&preset,image,sizeof image,1000)==AF_INVALID&&!allocations);
 assert(af_ap_runtime_send_recipe(7,&preset,image,sizeof image,0)==AF_INVALID&&!allocations);
 assert(!af_recipe_rx_init(&receiver,71,AF_RECIPE_CAP_FULL));
 int result=mode>=7?af_ap_runtime_send_stored_recipe(7,&preset,capture,image,1000):
  af_ap_runtime_send_recipe(7,&preset,image,sizeof image,1000);
 if(mode==8||mode==9){
  assert(result==(mode==8?AF_IO:AF_STALE)&&!allocations&&!af_ap_runtime_last_attempted_version());
  assert(!af_ap_runtime_send_recipe(7,&preset,image,sizeof image,1000)&&frames==28&&seen==1);return 0;
 }
 if(mode==3||mode==5||mode==6){
  assert(result==AF_IO&&frames==(mode==3?5:mode==5?27:28)&&af_ap_runtime_last_attempted_version()==1);
  assert(seen==(mode==6?1:0));
  assert(af_ap_runtime_preset_status()==AF_IO);
  assert(af_ap_runtime_send_preset(7,&native)==AF_IO&&allocations==(mode==3?5:28));return 0;
 }
 assert(result==AF_OK&&frames==28&&allocations==28&&af_ap_runtime_last_attempted_version()==1);
 AfRecipeAck reply,unchanged;memset(&reply,0xa5,sizeof reply);unchanged=reply;
 assert(af_ap_runtime_recipe_result(&reply)==AF_BUSY&&!memcmp(&reply,&unchanged,sizeof reply));
 assert(af_ap_runtime_send_preset(7,&native)==AF_BUSY&&af_ap_runtime_release_preset()==AF_BUSY&&allocations==28);
 if(mode==2){
  now=1100;void *out=(void *)1;
  assert(!af_ap_runtime_next(0x80020002u,&out)&&!out&&waited==50);
  assert(af_ap_runtime_preset_status()==AF_IO);
  assert(af_ap_runtime_recipe_result(&reply)==AF_IO&&af_ap_runtime_send_preset(7,&native)==AF_IO&&allocations==28);return 0;
 }
 assert(af_ap_runtime_reply(acknowledgment,0x123,128)==0);
 assert(af_ap_runtime_recipe_result(&reply)==AF_BUSY);
 uint8_t invalid[128];memcpy(invalid,acknowledgment,128);invalid[50]^=1;
 assert(af_ap_runtime_reply(invalid,0x90030001u,128)==1&&af_ap_runtime_recipe_result(&reply)==AF_BUSY);
 assert(af_ap_runtime_reply(acknowledgment,0x90030001u,128)==1&&!af_ap_runtime_recipe_result(&reply));
 assert(reply.session==71&&reply.version==1&&reply.slot==7&&reply.status==(mode==1?AF_INVALID:AF_OK));
 assert(!memcmp(reply.payload_sha256,preset.payload_sha256,32));
 assert(!af_ap_runtime_send_preset(7,&native)&&seen==2&&af_ap_runtime_last_attempted_version()==2);
 assert(!af_ap_runtime_send_recipe(20,&preset,image,sizeof image,1000)&&frames==56&&seen==3);
 assert(af_ap_runtime_reply(acknowledgment,0x90030001u,128)==1&&!af_ap_runtime_recipe_result(&reply)&&reply.version==3);
 if(mode!=11){
  assert(!af_ap_runtime_send_recipe(1,&preset,image,sizeof image,1000)&&frames==84&&seen==4);
  assert(af_ap_runtime_reply(acknowledgment,0x90030001u,128)==1&&!af_ap_runtime_recipe_result(&reply)&&reply.slot==1&&reply.version==4);
 }
 return 0;
}
'''


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    folder = tmp_path_factory.mktemp('ap-recipe-sender')
    source, binary = folder / 'contract.c', folder / 'contract'
    source.write_text(HARNESS)
    files = ('af_runtime_ap406.c', 'af_runtime.c', 'af_handshake.c', 'af_apply_wire.c',
             'af_recipe_transport.c', 'af_joint_asset.c', 'af_sha256.c', 'af_joint.c', 'af_slots.c')
    command = ['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-DAF_CP_PRESET406=1', '-DAF_FACTORY_RESTORE406=1', '-DAF_SNAPSHOT_OVERLAY406=1',
               '-DAF_RECIPE_BRIDGE406=1', '-I'+str(NATIVE), str(source),
               *[str(NATIVE / name) for name in files], '-o', str(binary)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize('mode', [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11], ids=[
    'prepared', 'consumer-reject', 'ack-timeout', 'partial-send', 'old-capability',
    'timeout-during-end-allocation', 'late-driver-commit-unknown',
    'stored-capture-real-session-reentrant-busy', 'capture-failure-no-version', 'capture-identity-mismatch',
    'old-full-peer-cannot-replace-first-six'])
def test_actual_sender_ack_and_shared_version(executable, mode):
    run = subprocess.run([str(executable), str(mode)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


@pytest.fixture(scope='module')
def sector_executable(tmp_path_factory):
    folder=tmp_path_factory.mktemp('ap-sector-sender');source=folder/'contract.c';binary=folder/'contract'
    source.write_text(HARNESS.split('static int capture(')[0]+r'''
int main(int argc,char **argv){
 assert(argc==2);unsigned enabled=(unsigned)atoi(argv[1]);
 AfJointAsset a={.native_mode=1,.matrix_mode=1};a.model_sha256[0]=31;
 for(unsigned i=0;i<129;++i)a.native_seed[i]=a.recipe.gamma[i]=i*512;
 for(unsigned i=0;i<288;++i)a.sector_matrix[i]=(int16_t)(i%17-8);
 uint8_t image[AF_JOINT_SECTOR_BYTES];size_t bytes=0;
 assert(!af_joint_asset_encode(&a,image,sizeof image,&bytes)&&bytes==sizeof image);
 AfPreset p={.kind=1};p.params[6]=3;p.lut_sha256[0]=7;
 assert(!af_sha256(image,bytes,p.payload_sha256));
 connect(enabled?AF_APPLY_PROTOCOL_REQUIRED:(AF_APPLY_PROTOCOL_REQUIRED&~AF_APPLY_CAP_SECTOR_MATRIX));
 if(!enabled){
  assert(af_ap_runtime_send_recipe(7,&p,image,bytes,1000)==AF_JOINT_ASSET_UNSUPPORTED);
  assert(!allocations&&!af_ap_runtime_last_attempted_version()&&!receiver.magic);return 0;
 }
 assert(!af_recipe_rx_init(&receiver,71,AF_RECIPE_CAP_FULL|AF_RECIPE_CAP_SECTOR));
 assert(!af_ap_runtime_send_recipe(7,&p,image,bytes,1000)&&frames==35&&allocations==35);
 const AfRecipeOwned *o=&receiver.buffers[receiver.active];
 assert(o->asset.matrix_mode==1&&o->message.image_bytes==2483&&!memcmp(o->asset.sector_matrix,a.sector_matrix,576));
 assert(af_ap_runtime_reply(acknowledgment,0x90030001u,128)==1);
 AfRecipeAck ack;assert(!af_ap_runtime_recipe_result(&ack)&&ack.version==1&&!ack.status);
 return 0;
}
''')
    files=('af_runtime_ap406.c','af_runtime.c','af_handshake.c','af_apply_wire.c',
           'af_recipe_transport.c','af_joint_asset.c','af_sha256.c','af_joint.c','af_slots.c')
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-DAF_CP_PRESET406=1','-DAF_FACTORY_RESTORE406=1','-DAF_SNAPSHOT_OVERLAY406=1',
        '-DAF_RECIPE_BRIDGE406=1','-I'+str(NATIVE),str(source),
        *[str(NATIVE/name) for name in files],'-o',str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    return binary


@pytest.mark.parametrize('enabled',[0,1],ids=['missing-sector-capability','actual-thirty-five-frame-sender'])
def test_actual_sector_sender_requires_explicit_negotiated_capability(sector_executable,enabled):
    run=subprocess.run([str(sector_executable),str(enabled)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
