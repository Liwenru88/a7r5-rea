"""实际文件、显式测试模型、分批转换、保存和独立服务恢复；非相机成像验收。"""
import subprocess

import pytest

from test_native_repository import HARNESS, NATIVE

EXTRA = r'''
#include "af_sha256.h"
static AfJointModel service_model;
static AfGridSample train[8],valid_colors[4];
static AfImportRequest parameters;
static char input_source[1024];static float cells[24];
static const char cube[]="LUT_3D_SIZE 2\n0 0 0\n1 0 0\n.015625 1 0\n1.015625 1 0\n0 .015625 1.015625\n1 .015625 1.03125\n.015625 1.015625 1.015625\n1.015625 1.015625 1.03125\n";
static void configure(void){
 service_model=(AfJointModel){0};service_model.schema=service_model.base_mask=service_model.domain=1;
 service_model.components=15;service_model.model_sha256[0]=0x20;service_model.predict=af_joint_synthetic_predict;
 memcpy(service_model.cp_sha256,af_joint_cp_sha256,32);
 for(unsigned i=0;i<129;++i)seed.gamma[i]=i*1024;
 unsigned n=0;for(unsigned b=0;b<2;++b)for(unsigned g=0;g<2;++g)for(unsigned r=0;r<2;++r)
  train[n++]=(AfGridSample){{.1f+.6f*r,.15f+.55f*g,.12f+.5f*b},1,0};
 valid_colors[0]=(AfGridSample){{.22f,.22f,.22f},1,1};valid_colors[1]=(AfGridSample){{.41f,.41f,.41f},1,1};
 valid_colors[2]=(AfGridSample){{.61f,.39f,.28f},1,2};valid_colors[3]=(AfGridSample){{.8f,.2f,.55f},1,0};
 parameters=(AfImportRequest){0};parameters.model=&service_model;parameters.seed=&seed;
 parameters.initial.params[6]=3;parameters.training=train;parameters.training_count=8;
 parameters.validation=valid_colors;parameters.validation_count=4;parameters.options=(AfJointOptions){65,256,16,16,16,4};
}
/* 仅测试提供者边界；底层仍为临时普通目录，不代表原Fsys执行。 */
static struct {uint64_t token;int fd,reads;} media_context={0x1234567812345678ULL,-1,0};
static int provider_scan(void *ctx,uint64_t g,AfMediaList *w,AfMediaList *o){
 assert(ctx==&media_context&&media_context.token==0x1234567812345678ULL);
 return af_media_scan(media_context.fd,g,w,o);
}
static int provider_read(void *ctx,const AfMediaList *l,uint32_t index,void *out,size_t cap,
 AfMediaSource *info,AfGridProgress progress,void *context){
 assert(ctx==&media_context&&media_context.token==0x1234567812345678ULL);++media_context.reads;
 return af_media_read(media_context.fd,l,index,out,cap,info,progress,context);
}
static const char long_file[]="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa暖光影.cube";
static const char long_filter[]="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa...";
int main(int argc,char **argv){
 assert(argc==3);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);
 const char *file_name=strstr(argv[2],"long")?long_file:"暖光.cube";
 const char *filter_name=strstr(argv[2],"long")?long_filter:"暖光";
 int f=openat(fd,file_name,O_WRONLY|O_CREAT|O_EXCL,0600);assert(f>=0&&write(f,cube,sizeof(cube)-1)==sizeof(cube)-1&&close(f)==0);
 af_catalog_init(&catalog);af_ap_manage_init(&manager);int status;
 void *s=af_repository_service_open(fd,&catalog,&labels,&status);assert(s&&!status);
 AfApMediaImporter importer;assert(af_repository_service_media_importer(s,&importer)==0);
 assert(af_media_scan(fd,11,&media_work,&listing)==0&&listing.count==1);
 AfApMediaInfo info={0};info.generation=11;
 assert(af_media_read(fd,&listing,0,input_source,sizeof(input_source),&info.source,0,0)==0);
 assert(importer.prepare(s,fd,&listing,&info)==AF_MANAGE_NOT_READY);
 configure();AfRepositoryImport binding={0};binding.source=input_source;binding.source_capacity=sizeof(input_source);
 binding.parameters=&parameters;binding.cube_storage=cells;binding.cube_capacity=24;binding.work=&import_work;binding.candidate=&candidate;
 service_model.components=8;assert(af_repository_service_bind_import(s,&binding)==AF_INVALID);
 /* 未绑定模型仍可导入电脑配方；上方CUBE prepare必须保持NOT_READY。 */
 assert(af_repository_service_capabilities(s)==0x3f);service_model.components=15;
 assert(af_repository_service_bind_import(s,&binding)==0&&af_repository_service_capabilities(s)==0x3f);
 AfMediaList malformed=listing;memset(malformed.entries[0].name,'a',94);
 memcpy(malformed.entries[0].name+89,".cube",5);malformed.entries[0].name[80]=(char)0xff;malformed.entries[0].name[94]=0;
 assert(importer.prepare(s,fd,&malformed,&info)==AF_INVALID);
 if(argv[2][0]=='h')info.source.sha256[0]^=1;
 assert(importer.prepare(s,fd,&listing,&info)==0);
 assert(af_repository_service_bind_import(s,0)==AF_PERSIST_BUSY);
 AfApManageRequest q;assert(importer.request(s,&q)==0&&q.media_generation==11&&q.media_index==0&&q.op==3);
 assert(q.name_bytes==strlen(filter_name)&&!memcmp(q.name,filter_name,q.name_bytes));q.target_slot=7;
 assert(af_ap_manage_submit(&manager,&catalog,&q)==0);
 assert(af_repository_service_pump(s,&manager)==AF_JOINT_MORE&&manager.phase==AF_MANAGE_RUNNING&&!catalog.slots[6].present);
 assert(af_repository_service_close(s)==AF_PERSIST_BUSY&&af_repository_service_bind_import(s,0)==AF_PERSIST_BUSY);
 if(argv[2][0]=='c')assert(af_ap_manage_cancel(&manager,manager.job.ticket)==0);
 unsigned polls=0;do{status=af_repository_service_pump(s,&manager);assert(++polls<30);}while(status==AF_JOINT_MORE);
 if(argv[2][0]=='s'){
  assert(status==0&&polls>=4&&manager.phase==AF_MANAGE_DONE&&manager.receipt.durable&&manager.receipt.generation==1);
  assert(catalog.slots[6].saved.kind==1&&candidate.fit.attempted_components==15&&candidate.report.samples==4);
  /* 使用实际不透明服务导出，覆盖旧319字节缓冲不足以承载AJR1的边界。 */
  assert(mkdirat(fd,"library",0700)==0);int library=openat(fd,"library",O_RDONLY|O_DIRECTORY);assert(library>=0);
  assert(af_repository_service_bind_library(s,library)==0&&af_edit(&catalog,7,0,4)==0);
  q=(AfApManageRequest){0};q.op=AF_MANAGE_EXPORT;q.source_slot=q.target_slot=7;
  assert(af_ap_manage_submit(&manager,&catalog,&q)==0&&af_repository_service_pump(s,&manager)==0);
  int file=openat(library,"C07_G0000000000000001.a7filter",O_RDONLY);assert(file>=0);
  uint8_t raw[4096];ssize_t bytes=read(file,raw,sizeof(raw));assert(bytes>1943&&close(file)==0&&close(library)==0);
  AfDocument exported;assert(af_document_decode(raw,(size_t)bytes,AF_JOINT_ASSET_SCHEMA,&exported)==0);
  assert(exported.image_bytes==1943&&!memcmp(exported.image,candidate.image,1943)&&af_dirty(&catalog,7)==1);
 }else assert(status<0&&manager.phase==(argv[2][0]=='c'?AF_MANAGE_CANCELLED:AF_MANAGE_FAILED)&&!manager.receipt.durable&&!catalog.slots[6].present);
 assert(af_repository_service_close(s)==0);assert(unlinkat(fd,file_name,0)==0);
 af_catalog_init(&catalog);s=af_repository_service_open(fd,&catalog,&labels,&status);assert(s&&!status);
 assert(catalog.slots[6].present==(uint32_t)(argv[2][0]=='s'));
 if(catalog.slots[6].present)assert(catalog.slots[6].working.kind==1&&!strcmp(labels.slots[6].text,filter_name));
 assert(af_repository_service_close(s)==0&&close(fd)==0);return 0;
}
'''


@pytest.fixture(scope='module',params=['posix','provider','fsys'])
def driver(tmp_path_factory,request):
    folder = tmp_path_factory.mktemp('import-service')
    source = folder / 'driver.c'
    extra=EXTRA
    if request.param in ('provider','fsys'):
        extra=extra.replace('AfApMediaImporter importer;assert(af_repository_service_media_importer(s,&importer)==0);',
            'AfApMediaProviderImporter importer;assert(af_repository_service_media_provider_importer(s,&importer)==0);\n'
            ' media_context.fd=fd;AfMediaProvider provider={1,sizeof(provider),&media_context,provider_scan,provider_read};')
        extra=extra.replace('importer.prepare(s,fd,','importer.prepare(s,&provider,')
        extra=extra.replace('if(argv[2][0]==\'c\')assert(',
            'provider.read=0; /* 任务持有复制后的绑定。 */\n if(argv[2][0]==\'c\')assert(')
        extra=extra.replace('assert(af_repository_service_close(s)==0);assert(unlinkat',
            'assert(media_context.reads==(argv[2][0]==\'c\'?0:1));assert(af_repository_service_close(s)==0);assert(unlinkat')
    if request.param=='fsys':
        # 实际原生适配器承接64位token／Find私有游标，再进入同一仓库事务。
        # 只有最下层卷端口用临时文件；不宣称原Fsys机器码或SD硬件已执行。
        port=(NATIVE.parent/'tests/fsys406_service_port.c').read_text()
        anchor='int main(int argc,char **argv){'
        assert extra.count(anchor)==1
        extra=extra.replace(anchor,port+'\n'+anchor)
        extra=extra.replace('return af_media_scan(media_context.fd,g,w,o);',
                            'return af_fsys406_scan(&fsys_service,g,w,o);')
        extra=extra.replace('return af_media_read(media_context.fd,l,index,out,cap,info,progress,context);',
                            'return af_fsys406_read(&fsys_service,l,index,out,cap,info,progress,context);')
        # 包装函数在端口定义之前，显式提前声明唯一驻留context。
        extra='#include "af_fsys406.h"\nstatic AfFsys406 fsys_service;\n'+extra
        extra=extra.replace('media_context.fd=fd;AfMediaProvider provider={1,sizeof(provider),&media_context,provider_scan,provider_read};',
                            'AfMediaProvider provider;fsys_port_prepare(fd,file_name,&provider);')
        extra=extra.replace('af_media_scan(fd,11,&media_work,&listing)',
                            'provider.scan(provider.context,11,&media_work,&listing)')
        extra=extra.replace('af_media_read(fd,&listing,0,input_source,sizeof(input_source),&info.source,0,0)',
                            'provider.read(provider.context,&listing,0,input_source,sizeof(input_source),&info.source,0,0)')
        extra=extra.replace("media_context.reads==(argv[2][0]=='c'?0:1)",
                            "media_context.reads==(argv[2][0]=='c'?1:2)")
    source.write_text(HARNESS.split('int main(int argc,char **argv)')[0] + extra)
    binary = folder / 'driver'
    names = ('af_repository.c', 'af_repository_service.c', 'af_repository_import.c', 'af_media.c', 'af_posix.c',
             'af_labels.c', 'af_labels_store.c', 'af_ap_manage.c', 'af_persist.c', 'af_store.c',
             'af_document.c', 'af_record.c', 'af_sha256.c', 'af_slots.c', 'af_ui.c', 'af_import.c',
             'af_joint.c', 'af_joint_fit.c', 'af_joint_asset.c', 'af_joint_report.c', 'af_grid.c', 'af_grid_fit.c', 'af_cube.c')
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                          '-I' + str(NATIVE), str(source), *[str(NATIVE / n) for n in names],
                          *([str(NATIVE/'af_fsys406.c')] if request.param=='fsys' else []),
                          str(NATIVE.parent / 'tests/native_joint_target.c'), '-o', str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return binary


@pytest.mark.parametrize('case', ['success', 'cancel', 'hash-changed', 'success-long'])
def test_bound_service_import_is_cooperative_and_durable(driver, tmp_path, case):
    run = subprocess.run([str(driver), str(tmp_path), case], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
