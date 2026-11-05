"""实际文件仓库到独立发送副本；复用现有LUT保存测试搭建，不操作设备。"""
from pathlib import Path
import subprocess

import pytest

from test_native_repository import HARNESS

NATIVE=Path(__file__).resolve().parents[1]/'native'
ADDED=r'''
#include "af_repository_recipe.h"
#include "af_sha256.h"
static AfRecipeTx tx;
static AfRecipeRx rx;
static AfJointAssetDecodeWork decode_work;
static unsigned io_calls;
static int forbidden_read(void *p,uint32_t s,uint32_t b,void *o,size_t c,size_t *n){
 (void)p;(void)s;(void)b;(void)o;(void)c;(void)n;++io_calls;return -1;
}
static void recipe_prepare(int fd){
 imported(fd,0);af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 assert(af_repository_open(&repository,fd,0,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==0);
 assert(catalog.slots[7].saved.kind==1&&catalog.slots[7].saved_revision==1);
 assert(af_edit(&catalog,8,0,7)==0&&af_edit(&catalog,8,1,-4)==0&&af_dirty(&catalog,8)==1);
}
static void recipe_flow(int fd){
 recipe_prepare(fd);AfCatalog before=catalog;AfLabels names=labels;AfStore original=repository.stores[7];
 /* 前一操作已复用全部缓冲，内存snapshot失效；capture必须显式重读。 */
 memset(memory,0xa5,sizeof(memory));AfDocument d;
 assert(af_store_snapshot(&repository.stores[7],&buffers,&d)==AF_STORE_STALE);
 assert(af_repository_recipe_capture(&repository,8,1,123,91,&tx)==AF_STORE_OK);
 assert(!memcmp(&before,&catalog,sizeof(before))&&!memcmp(&names,&labels,sizeof(names))&&
        !memcmp(&original,&repository.stores[7],sizeof(original))&&af_dirty(&catalog,8)==1);
 uint8_t image[AF_JOINT_ASSET_BYTES];memcpy(image,tx.message.image,sizeof(image));
 assert(!memcmp(image,candidate.image,sizeof(image))&&tx.message.preset.params[0]==7&&tx.message.preset.params[1]==-4);
 AfStoreIo io=repository.io;repository.io.read=forbidden_read;io_calls=0;
 memset(memory,0x5a,sizeof(memory));
 assert(af_repository_recipe_current(&repository,&tx,1)==AF_STORE_OK&&io_calls==0);
 assert(af_recipe_rx_init(&rx,123,AF_RECIPE_CAP_FULL)==AF_OK);
 for(unsigned i=0;i<AF_RECIPE_TOTAL_FRAMES;++i){uint8_t frame[128];
  assert(af_recipe_tx_frame(&tx,i,frame,sizeof(frame))==AF_OK&&af_recipe_rx_frame(&rx,frame,sizeof(frame))==AF_OK);}
 assert(af_recipe_rx_validate(&rx,&decode_work)==AF_OK);AfRecipeLease lease;const AfRecipeOwned *owned;
 assert(af_recipe_rx_take(&rx,&lease,&owned)==AF_OK&&!memcmp(owned->message.image,image,sizeof(image)));
 assert(owned->message.preset.params[0]==7&&owned->message.preset.params[1]==-4);
 uint8_t ack[128];assert(af_recipe_rx_finish(&rx,&lease,AF_OK,ack,sizeof(ack))==AF_OK);
 assert(af_recipe_rx_release(&rx,&lease)==AF_OK);repository.io=io;
 assert(af_repository_close(&repository)==AF_STORE_OK);
}
static void recipe_stale(int fd,unsigned which){
 recipe_prepare(fd);assert(af_repository_recipe_capture(&repository,8,1,123,91,&tx)==AF_STORE_OK);
 if(which==0)assert(af_edit(&catalog,8,0,6)==AF_OK);
 else if(which==1){AfApManageRequest q={0};q.op=AF_MANAGE_SAVE;q.source_slot=q.target_slot=8;run(&q);}
 else if(which==2)assert(af_persist_clear(&catalog,&repository.stores[7],&repository.io,&buffers)==AF_STORE_OK);
 else{AfSave save;assert(af_begin_save(&catalog,8,&save)==AF_OK);}
 assert(af_repository_recipe_current(&repository,&tx,1)==AF_STORE_STALE);
 assert(af_repository_close(&repository)==AF_STORE_OK);
}
static void recipe_rejected(int fd,unsigned which){
 recipe_prepare(fd);memset(&tx,0xa5,sizeof(tx));AfRecipeTx untouched=tx;
 if(which==0){
  void *aliases[]={&repository,&catalog,&labels,memory[0],memory[1],memory[2]};
  AfCatalog original=catalog;AfLabels names=labels;AfRepository repo=repository;uint8_t saved_memory[sizeof(memory)];memcpy(saved_memory,memory,sizeof(memory));
  for(unsigned i=0;i<sizeof(aliases)/sizeof(aliases[0]);++i){
   assert(af_repository_recipe_capture(&repository,8,1,123,91,aliases[i])==AF_STORE_INVALID);
   assert(!memcmp(&original,&catalog,sizeof(original))&&!memcmp(&names,&labels,sizeof(names))&&
          !memcmp(&repo,&repository,sizeof(repo))&&!memcmp(saved_memory,memory,sizeof(memory)));}
 }else if(which==1){
  assert(af_repository_recipe_capture(&repository,8,2,123,91,&tx)==AF_STORE_STALE);
  assert(af_repository_recipe_capture(&repository,0,1,123,91,&tx)==AF_STORE_INVALID);
  assert(af_repository_recipe_capture(&repository,6,1,123,91,&tx)==AF_STORE_STALE);
 }else if(which==2){
  repository.stores[7].uncertain=1;AfStore original=repository.stores[7];
  assert(af_repository_recipe_capture(&repository,8,1,123,91,&tx)==AF_STORE_UNCERTAIN);
  assert(!memcmp(&original,&repository.stores[7],sizeof(original)));
 }else if(which==3){
  int f=openat(repository.posix.directory,"C08_A.rec",O_WRONLY|O_TRUNC);assert(f>=0&&write(f,"bad",3)==3&&close(f)==0);
  AfSlot original=catalog.slots[7];AfStore store=repository.stores[7];
  assert(af_repository_recipe_capture(&repository,8,1,123,91,&tx)==AF_STORE_CORRUPT);
  assert(!memcmp(&original,&catalog.slots[7],sizeof(original))&&!memcmp(&store,&repository.stores[7],sizeof(store)));
 }else{
  /* 最新B损坏时recover可选A旧代，但capture不得自动回退catalog。 */
  AfApManageRequest q={0};q.op=AF_MANAGE_SAVE;q.source_slot=q.target_slot=8;run(&q);
  assert(catalog.slots[7].saved_revision==2&&repository.stores[7].bank==1);
  int f=openat(repository.posix.directory,"C08_B.rec",O_WRONLY|O_TRUNC);assert(f>=0&&write(f,"bad",3)==3&&close(f)==0);
  AfSlot original=catalog.slots[7];AfStore store=repository.stores[7];
  assert(af_repository_recipe_capture(&repository,8,2,123,91,&tx)==AF_STORE_STALE);
  assert(!memcmp(&original,&catalog.slots[7],sizeof(original))&&!memcmp(&store,&repository.stores[7],sizeof(store)));
 }
 assert(!memcmp(&tx,&untouched,sizeof(tx)));assert(af_repository_close(&repository)==AF_STORE_OK);
}

static void monochrome_recipe(int fd,unsigned base,unsigned mode,unsigned bad){
 recipe_prepare(fd);AfJointAsset a={0},decoded;uint8_t image[AF_JOINT_ASSET_MAX_BYTES],digest[32];size_t bytes;
 a.base=base;a.native_mode=1;a.matrix_mode=mode;a.model_sha256[0]=9;
 for(unsigned i=0;i<129;++i)a.recipe.gamma[i]=a.native_seed[i]=i*1024;
 if(mode){for(unsigned e=0;e<3;++e)for(unsigned s=0;s<16;++s)a.sector_matrix[e*96+s*6]=(int16_t)(s+1);if(bad)a.sector_matrix[96+7*6]++;}
 else{for(unsigned e=0;e<3;++e)a.recipe.matrix[6*e]=7;if(bad)a.recipe.matrix[6]++;}
 /* 旧格式仍能编码/解码、保存、恢复和导出；只有应用前拒绝不可表示配方。 */
 assert(!af_joint_asset_encode(&a,image,sizeof image,&bytes));assert(!af_joint_asset_decode(image,bytes,&decoded));
 AfDocument document={0};document.present=1;document.schema=AF_JOINT_ASSET_SCHEMA;document.converter=af_joint_asset_converter(&a);
 document.initial.base=(uint8_t)base;document.initial.kind=1;document.initial.params[6]=3;document.initial.lut_sha256[0]=7;
 assert(!af_sha256(image,bytes,digest));memcpy(document.initial.payload_sha256,digest,32);document.saved=document.initial;
 document.name="Mono";document.name_bytes=4;document.image=image;document.image_bytes=bytes;document.report.samples=1;document.report.scope=1;memcpy(document.report.model_sha256,a.model_sha256,32);
 assert(!af_store_commit(&repository.stores[7],&repository.io,&buffers,&document));assert(!af_repository_recover(&repository,8));
 assert(catalog.slots[7].saved.base==base&&catalog.slots[7].saved_revision==2);
 memset(&tx,0xa5,sizeof tx);AfRecipeTx untouched=tx;AfCatalog before=catalog;AfStore store=repository.stores[7];
 int status=af_repository_recipe_capture(&repository,8,2,123,91,&tx);assert(status==(bad?AF_STORE_UNSUPPORTED:AF_STORE_OK));
 assert(!memcmp(&before,&catalog,sizeof before)&&!memcmp(&store,&repository.stores[7],sizeof store));
 if(bad)assert(!memcmp(&tx,&untouched,sizeof tx));
 assert(!mkdirat(fd,"mono-export",0700));int library=openat(fd,"mono-export",O_RDONLY|O_DIRECTORY);assert(library>=0);
 AfApManageRequest q={0};q.op=AF_MANAGE_EXPORT;q.source_slot=q.target_slot=8;assert(!af_ap_manage_submit(&manager,&catalog,&q));
 uint8_t exported[4096];assert(!af_repository_export(&repository,&manager,library,exported,sizeof exported));
 int f=openat(library,"C08_G0000000000000002.a7filter",O_RDONLY);assert(f>=0);ssize_t n=read(f,exported,sizeof exported);assert(n>0&&!close(f));
 assert(!af_document_decode(exported,(size_t)n,AF_JOINT_ASSET_SCHEMA,&document));assert(document.image_bytes==bytes&&!memcmp(document.image,image,bytes));
 assert(!af_joint_asset_decode(document.image,document.image_bytes,&decoded));
 assert(!close(library)&&!af_repository_close(&repository));
}
'''


@pytest.fixture(scope='module')
def recipe_driver(tmp_path_factory):
    folder=tmp_path_factory.mktemp('repository-recipe')
    source=folder/'driver.c';binary=folder/'driver'
    main=HARNESS.replace('int main(',ADDED+'\nint main(')
    main=main.replace('default:abort();',"case 'f':recipe_flow(fd);break;case 'g':recipe_stale(fd,0);break;case 'h':recipe_stale(fd,1);break;case 'i':recipe_stale(fd,2);break;case 'j':recipe_stale(fd,3);break;case 'k':recipe_rejected(fd,0);break;case 'l':recipe_rejected(fd,1);break;case 'm':recipe_rejected(fd,2);break;case 'n':recipe_rejected(fd,3);break;case 'o':recipe_rejected(fd,4);break;case 'p':monochrome_recipe(fd,8,0,0);break;case 'q':monochrome_recipe(fd,9,0,0);break;case 'r':monochrome_recipe(fd,8,1,0);break;case 's':monochrome_recipe(fd,9,1,0);break;case 't':monochrome_recipe(fd,8,0,1);break;case 'u':monochrome_recipe(fd,9,0,1);break;case 'v':monochrome_recipe(fd,8,1,1);break;case 'w':monochrome_recipe(fd,9,1,1);break;default:abort();")
    source.write_text(main)
    names=['af_repository_recipe.c','af_recipe_transport.c','af_repository.c','af_repository_service.c',
           'af_repository_import.c','af_media.c','af_posix.c','af_labels.c','af_labels_store.c','af_ap_manage.c',
           'af_persist.c','af_store.c','af_document.c','af_record.c','af_sha256.c','af_slots.c','af_ui.c',
           'af_import.c','af_joint.c','af_joint_fit.c','af_joint_asset.c','af_joint_report.c',
           'af_grid.c','af_grid_fit.c','af_cube.c']
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),
                           str(source),*[str(NATIVE/n) for n in names],
                           str(NATIVE.parent/'tests/native_joint_target.c'),'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return binary


@pytest.mark.parametrize('case',list('fghijklmno'),ids=[
    'durable-lut-dirty-values-owned-roundtrip','working-change-stale','saved-generation-stale',
    'cleared-slot-stale','pending-save-stale','protected-memory-aliases','revision-and-legacy-slot',
    'uncertain-not-recovered','corrupt-source-no-publish','older-bank-never-auto-restored'])
def test_repository_recipe_capture(recipe_driver,tmp_path,case):
    result=subprocess.run([str(recipe_driver),str(tmp_path),case],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('case', list('pqrstuvw'), ids=['BW18','SE18','BW288','SE288','BW18-unsupported','SE18-unsupported','BW288-unsupported','SE288-unsupported'])
def test_legacy_monochrome_storage_exports_but_ambiguous_application_rejects(recipe_driver, tmp_path, case):
    result = subprocess.run([str(recipe_driver), str(tmp_path), case], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
