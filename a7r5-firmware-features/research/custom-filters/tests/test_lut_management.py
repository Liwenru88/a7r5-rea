"""完整研究LUT的管理事务：真实临时文件，不把夹具当颜色模型或机身结果。"""
import subprocess

import pytest

from test_native_repository import HARNESS, NATIVE

EXTRA = r'''
#include "af_sha256.h"
static uint8_t asset_image[AF_JOINT_ASSET_BYTES],exported[AF_DOCUMENT_MAX];
static AfFitReport expected_report;
static void open_mixed(int fd){
 af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 assert(af_repository_open_documents(&repository,fd,1,0,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==0);
}
static void seed_document(void){
 /* 来源和误差都是明确的格式夹具，不声明本机标定或真实CUBE拟合。 */
 AfJointAsset asset={0};asset.base=18;asset.model_sha256[0]=0x32;
 for(unsigned i=0;i<129;++i)asset.recipe.gamma[i]=i*1024;
 asset.recipe.grid[13]=7;asset.recipe.matrix[2]=-3;asset.recipe.cc1[7]=11;size_t bytes;
 assert(af_joint_asset_encode(&asset,asset_image,sizeof(asset_image),&bytes)==0);
 AfDocument d={0};d.present=1;d.schema=AF_JOINT_ASSET_SCHEMA;d.converter=1;
 d.initial.base=18;d.initial.kind=1;d.initial.params[6]=3;d.initial.params[0]=-2;
 d.initial.lut_sha256[0]=0x53;assert(af_sha256(asset_image,bytes,d.initial.payload_sha256)==0);
 d.saved=d.initial;d.image=asset_image;d.image_bytes=bytes;d.name="Film";d.name_bytes=4;
 d.report.samples=4;d.report.scope=1;memcpy(d.report.model_sha256,asset.model_sha256,32);
 expected_report=d.report;
 assert(af_persist_replace(&catalog,&repository.stores[6],&repository.io,&buffers,&d,0)==0);
 assert(af_labels_from_store(&labels,&catalog,&repository.stores[6],&buffers,0)==0);
}
static void complete_doc(uint32_t slot){
 assert(af_repository_recover(&repository,slot)==0);AfDocument d;AfJointAsset asset;
 assert(af_store_snapshot(&repository.stores[slot-1],&buffers,&d)==0&&af_import_asset(&d,&asset)==0);
 assert(d.image_bytes==sizeof(asset_image)&&!memcmp(d.image,asset_image,sizeof(asset_image)));
 assert(!memcmp(&d.report,&expected_report,sizeof(expected_report)));
}
static void flow_lut(int fd){
 open_mixed(fd);seed_document();assert(af_edit(&catalog,7,0,4)==0);
 AfSlot source=catalog.slots[6];AfApManageRequest q={0};q.op=AF_MANAGE_RENAME;
 q.source_slot=q.target_slot=7;q.name_bytes=9;memcpy(q.name,"胶片LUT",9);
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0&&af_repository_execute(&repository,&manager,0)==0);
 assert(catalog.slots[6].saved_revision==2&&af_dirty(&catalog,7)==1);
 assert(!memcmp(&catalog.slots[6].initial,&source.initial,sizeof(AfPreset))&&
        !memcmp(&catalog.slots[6].saved,&source.saved,sizeof(AfPreset))&&
        !memcmp(&catalog.slots[6].working,&source.working,sizeof(AfPreset)));
 q=(AfApManageRequest){0};q.op=AF_MANAGE_COPY;q.source_slot=7;q.target_slot=20;
 q.name_bytes=4;memcpy(q.name,"Copy",4);run(&q);
 assert(catalog.slots[19].working.params[0]==4&&catalog.slots[19].initial.params[0]==-2);
 assert(af_dirty(&catalog,7)==1&&catalog.slots[6].saved_revision==2);
 int library;assert(mkdirat(fd,"library",0700)==0);
 library=openat(fd,"library",O_RDONLY|O_DIRECTORY);assert(library>=0);
 q=(AfApManageRequest){0};q.op=AF_MANAGE_EXPORT;q.source_slot=q.target_slot=7;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0&&
        af_repository_export(&repository,&manager,library,exported,sizeof(exported))==0);
 assert(af_dirty(&catalog,7)==1&&manager.receipt.generation==2);
 int f=openat(library,"C07_G0000000000000002.a7filter",O_RDONLY);assert(f>=0);
 uint8_t file[4096];ssize_t count=read(f,file,sizeof(file));assert(count>1943&&close(f)==0);
 AfDocument d;assert(af_document_decode(file,(size_t)count,AF_JOINT_ASSET_SCHEMA,&d)==0);
 assert(d.saved.params[0]==-2&&d.initial.kind==1&&!memcmp(d.image,asset_image,sizeof(asset_image)));
 assert(af_document_report_applies(&d,&d.saved)==1);
 assert(af_document_report_applies(&d,&catalog.slots[6].working)==0);
 q=(AfApManageRequest){0};q.op=AF_MANAGE_SAVE;q.source_slot=q.target_slot=7;run(&q);
 assert(!af_dirty(&catalog,7)&&catalog.slots[6].saved.params[0]==4);
 complete_doc(20);complete_doc(7);assert(catalog.slots[6].saved.params[0]==4);
 q=(AfApManageRequest){0};q.op=AF_MANAGE_CLEAR;q.target_slot=20;q.overwrite=1;run(&q);
 assert(!catalog.slots[19].present&&catalog.slots[19].saved_revision==2);
 assert(af_repository_close(&repository)==0&&close(library)==0);open_mixed(fd);
 assert(catalog.slots[6].saved.params[0]==4&&!catalog.slots[19].present&&catalog.slots[19].saved_revision==2);
 assert(labels.slots[6].bytes==9&&!memcmp(labels.slots[6].text,"胶片LUT",9));
 complete_doc(7);assert(af_repository_close(&repository)==0);
}
static void reject_lut(int fd){
 open_mixed(fd);seed_document();AfCatalog before=catalog;AfLabels names=labels;
 AfApManageRequest q={0};q.op=AF_MANAGE_RENAME;q.source_slot=q.target_slot=7;q.name_bytes=4;memcpy(q.name,"Name",4);
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);assert(af_edit(&catalog,7,0,3)==0);
 assert(af_repository_execute(&repository,&manager,0)==AF_STALE&&manager.phase==AF_MANAGE_FAILED);
 assert(catalog.slots[6].saved_revision==1&&catalog.slots[6].saved.params[0]==-2&&af_dirty(&catalog,7)==1);
 assert(!memcmp(&labels,&names,sizeof(labels)));catalog=before;
 /* 同代旧载荷损坏不能仅凭内存kind/hash继续改名或导出。 */
 int f=openat(repository.posix.directory,"C07_A.rec",O_RDWR);assert(f>=0);uint8_t x;
 assert(pread(f,&x,1,400)==1);x^=1;assert(pwrite(f,&x,1,400)==1&&close(f)==0);
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_repository_execute(&repository,&manager,0)==AF_STORE_CORRUPT);
 assert(!manager.receipt.durable&&!memcmp(&before,&catalog,sizeof(catalog))&&!memcmp(&labels,&names,sizeof(labels)));
 assert(af_repository_close(&repository)==0);
}
int main(int argc,char **argv){assert(argc==3);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);
 if(argv[2][0]=='f')flow_lut(fd);else reject_lut(fd);assert(close(fd)==0);return 0;}
'''


@pytest.fixture(scope='module')
def lut_driver(tmp_path_factory):
    folder = tmp_path_factory.mktemp('lut-management')
    source, binary = folder / 'driver.c', folder / 'driver'
    source.write_text(HARNESS.split('int main(int argc,char **argv)')[0]+EXTRA)
    names = ('af_repository.c', 'af_repository_service.c', 'af_repository_import.c', 'af_media.c', 'af_posix.c',
             'af_labels.c', 'af_labels_store.c', 'af_ap_manage.c', 'af_persist.c', 'af_store.c', 'af_document.c',
             'af_record.c', 'af_sha256.c', 'af_slots.c', 'af_ui.c', 'af_import.c', 'af_joint.c', 'af_joint_fit.c',
             'af_joint_asset.c', 'af_joint_report.c', 'af_grid.c', 'af_grid_fit.c', 'af_cube.c')
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                          '-I'+str(NATIVE), str(source), *[str(NATIVE/n) for n in names],
                          str(NATIVE.parent/'tests/native_joint_target.c'), '-o', str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return binary


@pytest.mark.parametrize('case', ['flow', 'reject'])
def test_complete_lut_management_preserves_assets_and_saved_state(lut_driver, tmp_path, case):
    run = subprocess.run([str(lut_driver), str(tmp_path), case], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
