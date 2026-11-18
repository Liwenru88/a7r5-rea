"""无合成预测器的默认参考导入初始化、实际文件转换及关闭后重绑定。"""
from pathlib import Path
import subprocess

import pytest

from test_native_repository import HARNESS
from test_edit_joint import SOURCES

HOME = Path(__file__).resolve().parents[1]
ROOT = HOME.parents[1]
EXTRA = r'''
#include "af_reference_import.h"
static void default_reference(int fd){
 int status;af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 void *service=af_repository_service_open(fd,&catalog,&labels,&status);assert(service&&status==0);
 /* 完整配方入口不依赖模型；下面仍单独初始化并验证CUBE的默认模型。 */
 assert(af_repository_service_capabilities(service)&AF_MANAGE_CAP(AF_MANAGE_IMPORT));
 assert(af_reference_import_bind(service)==0);
 assert(af_repository_service_capabilities(service)&AF_MANAGE_CAP(AF_MANAGE_IMPORT));
 AfReferenceJointInfo info;assert(af_reference_import_info(service,&info)==0&&info.research_only==1&&!info.camera_apply_allowed);
 static const char text[]="LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n";
 int f=openat(fd,"默认滤镜.cube",O_WRONLY|O_CREAT|O_EXCL,0600);assert(f>=0&&write(f,text,sizeof(text)-1)==sizeof(text)-1&&close(f)==0);
 AfMediaList list;assert(af_media_scan(fd,17,&media_work,&list)==0&&list.count==1);
 AfApMediaImporter importer;assert(af_repository_service_media_importer(service,&importer)==0);
 AfApMediaInfo selected={0};selected.generation=list.generation;selected.index=0;char source[1024];
 assert(af_media_read(fd,&list,0,source,sizeof(source),&selected.source,0,0)==0);
 assert(importer.prepare(service,fd,&list,&selected)==0);
 AfApManageRequest q;assert(importer.request(service,&q)==0);q.target_slot=7;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 unsigned polls=0;do{status=af_repository_service_pump(service,&manager);assert(++polls<256);}while(status==AF_JOINT_MORE);
 assert(status==0&&manager.receipt.durable&&catalog.slots[6].saved.kind==1);
 uint8_t payload[32];memcpy(payload,catalog.slots[6].saved.payload_sha256,32);
 assert(af_repository_service_close(service)==0);
 assert(unlinkat(fd,"默认滤镜.cube",0)==0);af_catalog_init(&catalog);af_labels_init(&labels);
 service=af_repository_service_open(fd,&catalog,&labels,&status);assert(service&&status==0);
 assert(catalog.slots[6].saved.kind==1&&!memcmp(payload,catalog.slots[6].saved.payload_sha256,32));
 assert(af_reference_import_bind(service)==0&&af_reference_import_info(service,&info)==0);
 assert(af_repository_service_close(service)==0);
}
int main(int argc,char **argv){assert(argc==2);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);
 default_reference(fd);assert(close(fd)==0);return 0;}
'''


def test_default_reference_pipeline_binds_before_menu_capabilities_and_persists(tmp_path):
    source = tmp_path / 'driver.c'
    source.write_text(HARNESS.split('int main(int argc,char **argv)')[0] + EXTRA)
    names = list(dict.fromkeys([*SOURCES, 'af_repository.c', 'af_repository_service.c',
        'af_repository_import.c', 'af_media.c', 'af_posix.c', 'af_labels.c', 'af_labels_store.c',
        'af_ap_manage.c', 'af_persist.c', 'af_store.c', 'af_document.c', 'af_record.c', 'af_slots.c',
        'af_ui.c', 'af_import.c', 'af_joint_fit.c', 'af_joint_basis.c', 'af_joint_asset.c',
        'af_joint_report.c', 'af_grid.c', 'af_grid_fit.c', 'af_cube.c', 'af_reference_joint.c',
        'af_reference_domain.c', 'af_reference_samples.c', 'af_reference_assets.c',
        'af_reference_grid.c', 'af_reference_import.c', 'af_reference_blob.S']))
    binary = tmp_path / 'driver'
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-function', '-DAF_JOINT_BASIS406', '-DAF_REFERENCE_IMPORT406',
        '-ffp-contract=off', '-I' + str(HOME / 'native'), str(source),
        *[str(HOME / 'native' / n) for n in names], str(HOME / 'tests/native_joint_target.c'),
        '-o', str(binary)], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    body = tmp_path / 'body'
    body.mkdir()
    run = subprocess.run([str(binary), str(body)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
