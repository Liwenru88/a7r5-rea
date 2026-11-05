"""已保存AFD1导出到显式临时普通目录；不启动模拟器或访问实际媒体。"""
from pathlib import Path
import subprocess
import pytest
from test_native_repository import HARNESS

NATIVE = Path(__file__).resolve().parents[1] / 'native'
ADDED = r'''
#include <errno.h>
#include <sys/statvfs.h>
static int export_no_space,export_bad_sync,export_bad_read;
static unsigned char export_memory[AF_DOCUMENT_HEADER+AF_DOCUMENT_NAME_MAX];
int af_export_test_fstatvfs(int fd,struct statvfs *s){int result=fstatvfs(fd,s);if(!result&&export_no_space)s->f_bavail=0;return result;}
int af_export_test_fsync(int fd){struct stat s;if(export_bad_sync&&!fstat(fd,&s)&&S_ISDIR(s.st_mode)){errno=EIO;return -1;}return fsync(fd);}
ssize_t af_export_test_read(int fd,void *p,size_t n){if(export_bad_read){errno=EIO;return -1;}return read(fd,p,n);}
static int export_library(int parent){assert(mkdirat(parent,"library",0700)==0);int fd=openat(parent,"library",O_RDONLY|O_DIRECTORY);assert(fd>=0);return fd;}
static AfApManageRequest export_request(void){AfApManageRequest q={0};q.op=7;q.source_slot=q.target_slot=7;return q;}
static size_t exported_bytes(int library,uint8_t *raw,size_t cap){
 int f=openat(library,"C07_G0000000000000001.a7filter",O_RDONLY|O_NOFOLLOW);assert(f>=0);struct stat s;assert(fstat(f,&s)==0&&s.st_size>0&&(uint64_t)s.st_size<=cap);
 size_t n=(size_t)s.st_size;assert(read(f,raw,n)==(ssize_t)n&&close(f)==0);return n;
}
static void export_setup(int parent,int *library){
 open_repository(parent);AfApManageRequest q=create_request(7);run(&q);
 assert(af_edit_base(&catalog,7,18)==0&&af_edit(&catalog,7,0,4)==0&&af_dirty(&catalog,7)==1);*library=export_library(parent);
}
static void export_body_same(const AfCatalog *c,const AfLabels *l,const uint8_t *raw,size_t bytes){
 assert(!memcmp(&catalog,c,sizeof(catalog))&&!memcmp(&labels,l,sizeof(labels)));rename_original_unchanged(raw,bytes);
 struct stat s;assert(fstatat(repository.posix.directory,"C07_B.rec",&s,AT_SYMLINK_NOFOLLOW)<0);
}
static void export_flow(int parent){
 int library;export_setup(parent,&library);AfCatalog before=catalog;AfLabels names=labels;
 uint8_t old[4096+32],raw[512],again[512];size_t bytes=rename_original(old,sizeof(old));AfApManageRequest q=export_request();
 _Static_assert(sizeof(AfApManageRequest)==176,"请求ABI保持176B");
 /* 未overlay旧六返回EMPTY；非法字段和不一致载荷仍明确INVALID。 */
 AfApManage manager_before=manager;
 for(unsigned i=0;i<6;++i){AfApManageRequest bad=q;if(i==0)bad.target_slot=bad.source_slot=6;
  else if(i==1)bad.overwrite=1;else if(i==2)bad.name_bytes=1;else if(i==3)bad.media_generation=1;
  else if(i==4)bad.media_index=1;else bad.initial.base=1;
  assert(af_ap_manage_submit(&manager,&catalog,&bad)==(i==0?AF_EMPTY:AF_INVALID));
  assert(!memcmp(&before,&catalog,sizeof catalog)&&!memcmp(&names,&labels,sizeof labels)&&!memcmp(&manager_before,&manager,sizeof manager));}
 struct stat native_record;
 assert(fstatat(repository.posix.directory,"C06_A.rec",&native_record,AT_SYMLINK_NOFOLLOW)<0&&
        fstatat(repository.posix.directory,"C06_B.rec",&native_record,AT_SYMLINK_NOFOLLOW)<0&&
        fstatat(library,"C06_G0000000000000001.a7filter",&native_record,AT_SYMLINK_NOFOLLOW)<0);
 catalog.slots[6].initial.kind=1;assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_INVALID);catalog=before;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_repository_export(&repository,&manager,library,export_memory,sizeof(export_memory))==0);
 assert(manager.phase==AF_MANAGE_DONE&&manager.receipt.generation==1&&manager.receipt.durable&&!manager.receipt.uncertain);
 size_t n=exported_bytes(library,raw,sizeof(raw));AfDocument document;
 assert(af_document_decode(raw,n,0,&document)==0&&document.present&&document.name_bytes==4&&!memcmp(document.name,"Warm",4));
 assert(!memcmp(&document.initial,&before.slots[6].initial,sizeof(AfPreset))&&!memcmp(&document.saved,&before.slots[6].saved,sizeof(AfPreset)));
 assert(document.saved.base==17&&catalog.slots[6].working.base==18&&af_dirty(&catalog,7)==1);export_body_same(&before,&names,old,bytes);
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_repository_export(&repository,&manager,library,export_memory,sizeof(export_memory))==AF_PERSIST_EXISTS);
 assert(manager.phase==AF_MANAGE_FAILED&&!manager.receipt.durable&&!manager.receipt.uncertain);
 assert(exported_bytes(library,again,sizeof(again))==n&&!memcmp(raw,again,n));export_body_same(&before,&names,old,bytes);
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0&&af_edit(&catalog,7,0,2)==0);
 assert(af_repository_export(&repository,&manager,library,export_memory,sizeof(export_memory))==AF_STALE);
 assert(exported_bytes(library,again,sizeof(again))==n&&!memcmp(raw,again,n));
 assert(catalog.slots[6].saved_revision==1&&catalog.slots[6].saved.base==17&&catalog.slots[6].working.params[0]==2);
 assert(close(library)==0&&af_repository_close(&repository)==0);
}
static void export_capacity(int parent){
 int library;export_setup(parent,&library);AfCatalog before=catalog;AfLabels names=labels;
 uint8_t old[4096+32];size_t bytes=rename_original(old,sizeof(old));AfApManageRequest q=export_request();struct stat s;
 export_no_space=1;assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_repository_export(&repository,&manager,library,export_memory,sizeof(export_memory))==AF_STORE_CAPACITY);export_no_space=0;
 assert(manager.phase==AF_MANAGE_FAILED&&!manager.receipt.durable&&!manager.receipt.uncertain);
 assert(fstatat(library,"C07_G0000000000000001.a7filter",&s,AT_SYMLINK_NOFOLLOW)<0);export_body_same(&before,&names,old,bytes);
 /* 编码缓冲不足和受保护状态别名均在创建文件前拒绝。 */
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_repository_export(&repository,&manager,library,export_memory,AF_DOCUMENT_HEADER)==AF_STORE_CAPACITY);
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_repository_export(&repository,&manager,library,&catalog,sizeof(export_memory))==AF_STORE_INVALID);
 export_body_same(&before,&names,old,bytes);assert(fstatat(library,"C07_G0000000000000001.a7filter",&s,AT_SYMLINK_NOFOLLOW)<0);
 /* 外部改变真实源记录后，导出不得使用旧缓存或自动修复原文件。 */
 int f=openat(repository.posix.directory,"C07_A.rec",O_WRONLY);assert(f>=0);
 uint8_t changed=(uint8_t)(old[bytes-1]^1);assert(pwrite(f,&changed,1,(off_t)bytes-1)==1&&close(f)==0);
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_repository_export(&repository,&manager,library,export_memory,sizeof(export_memory))==AF_STORE_CORRUPT);
 assert(manager.phase==AF_MANAGE_FAILED&&!manager.receipt.durable&&!memcmp(&before,&catalog,sizeof(catalog))&&!memcmp(&names,&labels,sizeof(labels)));
 assert(fstatat(library,"C07_G0000000000000001.a7filter",&s,AT_SYMLINK_NOFOLLOW)<0);
 assert(close(library)==0&&af_repository_close(&repository)==0);
}
static void export_uncertain(int parent,int bad_read){
 int library;export_setup(parent,&library);AfCatalog before=catalog;AfLabels names=labels;
 uint8_t old[4096+32],raw[512],again[512];size_t bytes=rename_original(old,sizeof(old));AfApManageRequest q=export_request();
 export_bad_read=bad_read;export_bad_sync=!bad_read;assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_repository_export(&repository,&manager,library,export_memory,sizeof(export_memory))==AF_STORE_UNCERTAIN);
 export_bad_read=export_bad_sync=0;
 assert(manager.phase==AF_MANAGE_UNCERTAIN&&!manager.receipt.durable&&!manager.receipt.generation&&manager.receipt.uncertain);
 export_body_same(&before,&names,old,bytes);size_t n=exported_bytes(library,raw,sizeof(raw));
 assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_BUSY);
 /* 恢复许可只解除冻结，不产生成功回执；同槽同代仍不能覆盖保留文件。 */
 assert(af_ap_manage_recovered(&manager)==0&&manager.phase==AF_MANAGE_FAILED&&manager.receipt.result==AF_STORE_UNCERTAIN);
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_repository_export(&repository,&manager,library,export_memory,sizeof(export_memory))==AF_PERSIST_EXISTS);
 assert(exported_bytes(library,again,sizeof(again))==n&&!memcmp(raw,again,n));export_body_same(&before,&names,old,bytes);
 assert(close(library)==0&&af_repository_close(&repository)==0);
}
static void export_service(int parent){
 int status;af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 void *service=af_repository_service_open(parent,&catalog,&labels,&status);assert(service&&status==0&&af_repository_service_capabilities(service)==0x3f);
 int body=openat(parent,"A7LOOKS1",O_RDONLY|O_DIRECTORY);assert(body>=0);
 assert(af_repository_service_bind_library(service,body)==AF_STORE_INVALID&&af_repository_service_capabilities(service)==0x3f);assert(close(body)==0);
 int library=export_library(parent),caller_copy=dup(library);assert(caller_copy>=0);
 assert(af_repository_service_bind_library(service,caller_copy)==0&&af_repository_service_capabilities(service)==0x7f);assert(close(caller_copy)==0);
 AfApManageRequest q=create_request(7);assert(af_ap_manage_submit(&manager,&catalog,&q)==0&&af_repository_service_pump(service,&manager)==0);
 assert(af_edit_base(&catalog,7,18)==0);AfCatalog before=catalog;AfLabels names=labels;q=export_request();
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0&&af_repository_service_pump(service,&manager)==0);
 uint8_t raw[512];size_t bytes=exported_bytes(library,raw,sizeof(raw));AfDocument doc;assert(af_document_decode(raw,bytes,0,&doc)==0&&doc.saved.base==17);
 assert(manager.receipt.generation==1&&manager.receipt.durable&&!memcmp(&before,&catalog,sizeof(catalog))&&!memcmp(&names,&labels,sizeof(labels)));
 assert(af_repository_service_bind_library(service,-1)==0&&af_repository_service_capabilities(service)==0x3f);
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0&&af_repository_service_pump(service,&manager)==AF_MANAGE_NOT_READY);
 assert(manager.phase==AF_MANAGE_FAILED&&!manager.receipt.durable&&close(library)==0&&af_repository_service_close(service)==0);
}
'''


@pytest.fixture(scope='module')
def export_driver(tmp_path_factory):
    folder = tmp_path_factory.mktemp('export-build')
    source, binary = folder / 'driver.c', folder / 'repository-export'
    main = HARNESS.replace('int main(', ADDED + '\nint main(')
    main = main.replace('#define _POSIX_C_SOURCE 200809L', '#define _POSIX_C_SOURCE 200809L\n#ifdef __APPLE__\n#define _DARWIN_C_SOURCE 1\n#endif')
    main = main.replace('default:abort();', "case 'f':export_flow(fd);break;case 'g':export_capacity(fd);break;case 'h':export_uncertain(fd,0);break;case 'i':export_uncertain(fd,1);break;case 'j':export_service(fd);break;default:abort();")
    source.write_text(main)
    common = ['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-I' + str(NATIVE)]
    repository_object = folder / 'repository.o'
    result = subprocess.run(common + ['-Dfsync=af_export_test_fsync', '-Dfstatvfs=af_export_test_fstatvfs',
        '-Dread=af_export_test_read', '-c', str(NATIVE / 'af_repository.c'), '-o', str(repository_object)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    names = ['af_repository_service.c', 'af_repository_import.c', 'af_media.c', 'af_posix.c', 'af_labels.c', 'af_labels_store.c', 'af_ap_manage.c',
             'af_persist.c', 'af_store.c', 'af_document.c', 'af_record.c', 'af_sha256.c', 'af_slots.c', 'af_ui.c',
             'af_import.c', 'af_joint.c', 'af_joint_fit.c', 'af_joint_asset.c', 'af_joint_report.c',
             'af_grid.c', 'af_grid_fit.c', 'af_cube.c']
    result = subprocess.run(common + [str(source), str(repository_object), *[str(NATIVE / n) for n in names],
        str(NATIVE.parent / 'tests/native_joint_target.c'), '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize('case', ['f', 'g', 'h', 'i', 'j'], ids=[
    'saved-export-keeps-dirty-and-never-overwrites', 'capacity-and-alias-refused-before-create',
    'directory-sync-uncertain-preserves-file-and-body', 'readback-uncertain-preserves-file-and-body',
    'explicit-library-service-binding'])
def test_saved_export(export_driver, tmp_path, case):
    result = subprocess.run([str(export_driver), str(tmp_path), case], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
