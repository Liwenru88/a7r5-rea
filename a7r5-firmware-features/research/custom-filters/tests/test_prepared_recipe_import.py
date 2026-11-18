"""电脑配方双入口：宿主C和临时目录，不运行目标指令或访问设备。"""
import subprocess

import pytest

from test_native_repository import HARNESS, NATIVE


DRIVER = r'''
#include "af_sha256.h"
static uint8_t file_bytes[4096],read_bytes[4096],original_image[AF_JOINT_ASSET_MAX_BYTES];
static size_t file_size,original_size;
static const char *filename="电脑配方.A7FILTER";
static AfPreset expected_initial,expected_saved;
static AfFitReport expected_report;
static const char filter_name[]="暖色胶片";
static struct {int fd,reads;} provider_context;
static int provider_scan(void *p,uint64_t g,AfMediaList *w,AfMediaList *o){
 assert(p==&provider_context);return af_media_scan(provider_context.fd,g,w,o);
}
static int provider_read(void *p,const AfMediaList *l,uint32_t i,void *out,size_t cap,
 AfMediaSource *meta,AfGridProgress progress,void *user){
 assert(p==&provider_context);++provider_context.reads;
 return af_media_read(provider_context.fd,l,i,out,cap,meta,progress,user);
}
static void patch32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(v>>(8*i));}
static void repair_image_hashes(void){
 size_t at=AF_DOCUMENT_HEADER+strlen(filter_name);uint8_t digest[32];
 memset(file_bytes+at+96,0,32);assert(af_sha256(file_bytes+at,AF_JOINT_ASSET_BYTES,digest)==0);
 memcpy(file_bytes+at+96,digest,32);assert(af_sha256(file_bytes+at,AF_JOINT_ASSET_BYTES,digest)==0);
 memcpy(file_bytes+98,digest,32);memcpy(file_bytes+172,digest,32);
}
static void make_file(int fd,const char *mode){
 AfJointAsset asset={0};asset.base=0;asset.model_sha256[0]=0x31;
 asset.native_mode=strcmp(mode,"ajr1")!=0;
 for(unsigned i=0;i<129;++i){asset.recipe.gamma[i]=i*1024;if(asset.native_mode)asset.native_seed[i]=i*1024;}
 asset.recipe.matrix[0]=2;asset.recipe.cc1[0]=1;asset.recipe.grid[0]=3;
 int mono=!strncmp(mode,"bw",2)||(!strcmp(mode,"se")||!strncmp(mode,"se-",3));
 if(mono){asset.base=mode[0]=='b'?8:9;asset.matrix_mode=strstr(mode,"sector")!=0;memset(asset.recipe.matrix,0,sizeof asset.recipe.matrix);
  if(asset.matrix_mode){for(unsigned e=0;e<3;++e)for(unsigned s=0;s<16;++s)asset.sector_matrix[e*96+s*6]=(int16_t)(s+1);if(strstr(mode,"ambiguous"))asset.sector_matrix[96+7*6]++;}
  else{for(unsigned e=0;e<3;++e)asset.recipe.matrix[6*e]=2;if(strstr(mode,"ambiguous"))asset.recipe.matrix[6]++;}
 }
 size_t n;assert(af_joint_asset_encode(&asset,original_image,sizeof original_image,&n)==0);original_size=n;
 AfDocument d={0};d.present=1;d.name=filter_name;d.name_bytes=strlen(filter_name);
 d.initial.base=(uint8_t)asset.base;d.initial.params[6]=3;d.saved=d.initial;d.saved.params[0]=2;
 if(strcmp(mode,"pure")){
  d.initial.kind=1;d.initial.lut_sha256[0]=0x21;assert(af_sha256(original_image,n,d.initial.payload_sha256)==0);
  d.saved=d.initial;d.saved.params[0]=2;d.schema=AF_JOINT_ASSET_SCHEMA;d.converter=af_joint_asset_converter(&asset);
  d.image=original_image;d.image_bytes=n;d.report.samples=43;d.report.scope=1;
  d.report.delta_e[0]=100;d.report.delta_e[1]=200;d.report.delta_e[2]=300;
  d.report.delta_e[3]=70;d.report.delta_e[4]=90;memcpy(d.report.model_sha256,asset.model_sha256,32);
 }
 assert(af_document_encode(&d,AF_JOINT_ASSET_SCHEMA,file_bytes,sizeof file_bytes,&file_size)==0);
 expected_initial=d.initial;expected_saved=d.saved;expected_report=d.report;
 size_t at=AF_DOCUMENT_HEADER+strlen(filter_name);
 if(!strcmp(mode,"cp")){file_bytes[at+32]^=1;repair_image_hashes();}
 if(!strcmp(mode,"model"))file_bytes[56]^=1;
 if(!strcmp(mode,"seed")){file_bytes[at+128+300]^=1;repair_image_hashes();}
 if(!strcmp(mode,"converter"))patch32(file_bytes+12,99);
 if(!strcmp(mode,"future"))file_bytes[4]=2;
 if(!strcmp(mode,"trailing"))file_bytes[file_size++]=0;
 if(!strcmp(mode,"tombstone")){AfDocument empty={0};assert(!af_document_encode(&empty,0,file_bytes,sizeof file_bytes,&file_size));}
 int f=openat(fd,filename,O_WRONLY|O_CREAT|O_EXCL,0600);
 assert(f>=0&&write(f,file_bytes,file_size)==(ssize_t)file_size&&!close(f));
}
static void check_saved(unsigned slot){
 assert(catalog.slots[slot-1].present&&!memcmp(&catalog.slots[slot-1].initial,&expected_initial,sizeof expected_initial));
 assert(!memcmp(&catalog.slots[slot-1].saved,&expected_saved,sizeof expected_saved));
 assert(!memcmp(&catalog.slots[slot-1].working,&expected_saved,sizeof expected_saved));
 assert(!strcmp(labels.slots[slot-1].text,filter_name)&&!af_dirty(&catalog,slot));
}
int main(int argc,char **argv){
 assert(argc==4);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);
 const char *mode=argv[2];
 if(!strcmp(mode,"external")){
  int f=openat(fd,filename,O_RDONLY);assert(f>=0);ssize_t bytes=read(f,file_bytes,sizeof file_bytes);assert(bytes>0&&!close(f));
  file_size=(size_t)bytes;AfDocument d;assert(!af_document_decode(file_bytes,file_size,AF_JOINT_ASSET_SCHEMA,&d));
  assert(d.name_bytes==strlen(filter_name)&&!memcmp(d.name,filter_name,d.name_bytes));
  expected_initial=d.initial;expected_saved=d.saved;expected_report=d.report;
  assert(af_joint_asset_size_valid(d.image_bytes));original_size=d.image_bytes;memcpy(original_image,d.image,original_size);
 }else make_file(fd,mode);
 af_catalog_init(&catalog);af_ap_manage_init(&manager);int status;
 void *service=af_repository_service_open(fd,&catalog,&labels,&status);assert(service&&!status);
 assert(af_repository_service_capabilities(service)&AF_MANAGE_CAP(AF_MANAGE_IMPORT));
 assert(!af_media_scan(fd,11,&media_work,&listing)&&listing.count==1);
 AfApMediaInfo info={0};info.generation=11;
 assert(!af_media_read(fd,&listing,0,read_bytes,sizeof read_bytes,&info.source,0,0));
 AfApMediaImporter importer;AfApMediaProviderImporter supplied;
 AfMediaProvider p={1,sizeof p,&provider_context,provider_scan,provider_read};provider_context.fd=fd;
 int use_provider=argv[3][0]=='p';
 if(use_provider){assert(!af_repository_service_media_provider_importer(service,&supplied));
  assert(!supplied.prepare(service,&p,&listing,&info));}
 else {assert(!af_repository_service_media_importer(service,&importer));assert(!importer.prepare(service,fd,&listing,&info));}
 AfApManageRequest q;
 assert(!(use_provider?supplied.request(service,&q):importer.request(service,&q)));
 q.target_slot=7;
 if(!strcmp(mode,"overlay")){
  q.target_slot=6;assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_INVALID);q.overwrite=1;
 }
 assert(!af_ap_manage_submit(&manager,&catalog,&q));
 assert(af_repository_service_pump(service,&manager)==AF_JOINT_MORE);
 assert(af_repository_service_close(service)==AF_PERSIST_BUSY);
 if(!strcmp(mode,"cancel"))assert(!af_ap_manage_cancel(&manager,manager.job.ticket));
 if(!strcmp(mode,"changed")){
  int f=openat(fd,filename,O_WRONLY);assert(f>=0);uint8_t x='X';assert(pwrite(f,&x,1,256)==1&&!close(f));
 }
 unsigned polls=0;do{status=af_repository_service_pump(service,&manager);assert(++polls<5);}while(status==AF_JOINT_MORE);
 int success=!strcmp(mode,"success")||!strcmp(mode,"pure")||!strcmp(mode,"overlay")||!strcmp(mode,"external")||((!strncmp(mode,"bw",2)||(!strcmp(mode,"se")||!strncmp(mode,"se-",3)))&&!strstr(mode,"ambiguous"));
 if(success){
  assert(!status&&manager.phase==AF_MANAGE_DONE&&manager.receipt.durable&&manager.receipt.generation==1);
  check_saved(q.target_slot);
  /* 从实际仓库导出再解码：源文件的报告、初始值和保存值均保持。 */
  assert(!mkdirat(fd,"library",0700));int library=openat(fd,"library",O_RDONLY|O_DIRECTORY);assert(library>=0);
  assert(!af_repository_service_bind_library(service,library));
  AfApManageRequest e={0};e.op=AF_MANAGE_EXPORT;e.source_slot=e.target_slot=q.target_slot;
  assert(!af_ap_manage_submit(&manager,&catalog,&e)&&!af_repository_service_pump(service,&manager));
  char name[80];snprintf(name,sizeof name,"C%02u_G0000000000000001.a7filter",q.target_slot);
  int f=openat(library,name,O_RDONLY);assert(f>=0);ssize_t n=read(f,read_bytes,sizeof read_bytes);assert(n>0&&!close(f));
  AfDocument decoded;assert(!af_document_decode(read_bytes,(size_t)n,AF_JOINT_ASSET_SCHEMA,&decoded));
  assert(!memcmp(&decoded.report,&expected_report,sizeof expected_report));
  if(decoded.image_bytes)assert(decoded.image_bytes==original_size&&!memcmp(decoded.image,original_image,original_size));
  assert(af_document_report_applies(&decoded,&decoded.saved)==
   (!memcmp(&decoded.initial,&decoded.saved,sizeof(decoded.initial))));
  /* 已保存导出可直接回导另一个槽，不依赖源CUBE或预测器。 */
  assert(!af_media_scan(library,12,&media_work,&listing)&&listing.count==1);
  info.generation=12;assert(!af_media_read(library,&listing,0,file_bytes,sizeof file_bytes,&info.source,0,0));
  if(use_provider){provider_context.fd=library;assert(!supplied.prepare(service,&p,&listing,&info));assert(!supplied.request(service,&e));}
  else {assert(!importer.prepare(service,library,&listing,&info));assert(!importer.request(service,&e));}
  e.target_slot=20;assert(!af_ap_manage_submit(&manager,&catalog,&e));
  do{status=af_repository_service_pump(service,&manager);}while(status==AF_JOINT_MORE);
  assert(!status);check_saved(20);assert(!close(library));
 }else{
  assert(status<0&&!manager.receipt.durable&&!catalog.slots[6].present);if(strstr(mode,"ambiguous"))assert(status==AF_JOINT_ASSET_UNSUPPORTED);
  assert(manager.phase==(!strcmp(mode,"cancel")?AF_MANAGE_CANCELLED:AF_MANAGE_FAILED));
 }
 assert(!af_repository_service_close(service));assert(!unlinkat(fd,filename,0));
 af_catalog_init(&catalog);service=af_repository_service_open(fd,&catalog,&labels,&status);assert(service&&!status);
 if(success){check_saved(q.target_slot);check_saved(20);}else assert(!catalog.slots[6].present);
 assert(!af_repository_service_close(service)&&!close(fd));return 0;
}
'''


@pytest.fixture(scope='module')
def driver(tmp_path_factory):
    folder = tmp_path_factory.mktemp('prepared-recipe-host')
    source, binary = folder / 'driver.c', folder / 'driver'
    source.write_text(HARNESS.split('int main(int argc,char **argv)')[0] + DRIVER)
    names = ('af_repository.c', 'af_repository_service.c', 'af_repository_import.c',
             'af_media.c', 'af_posix.c', 'af_labels.c', 'af_labels_store.c', 'af_ap_manage.c',
             'af_persist.c', 'af_store.c', 'af_document.c', 'af_record.c', 'af_sha256.c',
             'af_slots.c', 'af_ui.c', 'af_import.c', 'af_joint.c', 'af_joint_fit.c',
             'af_joint_asset.c', 'af_joint_report.c', 'af_grid.c', 'af_grid_fit.c', 'af_cube.c')
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-function', '-I' + str(NATIVE), str(source),
        *[str(NATIVE / n) for n in names], str(NATIVE.parent / 'tests/native_joint_target.c'),
        '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize('mode', ['success', 'pure', 'overlay'])
@pytest.mark.parametrize('provider', ['fd', 'provider'])
def test_prepared_import_without_fitter_and_saved_export_roundtrip(driver, tmp_path, mode, provider):
    result = subprocess.run([str(driver), str(tmp_path), mode, provider], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('mode', ['ajr1', 'cp', 'model', 'seed', 'converter', 'future',
                                 'trailing', 'tombstone', 'changed', 'cancel'])
def test_bad_or_cancelled_prepared_file_never_changes_target(driver, tmp_path, mode):
    result = subprocess.run([str(driver), str(tmp_path), mode, 'fd'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_desktop_pack_output_enters_actual_service_without_conversion(driver, tmp_path):
    from test_recipe_file_tool import asset, metadata, tool

    meta = metadata()
    meta['name'] = '暖色胶片'
    with tool.native_codec() as api:
        packed = tool.pack(asset(), meta, api)
    (tmp_path / '电脑配方.A7FILTER').write_bytes(packed)
    result = subprocess.run([str(driver), str(tmp_path), 'external', 'fd'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


TRANSACTION = r'''
#include "af_repository_import.h"
static AfRepositoryImportTask task;
static uint8_t source_memory[4096];
int main(int argc,char **argv){
 assert(argc==3);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);make_file(fd,"success");
 af_catalog_init(&catalog);af_labels_init(&labels);af_ap_manage_init(&manager);
 assert(!af_repository_open(&repository,fd,1,AF_JOINT_ASSET_SCHEMA,4096,&buffers,&catalog,&labels));
 AfApManageRequest q=create_request(7);run(&q);AfCatalog before=catalog;AfLabels names=labels;
 uint8_t old[4096];size_t old_size=rename_original(old,sizeof old);
 assert(!af_media_scan(fd,9,&media_work,&listing));AfMediaSource expected;
 assert(!af_media_read(fd,&listing,0,read_bytes,sizeof read_bytes,&expected,0,0));
 AfRepositoryImport input={0};input.directory=fd;input.listing=&listing;
 input.source=source_memory;input.source_capacity=sizeof source_memory;
 q=(AfApManageRequest){0};q.op=AF_MANAGE_IMPORT;q.target_slot=7;q.overwrite=1;
 q.media_generation=9;q.initial.params[6]=3;q.name_bytes=1;q.name[0]='X';
 assert(!af_ap_manage_submit(&manager,&catalog,&q));
 assert(af_repository_import_start(&task,&repository,&manager,&input,&expected)==AF_JOINT_MORE);
 assert(af_repository_import_poll(&task,64)==AF_JOINT_MORE&&task.phase==AF_REPOSITORY_IMPORT_COMMIT);
 int mode=atoi(argv[2]),wanted;
 if(mode==0){source_memory[256]^=1;wanted=AF_STALE;}
 else if(mode==1){assert(!af_edit(&catalog,7,0,3));before=catalog;wanted=AF_STALE;}
 else if(mode==2){assert(!af_ap_manage_cancel(&manager,manager.job.ticket));wanted=AF_MANAGE_CANCEL;}
 else {real_io=repository.io;if(mode==3)repository.io.sync_data=fail_data_sync;
       else repository.io.sync_directory=fail_directory_sync;wanted=mode==3?AF_STORE_IO:AF_STORE_UNCERTAIN;}
 assert(af_repository_import_poll(&task,64)==wanted&&!manager.receipt.durable);
 if(mode>=3)repository.io=real_io;
 assert(!memcmp(&before,&catalog,sizeof before)&&!memcmp(&names,&labels,sizeof names));
 rename_original_unchanged(old,old_size);
 if(mode==4){
  assert(manager.phase==AF_MANAGE_UNCERTAIN&&repository.stores[6].uncertain);
  assert(af_ap_manage_submit(&manager,&catalog,&q)==AF_BUSY);
  assert(!af_repository_recover(&repository,7));check_saved(7);
  assert(!af_ap_manage_recovered(&manager));
 }else assert(manager.phase==(mode==2?AF_MANAGE_CANCELLED:AF_MANAGE_FAILED));
 assert(!af_repository_close(&repository)&&!close(fd));return 0;
}
'''


@pytest.fixture(scope='module')
def transaction_driver(tmp_path_factory):
    folder = tmp_path_factory.mktemp('prepared-transaction-host')
    source, binary = folder / 'driver.c', folder / 'driver'
    source.write_text(HARNESS.split('int main(int argc,char **argv)')[0]
                      + DRIVER.split('int main(int argc,char **argv)')[0] + TRANSACTION)
    names = ('af_repository.c', 'af_repository_service.c', 'af_repository_import.c',
             'af_media.c', 'af_posix.c', 'af_labels.c', 'af_labels_store.c', 'af_ap_manage.c',
             'af_persist.c', 'af_store.c', 'af_document.c', 'af_record.c', 'af_sha256.c',
             'af_slots.c', 'af_ui.c', 'af_import.c', 'af_joint.c', 'af_joint_fit.c',
             'af_joint_asset.c', 'af_joint_report.c', 'af_grid.c', 'af_grid_fit.c', 'af_cube.c')
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-function', '-I' + str(NATIVE), str(source),
        *[str(NATIVE / n) for n in names], str(NATIVE.parent / 'tests/native_joint_target.c'),
        '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize('mode', range(5))
def test_prepared_commit_staleness_cancellation_and_durability_failures(transaction_driver, tmp_path, mode):
    result = subprocess.run([str(transaction_driver), str(tmp_path), str(mode)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('mode', ['bw','se','bw-sector','se-sector','bw-ambiguous','se-ambiguous','bw-sector-ambiguous','se-sector-ambiguous'])
@pytest.mark.parametrize('provider', ['fd','provider'])
def test_monochrome_prepared_import_policy_preserves_format(driver, tmp_path, mode, provider):
    result = subprocess.run([str(driver), str(tmp_path), mode, provider], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
