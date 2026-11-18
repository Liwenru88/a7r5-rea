"""原生管理请求到实际普通目录及启动恢复，未访问相机存储。"""
from pathlib import Path
import subprocess
import pytest
NATIVE=Path(__file__).resolve().parents[1]/'native'
HARNESS=r'''
#define _POSIX_C_SOURCE 200809L
#include "af_repository.h"
#include "af_persist.h"
#include "af_repository_service.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static AfCatalog catalog,other;
static AfLabels labels,other_labels;
static AfRepository repository,second;
static unsigned char memory[3][4096+32];
static AfStoreBuffers buffers={memory[0],memory[1],memory[2],sizeof(memory[0])};
static AfApManage manager;
extern int af_joint_synthetic_predict(void *,const AfJointRecipe *,const float *,float *);
static AfImportWork import_work;
static AfImportCandidate candidate;
static AfJointRecipe seed;
static AfMediaList media_work,listing;
static AfApManageRequest create_request(unsigned slot){AfApManageRequest q={0};q.op=AF_MANAGE_CREATE;q.target_slot=slot;q.initial.base=17;q.initial.params[6]=3;q.name_bytes=4;memcpy(q.name,"Warm",4);return q;}
static void run(AfApManageRequest *q){assert(af_ap_manage_submit(&manager,&catalog,q)==0);assert(af_repository_execute(&repository,&manager,0)==0);assert(manager.phase==AF_MANAGE_DONE && manager.receipt.durable==1);}
static void open_repository(int fd){af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);assert(af_repository_open(&repository,fd,1,0,4096,&buffers,&catalog,&labels)==0);assert(repository.ready_mask==((1u<<20)-1) && !repository.error_mask);}
static void flow(int fd){
 open_repository(fd);AfApManageRequest q=create_request(7);run(&q);assert(catalog.slots[6].saved_revision==1);
 assert(af_repository_open(&second,fd,0,0,4096,&buffers,&other,&other_labels)==AF_PERSIST_BUSY);
 assert(af_edit_base(&catalog,7,18)==0);assert(af_edit(&catalog,7,0,4)==0);
 q=(AfApManageRequest){0};q.op=AF_MANAGE_SAVE;q.source_slot=q.target_slot=7;run(&q);
 assert(catalog.slots[6].saved.base==18 && catalog.slots[6].initial.base==17 && af_dirty(&catalog,7)==0);
 q=(AfApManageRequest){0};q.op=AF_MANAGE_COPY;q.source_slot=7;q.target_slot=20;q.name_bytes=4;memcpy(q.name,"Copy",4);run(&q);
 assert(catalog.slots[19].saved.base==18 && labels.slots[19].bytes==4);
 assert(af_repository_close(&repository)==0);open_repository(fd);
 assert(catalog.slots[6].working.base==18 && catalog.slots[6].working.params[0]==4);
 assert(catalog.slots[19].initial.base==17 && catalog.slots[19].saved.base==18);
 assert(!memcmp(labels.slots[19].text,"Copy",5));
 assert(af_repository_close(&repository)==0);
 int file=openat(fd,"A7LOOKS1/C20_A.rec",O_WRONLY|O_TRUNC);assert(file>=0 && write(file,"bad",3)==3 && close(file)==0);
 af_catalog_init(&catalog);assert(af_repository_open(&repository,fd,0,0,4096,&buffers,&catalog,&labels)==AF_REPOSITORY_PARTIAL);
 assert(repository.error_mask==(1u<<19) && catalog.slots[6].present && !catalog.slots[19].present);
 q=create_request(20);assert(af_ap_manage_submit(&manager,&catalog,&q)==0);assert(af_repository_execute(&repository,&manager,0)==AF_STORE_CORRUPT);
 assert(af_repository_close(&repository)==0);
}
static void rejected(int fd){
 AfStoreBuffers bad=buffers;bad.b=bad.a;
 assert(af_repository_open(&repository,fd,1,0,4096,&bad,&catalog,&labels)==AF_STORE_INVALID);
 struct stat s;assert(fstatat(fd,"A7LOOKS1",&s,AT_SYMLINK_NOFOLLOW)<0);
 assert(mkdirat(fd,"A7LOOKS1",0700)==0);int f=openat(fd,"A7LOOKS1/keep",O_WRONLY|O_CREAT|O_EXCL,0600);assert(f>=0 && write(f,"untouched",9)==9 && close(f)==0);
 assert(af_repository_open(&repository,fd,1,0,4096,&buffers,&catalog,&labels)==AF_STORE_INVALID);
 f=openat(fd,"A7LOOKS1/keep",O_RDONLY);char raw[10]={0};assert(f>=0 && read(f,raw,9)==9 && close(f)==0 && !strcmp(raw,"untouched"));
 assert(fstatat(fd,"A7LOOKS1/OWNER.LCK",&s,AT_SYMLINK_NOFOLLOW)<0);
}
static void failures(int fd){
 open_repository(fd);AfApManageRequest q=create_request(7);run(&q);AfCatalog saved=catalog;
 q=(AfApManageRequest){0};q.op=AF_MANAGE_IMPORT;q.target_slot=8;q.initial.params[6]=3;q.name_bytes=3;memcpy(q.name,"LUT",3);q.media_generation=1;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);assert(af_repository_execute(&repository,&manager,0)==AF_MANAGE_NOT_READY);
 assert(manager.phase==AF_MANAGE_FAILED && !memcmp(&saved,&catalog,sizeof(catalog)));
 q=(AfApManageRequest){0};q.op=AF_MANAGE_SAVE;q.source_slot=q.target_slot=7;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);assert(af_edit(&catalog,7,0,2)==0);
 assert(af_repository_execute(&repository,&manager,0)==AF_STALE && catalog.slots[6].saved.params[0]==0 && catalog.slots[6].working.params[0]==2);
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);assert(af_ap_manage_cancel(&manager,manager.job.ticket)==0);
 assert(af_repository_execute(&repository,&manager,0)==AF_EMPTY && manager.phase==AF_MANAGE_CANCELLED);
 assert(af_repository_close(&repository)==0);
}
static void service(int fd){
 int status=-99;af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 void *s=af_repository_service_open(fd,&catalog,&labels,&status);assert(s&&status==0&&af_repository_service_capabilities(s)==0x3f);
 AfApManageRequest q=create_request(7);assert(af_ap_manage_submit(&manager,&catalog,&q)==0);assert(af_repository_service_pump(s,&manager)==0);
 assert(manager.phase==AF_MANAGE_DONE && catalog.slots[6].present);
 assert(af_repository_service_close(s)==0);af_catalog_init(&catalog);
 s=af_repository_service_open(fd,&catalog,&labels,&status);assert(s&&status==0&&catalog.slots[6].saved.base==17);
 assert(!memcmp(labels.slots[6].text,"Warm",5));assert(af_repository_service_close(s)==0);
 assert(af_repository_service_capabilities(0)==0&&af_repository_service_pump(0,&manager)==AF_STORE_INVALID);
}
static void imported(int fd,int aliases){
 /* 显式合成模型仅验证文件→任务→持久化边界，绝不作为产品默认成像模型。 */
 static const char cube[]="LUT_3D_SIZE 2\n0 0 0\n1 0 0\n.015625 1 0\n1.015625 1 0\n0 .015625 1.015625\n1 .015625 1.03125\n.015625 1.015625 1.015625\n1.015625 1.015625 1.03125\n";
 int f=openat(fd,"source.cube",O_WRONLY|O_CREAT|O_EXCL,0600);assert(f>=0&&write(f,cube,sizeof(cube)-1)==sizeof(cube)-1&&close(f)==0);
 af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 assert(af_repository_open(&repository,fd,1,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==0);
 assert(af_media_scan(fd,9,&media_work,&listing)==0&&listing.count==1);
 AfJointModel model={0};model.schema=model.base_mask=model.domain=1;model.components=15;model.model_sha256[0]=0x20;
 for(unsigned i=0;i<32;++i)model.cp_sha256[i]=af_joint_cp_sha256[i];model.predict=af_joint_synthetic_predict;
 for(unsigned i=0;i<129;++i)seed.gamma[i]=i*1024;
 AfGridSample training[8],validation[4];unsigned n=0;
 for(unsigned b=0;b<2;++b)for(unsigned g=0;g<2;++g)for(unsigned r=0;r<2;++r)training[n++]=(AfGridSample){{.1f+.6f*r,.15f+.55f*g,.12f+.5f*b},1,0};
 validation[0]=(AfGridSample){{.22f,.22f,.22f},1,1};validation[1]=(AfGridSample){{.41f,.41f,.41f},1,1};validation[2]=(AfGridSample){{.61f,.39f,.28f},1,2};validation[3]=(AfGridSample){{.8f,.2f,.55f},1,0};
 AfImportRequest parameters={0};parameters.model=&model;parameters.seed=&seed;parameters.training=training;parameters.training_count=8;parameters.validation=validation;parameters.validation_count=4;parameters.options=(AfJointOptions){65,256,16,16,16,4};
 char source[512];float cells[24];AfRepositoryImport input={fd,&listing,source,sizeof(source),&parameters,cells,24,&import_work,&candidate,0};
 AfApManageRequest q={0};q.op=AF_MANAGE_IMPORT;q.target_slot=8;q.media_generation=9;q.initial.params[6]=3;q.name_bytes=8;memcpy(q.name,"Imported",8);
 if(aliases){
  AfApManageRequest original=create_request(1);original.overwrite=1;run(&original);AfCatalog before=catalog;AfLabels names_before=labels;
  AfStore stores_before[AF_USERS];memcpy(stores_before,repository.stores,sizeof(stores_before));
  void *protected[]={&repository,&catalog,&labels,&manager,memory[0],memory[1],memory[2],
                     &input,&listing,&parameters,&model,&seed,training,validation};
  memset(source,0xa5,sizeof(source));memset(cells,0x5a,sizeof(cells));memset(&candidate,0x6c,sizeof(candidate));
  AfImportCandidate candidate_before=candidate;char source_before[sizeof(source)];float cells_before[24];
  memcpy(source_before,source,sizeof(source));memcpy(cells_before,cells,sizeof(cells));
  for(unsigned output=0;output<4;++output)for(unsigned region=0;region<sizeof(protected)/sizeof(protected[0]);++region){
   AfRepositoryImport bad=input;void *binding=region==7?(void *)&bad:protected[region];
   if(output==0)bad.source=binding;else if(output==1)bad.cube_storage=binding;
   else if(output==2)bad.work=binding;else bad.candidate=binding;
   assert(af_ap_manage_submit(&manager,&catalog,&q)==0);assert(af_repository_execute(&repository,&manager,&bad)==AF_STORE_INVALID);
   assert(manager.phase==AF_MANAGE_FAILED&&manager.receipt.result==AF_STORE_INVALID&&!manager.receipt.durable&&!manager.receipt.uncertain&&!manager.receipt.generation);
   assert(!manager.progress_done&&!manager.progress_total&&!memcmp(source,source_before,sizeof(source))&&!memcmp(cells,cells_before,sizeof(cells)));
   assert(!memcmp(&before,&catalog,sizeof(before))&&!memcmp(&names_before,&labels,sizeof(names_before))&&!memcmp(stores_before,repository.stores,sizeof(stores_before)));
   assert(!memcmp(&candidate_before,&candidate,sizeof(candidate)));
  }
  for(unsigned invalid=0;invalid<4;++invalid){
   AfRepositoryImport bad=input;
   if(invalid==0)bad.source_capacity=SIZE_MAX;else if(invalid==1)bad.cube_capacity=SIZE_MAX/sizeof(float)+1;
   else if(invalid==2)bad.source=&candidate;else bad.cube_storage=(float *)&import_work;
   assert(af_ap_manage_submit(&manager,&catalog,&q)==0);assert(af_repository_execute(&repository,&manager,&bad)==AF_STORE_INVALID);
   assert(manager.phase==AF_MANAGE_FAILED&&!manager.receipt.durable&&!manager.receipt.generation);
   assert(!manager.progress_done&&!manager.progress_total&&!memcmp(source,source_before,sizeof(source))&&!memcmp(cells,cells_before,sizeof(cells)));
   assert(!memcmp(&before,&catalog,sizeof(before))&&!memcmp(&names_before,&labels,sizeof(names_before))&&!memcmp(&candidate_before,&candidate,sizeof(candidate)));
  }
  struct stat s;assert(fstatat(fd,"A7LOOKS1/C08_A.rec",&s,AT_SYMLINK_NOFOLLOW)<0&&fstatat(fd,"A7LOOKS1/C08_B.rec",&s,AT_SYMLINK_NOFOLLOW)<0);
  assert(af_repository_close(&repository)==0);assert(unlinkat(fd,"source.cube",0)==0);af_catalog_init(&catalog);
  assert(af_repository_open(&repository,fd,0,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==0);
  assert(!memcmp(&before.slots[0],&catalog.slots[0],sizeof(AfSlot))&&!catalog.slots[7].present);
  assert(af_repository_close(&repository)==0);return;
 }
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);assert(af_repository_execute(&repository,&manager,&input)==0);
 assert(manager.phase==AF_MANAGE_DONE&&manager.progress_done==1000000&&manager.progress_total==1000000);
 assert(catalog.slots[7].saved.kind==1 && candidate.fit.attempted_components==15 && candidate.report.samples==4);
 assert(af_repository_close(&repository)==0);assert(unlinkat(fd,"source.cube",0)==0);af_catalog_init(&catalog);
 assert(af_repository_open(&repository,fd,0,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels)==0);
 assert(af_repository_recover(&repository,8)==0);AfDocument d;AfJointAsset asset;
 assert(af_store_snapshot(&repository.stores[7],&buffers,&d)==0&&af_import_asset(&d,&asset)==0);
 assert(!memcmp(d.image,candidate.image,AF_JOINT_ASSET_BYTES)&&!memcmp(d.initial.lut_sha256,candidate.initial.lut_sha256,32));
 assert(af_repository_close(&repository)==0);
}
static AfStoreIo real_io;
static int fail_data_sync(void *context,uint32_t slot,uint32_t bank){
 assert(real_io.sync_data(context,slot,bank)==0);return -1;
}
static int fail_directory_sync(void *context,uint32_t slot,uint32_t bank){
 (void)context;(void)slot;(void)bank;return -1;
}
static size_t original_target(uint8_t *out,size_t capacity){
 size_t bytes=0;assert(repository.io.read(repository.io.context,20,0,out,capacity,&bytes)==0);return bytes;
}
static void target_backup_unchanged(const uint8_t *before,size_t bytes){
 uint8_t now[4096+32];assert(original_target(now,sizeof(now))==bytes&&!memcmp(before,now,bytes));
}
static AfApManageRequest setup_overwrite(int fd){
 open_repository(fd);AfApManageRequest q=create_request(7);run(&q);
 q=create_request(20);q.initial.base=0;q.name_bytes=3;memcpy(q.name,"Old",3);run(&q);
 assert(af_edit_base(&catalog,7,18)==0&&af_edit(&catalog,7,0,4)==0&&af_dirty(&catalog,7)==1);
 q=(AfApManageRequest){0};q.op=AF_MANAGE_COPY;q.source_slot=7;q.target_slot=20;
 q.name_bytes=6;memcpy(q.name,"替换",6);return q;
}
static void overwrite_flow(int fd){
 AfApManageRequest q=setup_overwrite(fd);uint8_t before[4096+32];size_t bytes=original_target(before,sizeof(before));
 AfCatalog original=catalog;AfLabels names_before=labels;AfApManage manager_before=manager;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_EXISTS);
 assert(!memcmp(&original,&catalog,sizeof(catalog))&&!memcmp(&names_before,&labels,sizeof(labels))&&!memcmp(&manager_before,&manager,sizeof(manager)));
 q.overwrite=1;assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_edit(&catalog,20,0,2)==0);
 assert(af_repository_execute(&repository,&manager,0)==AF_STALE&&!manager.receipt.durable);
 assert(catalog.slots[19].saved_revision==1&&catalog.slots[19].saved.params[0]==0);
 target_backup_unchanged(before,bytes);AfSlot source_before=catalog.slots[6];run(&q);
 assert(!memcmp(&source_before,&catalog.slots[6],sizeof(source_before))&&af_dirty(&catalog,7)==1);
 assert(catalog.slots[19].saved_revision==2&&catalog.slots[19].initial.base==17&&catalog.slots[19].saved.base==18);
 assert(catalog.slots[19].saved.params[0]==4&&af_dirty(&catalog,20)==0&&!strcmp(labels.slots[19].text,"替换"));
 target_backup_unchanged(before,bytes);assert(af_repository_close(&repository)==0);open_repository(fd);
 assert(catalog.slots[19].saved_revision==2&&catalog.slots[19].working.base==18&&catalog.slots[19].working.params[0]==4);
 assert(catalog.slots[6].saved_revision==1&&catalog.slots[6].working.base==17&&catalog.slots[6].working.params[0]==0);
 assert(!strcmp(labels.slots[19].text,"替换"));target_backup_unchanged(before,bytes);assert(af_repository_close(&repository)==0);
}
static void overwrite_failure(int fd,int after_publish){
 AfApManageRequest q=setup_overwrite(fd);q.overwrite=1;
 AfCatalog before=catalog;AfLabels names_before=labels;uint8_t old[4096+32];size_t bytes=original_target(old,sizeof(old));
 real_io=repository.io;
 if(after_publish)repository.io.sync_directory=fail_directory_sync;else repository.io.sync_data=fail_data_sync;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 int wanted=after_publish?AF_STORE_UNCERTAIN:AF_STORE_IO;
 assert(af_repository_execute(&repository,&manager,0)==wanted);
 assert(manager.receipt.result==wanted&&!manager.receipt.durable&&!manager.receipt.generation);
 assert(manager.phase==(after_publish?AF_MANAGE_UNCERTAIN:AF_MANAGE_FAILED));
 assert(manager.receipt.uncertain==(uint32_t)after_publish);
 assert(!memcmp(&before,&catalog,sizeof(catalog))&&!memcmp(&names_before,&labels,sizeof(labels)));
 repository.io=real_io;target_backup_unchanged(old,bytes);struct stat st;
 assert(fstatat(repository.posix.directory,"C20_B.new",&st,AT_SYMLINK_NOFOLLOW)<0);
 if(after_publish){
  assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_BUSY);
  assert(repository.stores[19].uncertain&&!repository.stores[19].ready);
  assert(af_repository_recover(&repository,20)==0&&manager.phase==AF_MANAGE_UNCERTAIN);
  assert(catalog.slots[19].saved_revision==2&&catalog.slots[19].working.params[0]==4&&!strcmp(labels.slots[19].text,"替换"));
  assert(!memcmp(&before.slots[6],&catalog.slots[6],sizeof(AfSlot)));
  assert(af_ap_manage_recovered(&manager)==0&&manager.phase==AF_MANAGE_FAILED);
 }else{
  assert(fstatat(repository.posix.directory,"C20_B.rec",&st,AT_SYMLINK_NOFOLLOW)<0);
  assert(repository.stores[19].ready&&!repository.stores[19].uncertain&&repository.stores[19].generation==1);
 }
 assert(af_repository_close(&repository)==0);open_repository(fd);
 assert(catalog.slots[19].saved_revision==(after_publish?2u:1u));
 assert(catalog.slots[19].working.params[0]==(after_publish?4:0));
 assert(!strcmp(labels.slots[19].text,after_publish?"替换":"Old"));target_backup_unchanged(old,bytes);
 assert(af_repository_close(&repository)==0);
}
/* 与现有真实目录仓库驱动组合；只创建本轮临时测试记录。 */
static AfApManageRequest setup_clear(int fd){
 (void)setup_overwrite(fd);AfApManageRequest q={0};
 q.op=AF_MANAGE_CLEAR;q.target_slot=20;q.overwrite=1;return q;
}
static void clear_flow(int fd){
 AfApManageRequest q=setup_clear(fd);AfCatalog original=catalog;AfLabels names_before=labels;
 AfApManage manager_before=manager;uint8_t old[4096+32];size_t bytes=original_target(old,sizeof(old));
 q.overwrite=0;assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_INVALID);q.overwrite=1;
 assert(!memcmp(&original,&catalog,sizeof(catalog))&&!memcmp(&manager_before,&manager,sizeof(manager)));
 const unsigned protected_slots[]={0,1,6,21};
 for(unsigned i=0;i<sizeof(protected_slots)/sizeof(protected_slots[0]);++i){
  AfApManageRequest bad=q;bad.target_slot=protected_slots[i];
  assert(af_ap_manage_submit(&manager,&catalog,&bad)==((bad.target_slot==1||bad.target_slot==6)?AF_EMPTY:AF_INVALID));
  assert(!memcmp(&original,&catalog,sizeof catalog)&&!memcmp(&names_before,&labels,sizeof labels)&&!memcmp(&manager_before,&manager,sizeof manager));
 }
 struct stat native_record;for(unsigned native_slot=1;native_slot<=6;native_slot+=5){
  const char *a=native_slot==1?"A7LOOKS1/C01_A.rec":"A7LOOKS1/C06_A.rec";
  const char *b=native_slot==1?"A7LOOKS1/C01_B.rec":"A7LOOKS1/C06_B.rec";
  assert(fstatat(fd,a,&native_record,AT_SYMLINK_NOFOLLOW)<0&&fstatat(fd,b,&native_record,AT_SYMLINK_NOFOLLOW)<0);
 }
 AfApManageRequest bad=q;bad.target_slot=8;assert(af_ap_manage_submit(&manager,&catalog,&bad)==AF_EMPTY);
 bad=q;bad.source_slot=7;assert(af_ap_manage_submit(&manager,&catalog,&bad)==AF_INVALID);
 bad=q;bad.name_bytes=1;bad.name[0]='X';assert(af_ap_manage_submit(&manager,&catalog,&bad)==AF_INVALID);
 AfPreset lut=catalog.slots[19].working;lut.kind=1;lut.payload_sha256[0]=lut.lut_sha256[0]=1;
 assert(af_install(&catalog,20,&lut,1)==AF_OK);
 /* 完整LUT管理另有文件级主路径；混合载荷快照仍须在入队前拒绝。 */
 catalog.slots[19].working.payload_sha256[0]^=2;AfCatalog lut_before=catalog;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_INVALID&&!memcmp(&lut_before,&catalog,sizeof(catalog)));
 catalog=original;
 assert(!memcmp(&names_before,&labels,sizeof(labels))&&!memcmp(&manager_before,&manager,sizeof(manager)));
 assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_OK);assert(af_edit(&catalog,20,0,2)==AF_OK);
 assert(af_repository_execute(&repository,&manager,0)==AF_STALE&&!manager.receipt.durable);
 target_backup_unchanged(old,bytes);AfSlot source=catalog.slots[6];run(&q);
 assert(!catalog.slots[19].present&&catalog.slots[19].saved_revision==2&&!catalog.slots[19].pending.request);
 assert(!memcmp(&source,&catalog.slots[6],sizeof(source))&&af_dirty(&catalog,7)==1);
 const char *name=0;size_t name_bytes=0;assert(af_labels_read(&labels,20,&name,&name_bytes)==AF_EMPTY);
 AfDocument d;assert(af_store_snapshot(&repository.stores[19],&buffers,&d)==AF_STORE_OK&&!d.present);
 target_backup_unchanged(old,bytes);assert(af_repository_close(&repository)==0);open_repository(fd);
 assert(!catalog.slots[19].present&&catalog.slots[19].saved_revision==2);
 assert(af_labels_read(&labels,20,&name,&name_bytes)==AF_EMPTY);
 assert(catalog.slots[6].working.base==17&&catalog.slots[6].working.params[0]==0);
 /* 墓碑仍占用代号；再次新建必须生成下一代，不能从1重启并复活旧记录。 */
 q=create_request(20);run(&q);assert(catalog.slots[19].present&&catalog.slots[19].saved_revision==3);
 assert(af_repository_close(&repository)==0);open_repository(fd);
 assert(catalog.slots[19].present&&catalog.slots[19].saved_revision==3);
 assert(af_repository_close(&repository)==0);
}
static void clear_failure(int fd,int after_publish){
 AfApManageRequest q=setup_clear(fd);AfCatalog before=catalog;AfLabels names_before=labels;
 uint8_t old[4096+32];size_t bytes=original_target(old,sizeof(old));real_io=repository.io;
 if(after_publish)repository.io.sync_directory=fail_directory_sync;else repository.io.sync_data=fail_data_sync;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_OK);
 int wanted=after_publish?AF_STORE_UNCERTAIN:AF_STORE_IO;
 assert(af_repository_execute(&repository,&manager,0)==wanted);
 assert(!manager.receipt.durable&&!manager.receipt.generation&&manager.receipt.uncertain==(uint32_t)after_publish);
 assert(manager.phase==(after_publish?AF_MANAGE_UNCERTAIN:AF_MANAGE_FAILED));
 assert(!memcmp(&before,&catalog,sizeof(catalog))&&!memcmp(&names_before,&labels,sizeof(labels)));
 repository.io=real_io;target_backup_unchanged(old,bytes);struct stat st;
 assert(fstatat(repository.posix.directory,"C20_B.new",&st,AT_SYMLINK_NOFOLLOW)<0);
 if(after_publish){
  assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_BUSY);
  assert(af_repository_recover(&repository,20)==AF_OK&&manager.phase==AF_MANAGE_UNCERTAIN);
  assert(!catalog.slots[19].present&&catalog.slots[19].saved_revision==2);
  assert(!memcmp(&before.slots[6],&catalog.slots[6],sizeof(AfSlot)));
  assert(af_ap_manage_recovered(&manager)==AF_OK&&manager.phase==AF_MANAGE_FAILED);
 }else{
  assert(fstatat(repository.posix.directory,"C20_B.rec",&st,AT_SYMLINK_NOFOLLOW)<0);
  assert(repository.stores[19].ready&&!repository.stores[19].uncertain&&repository.stores[19].generation==1);
 }
 assert(af_repository_close(&repository)==0);open_repository(fd);
 assert(catalog.slots[19].present==(uint32_t)!after_publish&&catalog.slots[19].saved_revision==(after_publish?2u:1u));
 const char *name=0;size_t name_bytes=0;
 if(after_publish)assert(af_labels_read(&labels,20,&name,&name_bytes)==AF_EMPTY);
 else assert(af_labels_read(&labels,20,&name,&name_bytes)==AF_OK&&!strcmp(name,"Old"));
 target_backup_unchanged(old,bytes);assert(af_repository_close(&repository)==0);
}

/* RENAME的ABI操作号固定为6；红灯阶段尚未追加生产枚举，测试仍可执行拒绝路径。 */
static AfApManageRequest rename_request(void){
 AfApManageRequest q={0};q.op=6;q.source_slot=q.target_slot=7;
 memset(q.name,'Z',60);memcpy(q.name+60,"暖",3);q.name_bytes=63;return q;
}
static size_t rename_original(uint8_t *out,size_t capacity){
 size_t bytes=0;assert(repository.io.read(repository.io.context,7,0,out,capacity,&bytes)==0);return bytes;
}
static void rename_original_unchanged(const uint8_t *before,size_t bytes){
 uint8_t now[4096+32];assert(rename_original(now,sizeof(now))==bytes&&!memcmp(before,now,bytes));
}
static void rename_presets_same(const AfSlot *before,const AfSlot *after){
 assert(before->present==after->present&&!memcmp(&before->initial,&after->initial,sizeof(AfPreset))&&
        !memcmp(&before->saved,&after->saved,sizeof(AfPreset))&&!memcmp(&before->working,&after->working,sizeof(AfPreset)));
}
static void rename_flow(int fd){
 (void)setup_overwrite(fd);AfApManageRequest q=rename_request();AfCatalog original=catalog;AfLabels old_names=labels;
 AfApManage manager_before=manager;uint8_t old[4096+32];size_t bytes=rename_original(old,sizeof(old));
 const unsigned protected_slots[]={0,1,6,21};
 for(unsigned i=0;i<sizeof(protected_slots)/sizeof(protected_slots[0]);++i){
  AfApManageRequest bad=q;bad.source_slot=bad.target_slot=protected_slots[i];
  assert(af_ap_manage_submit(&manager,&catalog,&bad)==((bad.target_slot==1||bad.target_slot==6)?AF_EMPTY:AF_INVALID));
  assert(!memcmp(&original,&catalog,sizeof catalog)&&!memcmp(&old_names,&labels,sizeof labels)&&!memcmp(&manager_before,&manager,sizeof manager));
 }
 struct stat native_record;for(unsigned native_slot=1;native_slot<=6;native_slot+=5){
  const char *a=native_slot==1?"A7LOOKS1/C01_A.rec":"A7LOOKS1/C06_A.rec";
  const char *b=native_slot==1?"A7LOOKS1/C01_B.rec":"A7LOOKS1/C06_B.rec";
  assert(fstatat(fd,a,&native_record,AT_SYMLINK_NOFOLLOW)<0&&fstatat(fd,b,&native_record,AT_SYMLINK_NOFOLLOW)<0);
 }
 AfApManageRequest bad=q;bad.source_slot=bad.target_slot=8;assert(af_ap_manage_submit(&manager,&catalog,&bad)==AF_EMPTY);
 for(unsigned i=0;i<7;++i){
  bad=q;if(i==0)bad.source_slot=20;else if(i==1)bad.overwrite=1;else if(i==2)bad.name_bytes=0;
  else if(i==3)bad.name_bytes=64;else if(i==4)bad.name[0]=(char)0x80;else if(i==5)bad.media_index=1;else bad.media_generation=1;
  assert(af_ap_manage_submit(&manager,&catalog,&bad)==AF_INVALID);
 }
 AfPreset lut=catalog.slots[6].working;lut.kind=1;lut.payload_sha256[0]=lut.lut_sha256[0]=1;
 assert(af_install(&catalog,7,&lut,1)==AF_OK);
 catalog.slots[6].working.payload_sha256[0]^=2;AfCatalog lut_before=catalog;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_INVALID&&!memcmp(&lut_before,&catalog,sizeof(catalog)));catalog=original;
 assert(!memcmp(&manager_before,&manager,sizeof(manager))&&!memcmp(&old_names,&labels,sizeof(labels)));
 /* 排队后继续调参必须拒绝，而不是把旧快照或新工作值偷偷存入记录。 */
 assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_OK);assert(af_edit(&catalog,7,0,2)==AF_OK);
 assert(af_repository_execute(&repository,&manager,0)==AF_STALE&&!manager.receipt.durable);
 assert(!strcmp(labels.slots[6].text,"Warm"));rename_original_unchanged(old,bytes);
 struct stat st;assert(fstatat(repository.posix.directory,"C07_B.rec",&st,AT_SYMLINK_NOFOLLOW)<0);
 AfSlot before=catalog.slots[6],other_slot=catalog.slots[19];AfLabel other_name=labels.slots[19];assert(af_dirty(&catalog,7)==1);
 run(&q);assert(catalog.slots[6].saved_revision==2&&af_dirty(&catalog,7)==1);rename_presets_same(&before,&catalog.slots[6]);
 assert(labels.slots[6].bytes==63&&!memcmp(labels.slots[6].text,q.name,63));
 assert(!memcmp(&other_slot,&catalog.slots[19],sizeof(other_slot))&&!memcmp(&other_name,&labels.slots[19],sizeof(other_name)));
 AfDocument d;assert(af_store_snapshot(&repository.stores[6],&buffers,&d)==AF_STORE_OK&&d.present&&d.name_bytes==63&&!memcmp(d.name,q.name,63));
 assert(!memcmp(&d.initial,&before.initial,sizeof(AfPreset))&&!memcmp(&d.saved,&before.saved,sizeof(AfPreset)));rename_original_unchanged(old,bytes);
 assert(af_repository_close(&repository)==0);open_repository(fd);
 assert(catalog.slots[6].saved_revision==2&&!memcmp(&catalog.slots[6].initial,&before.initial,sizeof(AfPreset))&&
        !memcmp(&catalog.slots[6].saved,&before.saved,sizeof(AfPreset))&&!memcmp(&catalog.slots[6].working,&before.saved,sizeof(AfPreset))&&af_dirty(&catalog,7)==0);
 assert(labels.slots[6].bytes==63&&!memcmp(labels.slots[6].text,q.name,63));rename_original_unchanged(old,bytes);assert(af_repository_close(&repository)==0);
}
static void rename_failure(int fd,int after_publish){
 (void)setup_overwrite(fd);AfApManageRequest q=rename_request();AfCatalog before=catalog;AfLabels names_before=labels;
 uint8_t old[4096+32];size_t bytes=rename_original(old,sizeof(old));real_io=repository.io;
 if(after_publish)repository.io.sync_directory=fail_directory_sync;else repository.io.sync_data=fail_data_sync;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_OK);int wanted=after_publish?AF_STORE_UNCERTAIN:AF_STORE_IO;
 assert(af_repository_execute(&repository,&manager,0)==wanted);
 assert(!manager.receipt.durable&&!manager.receipt.generation&&manager.receipt.uncertain==(uint32_t)after_publish&&manager.phase==(after_publish?AF_MANAGE_UNCERTAIN:AF_MANAGE_FAILED));
 assert(!memcmp(&before,&catalog,sizeof(catalog))&&!memcmp(&names_before,&labels,sizeof(labels))&&af_dirty(&catalog,7)==1);
 repository.io=real_io;rename_original_unchanged(old,bytes);struct stat st;assert(fstatat(repository.posix.directory,"C07_B.new",&st,AT_SYMLINK_NOFOLLOW)<0);
 if(after_publish){
  assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_BUSY&&repository.stores[6].uncertain&&!repository.stores[6].ready);
  assert(af_repository_recover(&repository,7)==AF_OK&&manager.phase==AF_MANAGE_UNCERTAIN);
  /* 显式recover沿既有load契约丢弃未保存值；改名没有把dirty工作值存入saved。 */
  assert(catalog.slots[6].saved_revision==2&&!memcmp(&catalog.slots[6].initial,&before.slots[6].initial,sizeof(AfPreset))&&
         !memcmp(&catalog.slots[6].saved,&before.slots[6].saved,sizeof(AfPreset))&&!memcmp(&catalog.slots[6].working,&before.slots[6].saved,sizeof(AfPreset))&&af_dirty(&catalog,7)==0);
  assert(labels.slots[6].bytes==63&&!memcmp(labels.slots[6].text,q.name,63));
  assert(!memcmp(&catalog.slots[19],&before.slots[19],sizeof(AfSlot))&&af_ap_manage_recovered(&manager)==AF_OK&&manager.phase==AF_MANAGE_FAILED);
 }else{
  assert(fstatat(repository.posix.directory,"C07_B.rec",&st,AT_SYMLINK_NOFOLLOW)<0&&repository.stores[6].ready&&!repository.stores[6].uncertain&&repository.stores[6].generation==1);
 }
 assert(af_repository_close(&repository)==0);open_repository(fd);
 assert(catalog.slots[6].saved_revision==(after_publish?2u:1u)&&!memcmp(&catalog.slots[6].saved,&before.slots[6].saved,sizeof(AfPreset))&&
        !memcmp(&catalog.slots[6].working,&before.slots[6].saved,sizeof(AfPreset)));
 if(after_publish)assert(labels.slots[6].bytes==63&&!memcmp(labels.slots[6].text,q.name,63));
 else assert(!strcmp(labels.slots[6].text,"Warm"));
 rename_original_unchanged(old,bytes);assert(af_repository_close(&repository)==0);
}

int main(int argc,char **argv){assert(argc==3);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);switch(argv[2][0]){case '0':flow(fd);break;case '1':rejected(fd);break;case '2':failures(fd);break;case '3':service(fd);break;case '4':imported(fd,0);break;case '5':imported(fd,1);break;case '6':overwrite_flow(fd);break;case '7':overwrite_failure(fd,0);break;case '8':overwrite_failure(fd,1);break;case '9':clear_flow(fd);break;case 'a':clear_failure(fd,0);break;case 'b':clear_failure(fd,1);break;case 'c':rename_flow(fd);break;case 'd':rename_failure(fd,0);break;case 'e':rename_failure(fd,1);break;default:abort();}assert(close(fd)==0);return 0;}
'''
@pytest.fixture(scope='module')
def driver(tmp_path_factory):
    d=tmp_path_factory.mktemp('repo-build');source=d/'driver.c';source.write_text(HARNESS);binary=d/'repository'
    names=['af_repository.c','af_repository_service.c','af_repository_import.c','af_media.c','af_posix.c','af_labels.c','af_labels_store.c','af_ap_manage.c',
           'af_persist.c','af_store.c','af_document.c','af_record.c','af_sha256.c','af_slots.c','af_ui.c',
           'af_import.c','af_joint.c','af_joint_fit.c','af_joint_asset.c','af_joint_report.c',
           'af_grid.c','af_grid_fit.c','af_cube.c']
    r=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(source),
        *[str(NATIVE/n) for n in names],str(NATIVE.parent/'tests/native_joint_target.c'),'-o',str(binary)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    return binary
@pytest.mark.parametrize('case',['0','1','2','3','4','5','6','7','8','9','a','b','c','d','e'],ids=['save-copy-boot-isolation','namespace-alias-protection','cancel-stale-no-model','service-binding-and-reopen','explicit-test-model-file-import','import-workspaces-cannot-corrupt-owned-state','overwrite-confirmation-staleness-and-reopen','overwrite-failure-before-publish','overwrite-uncertain-requires-explicit-recovery','clear-confirmation-staleness-tombstone-and-recreate','clear-failure-before-publish','clear-uncertain-recovery-does-not-resurrect','rename-dirty-preserved-stale-refused-and-reopen','rename-failure-before-publish','rename-uncertain-requires-explicit-recovery'])
def test_repository_os_chain(driver,tmp_path,case):
    r=subprocess.run([str(driver),str(tmp_path),case],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
