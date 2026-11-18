"""仓库标记schema保持，显式文档schema兼容混合记录；只使用pytest临时目录。"""
from pathlib import Path
import importlib.util
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'native'
SHARED = NATIVE.parent
spec = importlib.util.spec_from_file_location('repository_existing_contract', SHARED / 'tests/test_native_repository.py')
existing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(existing)

EXTRA = r'''
static size_t exact_file(int fd,const char *name,uint8_t *out,size_t capacity){
 int f=openat(fd,name,O_RDONLY);assert(f>=0);struct stat st;
 assert(!fstat(f,&st)&&st.st_size>=0&&(size_t)st.st_size<=capacity);
 size_t size=(size_t)st.st_size,at=0;
 while(at<size){ssize_t n=read(f,out+at,size-at);assert(n>0);at+=(size_t)n;}
 uint8_t extra;assert(read(f,&extra,1)==0&&close(f)==0);return size;
}
static void same_file(int fd,const char *name,const uint8_t *expected,size_t bytes){
 uint8_t now[4096+32];assert(exact_file(fd,name,now,sizeof now)==bytes&&!memcmp(expected,now,bytes));
}
static int open_documents(int fd,uint32_t marker,uint32_t documents){
 af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 return af_repository_open_documents(&repository,fd,0,marker,documents,4096,&buffers,&catalog,&labels);
}
static void fixture_lut(void){
 /* 显式构造完整研究格式夹具，不伪称来自机身颜色标定或真实LUT拟合。 */
 AfJointAsset a={0};a.base=17;a.model_sha256[0]=0x25;
 for(unsigned i=0;i<129;++i)a.recipe.gamma[i]=i*1024;
 uint8_t image[AF_JOINT_ASSET_BYTES];size_t n=0;
 assert(af_joint_asset_encode(&a,image,sizeof image,&n)==AF_OK&&n==sizeof image);
 AfDocument d={0};d.present=1;d.schema=AF_JOINT_ASSET_SCHEMA;d.converter=1;
 d.initial.base=17;d.initial.kind=1;d.initial.params[6]=3;d.initial.lut_sha256[0]=0x61;
 assert(af_sha256(image,sizeof image,d.initial.payload_sha256)==0);d.saved=d.initial;
 d.name="完整LUT";d.name_bytes=strlen(d.name);d.image=image;d.image_bytes=n;
 d.report.samples=4;d.report.scope=1;memcpy(d.report.model_sha256,a.model_sha256,32);
 assert(af_persist_replace(&catalog,&repository.stores[7],&repository.io,&buffers,&d,0)==AF_STORE_OK);
 assert(af_labels_from_store(&labels,&catalog,&repository.stores[7],&buffers,0)==AF_STORE_OK);
}
static void schema_compatibility(int fd){
 open_repository(fd);AfApManageRequest q=create_request(7);run(&q);
 uint8_t marker[96],old[4096+32];
 size_t marker_bytes=exact_file(fd,"A7LOOKS1/STORE.ID",marker,sizeof marker);
 size_t old_bytes=exact_file(fd,"A7LOOKS1/C07_A.rec",old,sizeof old);
 assert(marker_bytes==96&&!memcmp(marker+16,"\0\0\0\0",4));
 assert(af_repository_close(&repository)==0);
 assert(open_documents(fd,0,AF_JOINT_ASSET_SCHEMA)==AF_STORE_OK);
 assert(repository.schema==AF_JOINT_ASSET_SCHEMA&&repository.stores[6].schema==AF_JOINT_ASSET_SCHEMA);
 assert(catalog.slots[6].present&&!catalog.slots[6].working.kind&&catalog.slots[6].saved_revision==1);
 same_file(fd,"A7LOOKS1/STORE.ID",marker,marker_bytes);same_file(fd,"A7LOOKS1/C07_A.rec",old,old_bytes);
 fixture_lut();q=create_request(20);run(&q);
 uint8_t lut[4096+32],pure[4096+32];
 size_t lut_bytes=exact_file(fd,"A7LOOKS1/C08_A.rec",lut,sizeof lut);
 size_t pure_bytes=exact_file(fd,"A7LOOKS1/C20_A.rec",pure,sizeof pure);
 assert(af_repository_close(&repository)==0);
 assert(open_documents(fd,0,AF_JOINT_ASSET_SCHEMA)==AF_STORE_OK);
 assert(catalog.slots[6].present&&catalog.slots[7].present&&catalog.slots[19].present);
 assert(catalog.slots[7].saved.kind==1&&catalog.slots[7].saved_revision==1&&!strcmp(labels.slots[7].text,"完整LUT"));
 AfDocument restored;AfJointAsset asset;
 assert(af_repository_recover(&repository,8)==AF_STORE_OK);
 assert(af_store_snapshot(&repository.stores[7],&buffers,&restored)==AF_STORE_OK);
 assert(restored.image_bytes==AF_JOINT_ASSET_BYTES&&af_import_asset(&restored,&asset)==AF_OK&&asset.base==17);
 assert(af_repository_close(&repository)==0);
 /* 文档schema不匹配仍隔离LUT，纯参数可读；原open(0)保持同样的旧语义。 */
 for(unsigned i=0;i<2;++i){
  af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
  int status=i?af_repository_open(&repository,fd,0,0,4096,&buffers,&catalog,&labels):open_documents(fd,0,0x12345678u);
  assert(status==AF_REPOSITORY_PARTIAL&&repository.status[7]==AF_STORE_UNSUPPORTED);
  assert(repository.error_mask==(1u<<7)&&catalog.slots[6].present&&catalog.slots[19].present&&!catalog.slots[7].present);
  assert(!repository.stores[7].ready&&af_repository_close(&repository)==0);
 }
 same_file(fd,"A7LOOKS1/STORE.ID",marker,marker_bytes);same_file(fd,"A7LOOKS1/C07_A.rec",old,old_bytes);
 same_file(fd,"A7LOOKS1/C08_A.rec",lut,lut_bytes);same_file(fd,"A7LOOKS1/C20_A.rec",pure,pure_bytes);
 /* 错误仓库标记仍整库拒绝，不能自动重写STORE.ID。 */
 assert(open_documents(fd,AF_JOINT_ASSET_SCHEMA,AF_JOINT_ASSET_SCHEMA)==AF_STORE_UNSUPPORTED);
 assert(!repository.opened&&!catalog.slots[6].present&&!catalog.slots[7].present);
 same_file(fd,"A7LOOKS1/STORE.ID",marker,marker_bytes);same_file(fd,"A7LOOKS1/C07_A.rec",old,old_bytes);
}
int main(int argc,char **argv){assert(argc==2);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);schema_compatibility(fd);assert(close(fd)==0);return 0;}
'''


def test_marker_zero_allows_explicit_mixed_documents_without_changing_old_bytes(tmp_path):
    source = tmp_path / 'schema.c'
    harness = existing.HARNESS.split('int main(int argc,char **argv)')[0]
    source.write_text(harness.replace('#include "af_repository.h"', '#include "af_repository.h"\n#include "af_sha256.h"') + EXTRA)
    names = ['af_repository.c', 'af_media.c', 'af_posix.c', 'af_labels.c', 'af_labels_store.c', 'af_ap_manage.c',
             'af_persist.c', 'af_store.c', 'af_document.c', 'af_record.c', 'af_sha256.c', 'af_slots.c', 'af_ui.c',
             'af_import.c', 'af_joint.c', 'af_joint_fit.c', 'af_joint_asset.c', 'af_joint_report.c', 'af_grid.c', 'af_grid_fit.c', 'af_cube.c']
    binary = tmp_path / 'schema'
    command = ['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-I' + str(NATIVE), str(source),
               *[str(NATIVE / n) for n in names], str(SHARED / 'tests/native_joint_target.c'), '-o', str(binary)]
    run = subprocess.run(command, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    directory = tmp_path / 'library'
    directory.mkdir(mode=0o700)
    run = subprocess.run([str(binary), str(directory)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
