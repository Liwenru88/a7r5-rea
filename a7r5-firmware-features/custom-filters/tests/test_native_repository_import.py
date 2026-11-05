"""IMPORT仓库分批任务：真实临时文件/存储，显式合成模型仅验证接线。"""
from pathlib import Path
import subprocess
import pytest
from test_native_repository import HARNESS

NATIVE = Path(__file__).resolve().parents[1] / 'native'
ADDED = r'''
#include "af_repository_import.h"
static AfRepositoryImportTask task;
static AfRepositoryImport binding;
static AfImportRequest parameters;
static AfMediaSource selected;
static AfJointModel test_model;
static AfGridSample training[8],validation[4];
static char source_memory[512],selection_memory[512];
static float cube_cells[24];
static struct {unsigned calls,fail_at;} predictions;
static const char source_cube[]="LUT_3D_SIZE 2\n0 0 0\n1 0 0\n.015625 1 0\n1.015625 1 0\n0 .015625 1.015625\n1 .015625 1.03125\n.015625 1.015625 1.015625\n1.015625 1.015625 1.03125\n";
static int explicit_model(void *context,const AfJointRecipe *r,const float *rgb,float *out){
 (void)context;++predictions.calls;if(predictions.fail_at&&predictions.calls>=predictions.fail_at)return AF_IO;
 return af_joint_synthetic_predict(0,r,rgb,out);
}
static AfApManageRequest import_request(void){AfApManageRequest q={0};q.op=AF_MANAGE_IMPORT;q.target_slot=8;q.media_generation=9;q.initial.params[6]=3;q.name_bytes=8;memcpy(q.name,"Imported",8);return q;}
static AfApManageRequest prepare_task(int fd){
 af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 assert(af_repository_open(&repository,fd,1,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==0);
 AfApManageRequest q=create_request(7);run(&q);assert(af_edit_base(&catalog,7,18)==0);
 int f=openat(fd,"source.cube",O_WRONLY|O_CREAT|O_EXCL,0600);assert(f>=0&&write(f,source_cube,sizeof(source_cube)-1)==sizeof(source_cube)-1&&close(f)==0);
 assert(af_media_scan(fd,9,&media_work,&listing)==0&&listing.count==1);
 assert(af_media_read(fd,&listing,0,selection_memory,sizeof(selection_memory),&selected,0,0)==0);
 test_model=(AfJointModel){0};test_model.schema=test_model.base_mask=test_model.domain=1;test_model.components=15;test_model.model_sha256[0]=0x20;
 for(unsigned i=0;i<32;++i)test_model.cp_sha256[i]=af_joint_cp_sha256[i];test_model.predict=explicit_model;
 memset(&seed,0,sizeof(seed));for(unsigned i=0;i<129;++i)seed.gamma[i]=i*1024;
 unsigned n=0;for(unsigned b=0;b<2;++b)for(unsigned g=0;g<2;++g)for(unsigned r=0;r<2;++r)training[n++]=(AfGridSample){{.1f+.6f*r,.15f+.55f*g,.12f+.5f*b},1,0};
 validation[0]=(AfGridSample){{.22f,.22f,.22f},1,1};validation[1]=(AfGridSample){{.41f,.41f,.41f},1,1};validation[2]=(AfGridSample){{.61f,.39f,.28f},1,2};validation[3]=(AfGridSample){{.8f,.2f,.55f},1,0};
 parameters=(AfImportRequest){0};parameters.model=&test_model;parameters.seed=&seed;parameters.training=training;parameters.training_count=8;parameters.validation=validation;parameters.validation_count=4;
 parameters.options=(AfJointOptions){65,256,16,16,16,4};
 binding=(AfRepositoryImport){fd,&listing,source_memory,sizeof(source_memory),&parameters,cube_cells,24,&import_work,&candidate,0};
 memset(&task,0,sizeof(task));assert(af_repository_import_init(&task)==0);memset(&candidate,0xa5,sizeof(candidate));predictions.calls=predictions.fail_at=0;
 return import_request();
}
static void start_task(AfApManageRequest *q){
 assert(af_ap_manage_submit(&manager,&catalog,q)==0);
 assert(af_repository_import_start(&task,&repository,&manager,&binding,&selected)==AF_JOINT_MORE);
 assert(manager.phase==AF_MANAGE_RUNNING&&af_repository_import_busy(&task));
}
static void target_absent(int parent){struct stat s;assert(!catalog.slots[7].present);
 assert(fstatat(parent,"A7LOOKS1/C08_A.rec",&s,AT_SYMLINK_NOFOLLOW)<0&&fstatat(parent,"A7LOOKS1/C08_B.rec",&s,AT_SYMLINK_NOFOLLOW)<0);}
static int drain_task(unsigned budget){
 for(unsigned i=0;i<1000;++i){unsigned evaluated=task.conversion.search.fit.evaluations,validated=task.conversion.validated;
  int status=af_repository_import_poll(&task,budget);
  assert(task.conversion.search.fit.evaluations-evaluated<=budget&&task.conversion.validated-validated<=budget);
  if(status!=AF_JOINT_MORE)return status;
  assert(manager.phase==AF_MANAGE_RUNNING);
 }abort();
}
static void batch_flow(int fd){
 AfApManageRequest q=prepare_task(fd);AfSlot other_before=catalog.slots[6];AfLabel other_name=labels.slots[6];start_task(&q);
 assert(af_repository_import_init(&task)==AF_BUSY&&af_repository_import_start(&task,&repository,&manager,&binding,&selected)==AF_BUSY);
 /* start后改变外部列表/参数/seed/模型声明，不改变已复制的请求。 */
 listing.count=0;parameters.options.evaluations=1;training[0].weight=-1;test_model.components=8;seed.gamma[0]=999;selected.sha256[0]^=1;
 assert(af_repository_import_poll(&task,0)==AF_INVALID&&af_repository_import_poll(&task,65)==AF_INVALID&&manager.phase==AF_MANAGE_RUNNING);
 uint32_t progress=0;unsigned polls=0;
 while(task.phase!=AF_REPOSITORY_IMPORT_COMMIT){
  assert(af_repository_import_poll(&task,3)==AF_JOINT_MORE);++polls;
  assert(manager.phase==AF_MANAGE_RUNNING&&manager.progress_done>=progress);progress=manager.progress_done;target_absent(fd);
 }assert(polls>10&&!catalog.slots[7].present&&candidate.fit.attempted_components==15);
 assert(af_repository_import_poll(&task,3)==AF_OK&&manager.phase==AF_MANAGE_DONE&&manager.receipt.durable&&manager.receipt.generation==1);
 assert(!af_repository_import_busy(&task)&&af_repository_import_poll(&task,3)==AF_STALE&&manager.progress_done==1000000);
 assert(catalog.slots[7].saved.kind==1&&!memcmp(&other_before,&catalog.slots[6],sizeof(other_before))&&!memcmp(&other_name,&labels.slots[6],sizeof(other_name)));
 uint8_t image[AF_JOINT_ASSET_BYTES];memcpy(image,candidate.image,sizeof(image));assert(af_repository_close(&repository)==0);
 af_catalog_init(&catalog);assert(af_repository_open(&repository,fd,0,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==0);
 AfDocument d;assert(af_store_snapshot(&repository.stores[7],&buffers,&d)==0&&d.image_bytes==sizeof(image)&&!memcmp(d.image,image,sizeof(image)));
 assert(catalog.slots[7].saved_revision==1&&catalog.slots[7].working.kind==1&&!strcmp(labels.slots[7].text,"Imported")&&af_repository_close(&repository)==0);
}
static void batch_rejected(int fd,int which){
 AfApManageRequest q=prepare_task(fd);AfCatalog before=catalog;AfLabels names=labels;
 AfImportCandidate untouched=candidate;
 if(which==0){q.target_slot=6;assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_INVALID);
  assert(!af_repository_import_busy(&task)&&!memcmp(&before,&catalog,sizeof(catalog))&&!memcmp(&names,&labels,sizeof(labels))&&!memcmp(&untouched,&candidate,sizeof(candidate)));
  target_absent(fd);assert(af_repository_close(&repository)==0);return;}
 else if(which==1){binding.source=&catalog;assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
  assert(af_repository_import_start(&task,&repository,&manager,&binding,&selected)==AF_INVALID);}
 else{binding.parameters=0;assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
  assert(af_repository_import_start(&task,&repository,&manager,&binding,&selected)==AF_MANAGE_NOT_READY);}
 assert(manager.phase==AF_MANAGE_FAILED&&!af_repository_import_busy(&task)&&!memcmp(&before,&catalog,sizeof(catalog))&&!memcmp(&names,&labels,sizeof(labels))&&!memcmp(&untouched,&candidate,sizeof(candidate)));
 target_absent(fd);assert(af_repository_close(&repository)==0);
}
static void batch_changed_file(int fd){
 AfApManageRequest q=prepare_task(fd);start_task(&q);struct stat s;int f=openat(fd,"source.cube",O_RDWR);assert(f>=0&&fstat(f,&s)==0);
 struct timespec times[2];
#ifdef __APPLE__
 times[0]=s.st_atimespec;times[1]=s.st_mtimespec;
#else
 times[0]=s.st_atim;times[1]=s.st_mtim;
#endif
 char changed='4';assert(source_cube[sizeof(source_cube)-3]=='5');
 assert(pwrite(f,&changed,1,sizeof(source_cube)-3)==1&&futimens(f,times)==0&&close(f)==0);
 assert(af_repository_import_poll(&task,3)==AF_STALE&&manager.phase==AF_MANAGE_FAILED&&predictions.calls==0);
 target_absent(fd);assert(af_repository_close(&repository)==0);
}
static void batch_stop(int fd,int which){
 AfApManageRequest q=prepare_task(fd);start_task(&q);AfImportCandidate untouched=candidate;
 assert(af_repository_import_poll(&task,2)==AF_JOINT_MORE&&task.phase==AF_REPOSITORY_IMPORT_FITTING);
 int wanted;
 if(which==0){assert(af_ap_manage_cancel(&manager,manager.job.ticket)==0);wanted=AF_MANAGE_CANCEL;}
 else if(which==1){source_memory[0]^=1;wanted=AF_STALE;}
 else{predictions.fail_at=predictions.calls+1;wanted=AF_JOINT_MODEL_ERROR;}
 assert(drain_task(3)==wanted&&manager.phase==(which==0?AF_MANAGE_CANCELLED:AF_MANAGE_FAILED));
 assert(!af_repository_import_busy(&task)&&!memcmp(&untouched,&candidate,sizeof(candidate)));target_absent(fd);assert(af_repository_close(&repository)==0);
}
static void batch_publish(int fd,int after_publish){
 AfApManageRequest q=prepare_task(fd);AfCatalog before=catalog;AfLabels names=labels;start_task(&q);
 while(task.phase!=AF_REPOSITORY_IMPORT_COMMIT)assert(af_repository_import_poll(&task,64)==AF_JOINT_MORE);
 real_io=repository.io;if(after_publish)repository.io.sync_directory=fail_directory_sync;else repository.io.sync_data=fail_data_sync;
 assert(af_repository_import_poll(&task,64)==(after_publish?AF_STORE_UNCERTAIN:AF_STORE_IO));repository.io=real_io;
 assert(!memcmp(&before,&catalog,sizeof(catalog))&&!memcmp(&names,&labels,sizeof(labels))&&!af_repository_import_busy(&task));
 assert(manager.phase==(after_publish?AF_MANAGE_UNCERTAIN:AF_MANAGE_FAILED)&&!manager.receipt.durable&&!manager.receipt.generation);
 if(after_publish){assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_BUSY);
  assert(af_repository_recover(&repository,8)==0&&catalog.slots[7].saved.kind==1&&catalog.slots[7].saved_revision==1);
  assert(af_ap_manage_recovered(&manager)==0&&manager.phase==AF_MANAGE_FAILED&&manager.receipt.result==AF_STORE_UNCERTAIN);
 }else target_absent(fd);
 assert(af_repository_close(&repository)==0);
}
static void batch_stale_target(int fd){
 AfApManageRequest q=prepare_task(fd),old=create_request(8);run(&old);q.overwrite=1;start_task(&q);
 assert(af_edit(&catalog,8,0,2)==0);assert(drain_task(64)==AF_STALE);
 assert(catalog.slots[7].saved_revision==1&&catalog.slots[7].saved.kind==0&&catalog.slots[7].working.params[0]==2&&!strcmp(labels.slots[7].text,"Warm"));
 struct stat s;assert(fstatat(repository.posix.directory,"C08_B.rec",&s,AT_SYMLINK_NOFOLLOW)<0&&af_repository_close(&repository)==0);
}
static void batch_candidate_changed(int fd){
 AfApManageRequest q=prepare_task(fd);start_task(&q);
 while(task.phase!=AF_REPOSITORY_IMPORT_COMMIT)assert(af_repository_import_poll(&task,64)==AF_JOINT_MORE);
 /* 候选仍是格式合法的另一名称，但不是已经捕获的请求；不得跨轮询混入。 */
 candidate.name[0]='X';assert(af_repository_import_poll(&task,64)==AF_STALE);
 assert(manager.phase==AF_MANAGE_FAILED);target_absent(fd);assert(af_repository_close(&repository)==0);
}
static void legacy_overlay_reopen_and_clear(int fd){
 AfApManageRequest q=prepare_task(fd);AfSlot original_other=catalog.slots[6];AfLabel other_name=labels.slots[6];
 q.target_slot=6;q.overwrite=1;start_task(&q);assert(drain_task(64)==AF_OK);
 assert(catalog.slots[5].present&&catalog.slots[5].saved.kind==1&&catalog.slots[5].saved_revision==1);
 assert(!memcmp(&original_other,&catalog.slots[6],sizeof original_other)&&!memcmp(&other_name,&labels.slots[6],sizeof other_name));
 assert(af_repository_close(&repository)==0);af_catalog_init(&catalog);
 assert(af_repository_open(&repository,fd,0,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==0);
 assert(catalog.slots[5].present&&catalog.slots[5].saved.kind==1&&!strcmp(labels.slots[5].text,"Imported"));
 AfApManageRequest clear={0};clear.op=AF_MANAGE_CLEAR;clear.target_slot=6;clear.overwrite=1;run(&clear);
 assert(!catalog.slots[5].present&&catalog.slots[5].saved_revision==2&&!labels.slots[5].bytes);
 assert(af_repository_close(&repository)==0);af_catalog_init(&catalog);
 assert(af_repository_open(&repository,fd,0,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==0);
 assert(!catalog.slots[5].present&&catalog.slots[5].saved_revision==2&&!labels.slots[5].bytes);
 for(unsigned i=0;i<5;++i)assert(!catalog.slots[i].present&&!catalog.slots[i].saved_revision);
 assert(!memcmp(&original_other.initial,&catalog.slots[6].initial,sizeof(AfPreset))&&
        !memcmp(&original_other.saved,&catalog.slots[6].saved,sizeof(AfPreset))&&
        !memcmp(&original_other.saved,&catalog.slots[6].working,sizeof(AfPreset))&&
        original_other.saved_revision==catalog.slots[6].saved_revision&&
        !memcmp(&other_name,&labels.slots[6],sizeof other_name));
 assert(af_repository_close(&repository)==0);
}
'''


@pytest.fixture(scope='module')
def import_task_driver(tmp_path_factory):
    folder = tmp_path_factory.mktemp('import-task-build')
    source, binary = folder / 'driver.c', folder / 'repository-import'
    main = HARNESS.replace('int main(', ADDED + '\nint main(')
    main = main.replace('#define _POSIX_C_SOURCE 200809L', '#define _POSIX_C_SOURCE 200809L\n#ifdef __APPLE__\n#define _DARWIN_C_SOURCE 1\n#endif')
    main = main.replace('default:abort();', "case 'f':batch_flow(fd);break;case 'g':batch_rejected(fd,0);break;case 'h':batch_rejected(fd,1);break;case 'i':batch_rejected(fd,2);break;case 'j':batch_changed_file(fd);break;case 'k':batch_stop(fd,0);break;case 'l':batch_stop(fd,1);break;case 'm':batch_stop(fd,2);break;case 'n':batch_publish(fd,0);break;case 'o':batch_publish(fd,1);break;case 'p':batch_stale_target(fd);break;case 'q':batch_candidate_changed(fd);break;case 'z':legacy_overlay_reopen_and_clear(fd);break;default:abort();")
    source.write_text(main)
    names = ['af_repository_import.c', 'af_repository.c', 'af_repository_service.c', 'af_media.c',
        'af_posix.c', 'af_labels.c', 'af_labels_store.c', 'af_ap_manage.c', 'af_persist.c',
        'af_store.c', 'af_document.c', 'af_record.c', 'af_sha256.c', 'af_slots.c', 'af_ui.c',
        'af_import.c', 'af_joint.c', 'af_joint_fit.c', 'af_joint_asset.c', 'af_joint_report.c',
        'af_grid.c', 'af_grid_fit.c', 'af_cube.c']
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-I' + str(NATIVE),
        str(source), *[str(NATIVE / n) for n in names], str(NATIVE.parent / 'tests/native_joint_target.c'),
        '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize('case', ['f','g','h','i','j','k','l','m','n','o','p','q','z'], ids=[
    'batched-snapshot-and-durable-reopen', 'original-overlay-unconfirmed-refused', 'work-alias-refused',
    'no-default-model', 'same-mtime-same-length-file-change-refused', 'cancel-between-polls',
    'source-buffer-change-refused', 'model-failure-no-commit', 'failure-before-publish',
    'uncertain-recovery-keeps-real-record', 'stale-target-refused-before-publish',
    'candidate-must-still-match-captured-request','original-overlay-lut-durable-reopen-tombstone'])
def test_import_repository_task(import_task_driver, tmp_path, case):
    result = subprocess.run([str(import_task_driver), str(tmp_path), case], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
