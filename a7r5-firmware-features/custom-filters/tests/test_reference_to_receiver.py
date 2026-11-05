"""同一参考配方从求解到真实仓库再到Rx；域映射为数学用例，无机身精度声明。"""
import ctypes as c
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from joint_support import Model
from test_native_persistence import Document
from test_native_repository import HARNESS
from test_reference_import_pipeline import api, reference, request, convert

NATIVE=Path(__file__).resolve().parents[1]/'native'
DRIVER=r'''
#include "af_repository_recipe.h"
static unsigned char source_document[4096],expected_image[AF_JOINT_ASSET_BYTES];
static unsigned char expected_model[32],expected_payload[32];
static AfRecipeTx transmitted;
static AfRecipeRx received;
static AfJointAssetDecodeWork decoded;
static void print_hex(const uint8_t value[32]){for(unsigned i=0;i<32;++i)printf("%02x",value[i]);}
int main(int argc,char **argv){
 assert(argc==2);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);
 int source=openat(fd,"reference.a7filter",O_RDONLY);struct stat st;
 assert(source>=0&&fstat(source,&st)==0&&st.st_size>0&&(uint64_t)st.st_size<=sizeof(source_document));
 size_t at=0;while(at<(size_t)st.st_size){ssize_t n=read(source,source_document+at,(size_t)st.st_size-at);assert(n>0);at+=(size_t)n;}
 assert(close(source)==0);AfDocument document;
 assert(af_document_decode(source_document,at,AF_JOINT_ASSET_SCHEMA,&document)==AF_DOCUMENT_OK);
 assert(document.present&&document.initial.kind==1&&document.saved.kind==1&&document.image_bytes==sizeof(expected_image));
 memcpy(expected_image,document.image,sizeof(expected_image));
 memcpy(expected_model,document.report.model_sha256,sizeof(expected_model));
 memcpy(expected_payload,document.saved.payload_sha256,sizeof(expected_payload));
 assert(!memcmp(expected_model,expected_image+64,32));
 af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 assert(af_repository_open(&repository,fd,1,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==AF_STORE_OK);
 assert(af_persist_replace(&catalog,&repository.stores[6],&repository.io,&buffers,&document,0)==AF_STORE_OK);
 assert(af_labels_from_store(&labels,&catalog,&repository.stores[6],&buffers,0)==AF_STORE_OK);
 assert(catalog.slots[6].saved_revision==1&&catalog.slots[6].saved.kind==1);
 assert(af_repository_close(&repository)==AF_STORE_OK);
 /* 删除转换输入，并清空全部易失目录/原文档/复用缓冲。恢复只依赖机内副本。 */
 assert(unlinkat(fd,"reference.a7filter",0)==0);
 memset(source_document,0,sizeof(source_document));memset(memory,0,sizeof(memory));
 af_catalog_init(&catalog);af_labels_init(&labels);
 assert(af_repository_open(&repository,fd,0,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==AF_STORE_OK);
 assert(catalog.slots[6].saved_revision==1&&catalog.slots[6].working.kind==1);
 assert(!memcmp(catalog.slots[6].working.payload_sha256,expected_payload,32));
 assert(af_edit(&catalog,7,0,7)==AF_OK&&af_edit(&catalog,7,1,-4)==AF_OK&&af_dirty(&catalog,7)==1);
 AfSlot before=catalog.slots[6];
 memset(memory,0x5a,sizeof(memory));
 assert(af_repository_recipe_capture(&repository,7,1,0x123456789abcdef0ULL,29,&transmitted)==AF_STORE_OK);
 assert(!memcmp(&before,&catalog.slots[6],sizeof(before))&&af_dirty(&catalog,7)==1);
 /* 再次复用三缓冲后发送，确保包来自独立不可变副本。 */
 memset(memory,0xa5,sizeof(memory));
 assert(af_repository_recipe_current(&repository,&transmitted,1)==AF_STORE_OK);
 assert(af_recipe_rx_init(&received,0x123456789abcdef0ULL,AF_RECIPE_CAP_FULL)==AF_OK);
 for(unsigned i=0;i<AF_RECIPE_TOTAL_FRAMES;++i){uint8_t frame[AF_RECIPE_FRAME_BYTES];
  assert(af_recipe_tx_frame(&transmitted,i,frame,sizeof(frame))==AF_OK);
  assert(af_recipe_rx_frame(&received,frame,sizeof(frame))==AF_OK);
 }
 assert(af_recipe_rx_validate(&received,&decoded)==AF_OK);
 AfRecipeLease lease;const AfRecipeOwned *value;
 assert(af_recipe_rx_take(&received,&lease,&value)==AF_OK);
 assert(value->message.slot==7&&value->message.version==29&&value->asset.base==catalog.slots[6].working.base);
 assert(!memcmp(value->message.image,expected_image,sizeof(expected_image))&&!memcmp(value->asset.model_sha256,expected_model,32));
 assert(!memcmp(&value->message.preset,&catalog.slots[6].working,sizeof(AfPreset)));
 assert(value->message.preset.params[0]==7&&value->message.preset.params[1]==-4);
 uint8_t ack_bytes[AF_RECIPE_FRAME_BYTES];AfRecipeAck ack;
 assert(af_recipe_rx_finish(&received,&lease,AF_OK,ack_bytes,sizeof(ack_bytes))==AF_OK);
 assert(af_recipe_tx_ack(&transmitted,ack_bytes,sizeof(ack_bytes),&ack)==AF_OK);
 assert(ack.status==AF_OK&&ack.version==29&&ack.slot==7&&!memcmp(ack.payload_sha256,expected_payload,32));
 assert(af_recipe_rx_release(&received,&lease)==AF_OK);
 assert(af_repository_close(&repository)==AF_STORE_OK&&close(fd)==0);
 printf("{\"status\":\"PASS_REFERENCE_TO_RX_OFFLINE\",\"frames\":%u,\"payload_sha256\":\"",AF_RECIPE_TOTAL_FRAMES);
 print_hex(expected_payload);printf("\",\"model_sha256\":\"");print_hex(expected_model);
 printf("\",\"params\":[7,-4],\"camera_verified\":false}\n");return 0;
}
'''


@pytest.fixture(scope='module')
def receiver_driver(tmp_path_factory):
    folder=tmp_path_factory.mktemp('reference-to-receiver')
    source=folder/'driver.c';binary=folder/'driver'
    # 复用仓库已有完整搭建，保留原入口为未调用的普通函数，避免复制另一套仓库模拟。
    source.write_text(HARNESS.replace('int main(', 'int existing_repository_harness_main(')+'\n'+DRIVER)
    # 与test_repository_recipe相同的实际后端清单，所有文件I/O仍走原AfRepository。
    names=['af_repository_recipe.c','af_recipe_transport.c','af_repository.c','af_repository_service.c',
           'af_repository_import.c','af_media.c','af_posix.c','af_labels.c','af_labels_store.c','af_ap_manage.c',
           'af_persist.c','af_store.c','af_document.c','af_record.c','af_sha256.c','af_slots.c','af_ui.c',
           'af_import.c','af_joint.c','af_joint_fit.c','af_joint_asset.c','af_joint_report.c',
           'af_grid.c','af_grid_fit.c','af_cube.c']
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),
                           str(source),*[str(NATIVE/name) for name in names],
                           str(NATIVE.parent/'tests/native_joint_target.c'),'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return binary


def test_same_reference_recipe_survives_durable_reopen_dirty_edit_and_full_rx(api,receiver_driver,tmp_path):
    state,config,workspace,baseline,prepared,seed,owners=reference.setup(api)
    q=request(api,lambda r,g,b:(r*.97,g*.99,b*.98))
    q.initial.params[:]=config.reference_params
    model=Model();assert api.af_reference_joint_model(state,c.byref(q.initial),c.byref(model))==0
    q._model=model;q.model=c.pointer(model);q._seed=seed;q.seed=c.pointer(seed)
    candidate=convert(api,q)
    assert candidate.fit.attempted_components==15 and candidate.fit.final_mse<=candidate.fit.initial_mse
    assert bytes(candidate.report.model_sha256)==bytes(model.model_sha256)
    info=reference.Info();assert api.af_reference_joint_info(state,c.byref(info))==0
    assert info.research_only==1 and info.camera_apply_allowed==0
    assert bytes(info.grid_source_sha256)==bytes(config.grid_source_sha256)
    document=Document();assert api.af_import_document(c.byref(candidate),c.byref(document))==0
    api.af_document_encode.argtypes=[c.POINTER(Document),c.c_uint32,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
    encoded=c.create_string_buffer(4096);written=c.c_size_t()
    assert api.af_document_encode(c.byref(document),0x314a4641,encoded,4096,c.byref(written))==0
    source=tmp_path/'reference.a7filter';source.write_bytes(encoded.raw[:written.value])
    result=subprocess.run([str(receiver_driver),str(tmp_path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    receipt=json.loads(result.stdout)
    assert receipt==dict(status='PASS_REFERENCE_TO_RX_OFFLINE',frames=28,
                        payload_sha256=hashlib.sha256(bytes(candidate.image)).hexdigest(),
                        model_sha256=bytes(model.model_sha256).hex(),params=[7,-4],camera_verified=False)
    assert not source.exists() and (tmp_path/'A7LOOKS1/C07_A.rec').is_file()
