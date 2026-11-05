/* 原Fsys卷＋生产只读适配器；媒体快照为显式夹具，不运行机身应用或硬件。 */
#include "af_fsys406.h"
#include "af_document.h"
#include "af_repository_service.h"
#include "af_reference_import.h"
#include "af_sha256.h"
extern int printf(const char *,...),fflush(void *),snprintf(char *,size_t,const char *,...);
extern void *dlsym(void *,const char *);
typedef struct {const char *name;void *base;const char *symbol;void *address;} LibraryInfo;
extern int dladdr(const void *,LibraryInfo *);
extern int memcmp(const void *,const void *,size_t),strcmp(const char *,const char *);
extern void *memset(void *,int,size_t),*memcpy(void *,const void *,size_t);
extern void _exit(int);
extern int open(const char *,int,...),close(int),munmap(void *,size_t);
extern int mkdir(const char *,unsigned);
extern long read(int,void *,size_t),lseek(int,long,int);
extern void *mmap(void *,size_t,int,int,int,long);
extern void mcmn_init(void);
extern int32_t Fsys_Init(void),Fsys_Mount(const char *,uint32_t,char *,const void *);
extern int32_t Fsys_Mkdir(const char *),Fsys_Open(const char *,uint64_t *,uint32_t);
extern int32_t Fsys_Read(uint64_t,void *,int32_t),Fsys_Write(uint64_t,const void *,int32_t);
extern int32_t Fsys_Flush(uint64_t),Fsys_Close(uint64_t),Fsys_Unmount(unsigned char,uint32_t);
extern int32_t Fsys_FindFirst(const char *,uint8_t,void *),Fsys_FindNext(void *);
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start,%function\n_start:\nmov x0,sp\nbl entry\nbrk #0\n");
static AfFsys406 service;
static AfMediaList work,list;
static uint8_t source[4096],document[1024],snapshot_image[AF_FSYS406_SNAPSHOT_BYTES];
static const char cube[]="LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n";
static const char *names[]={"暖光.cube","电脑参数.a7filter","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa暖光影.cube"};
static uintptr_t library_base;
static AfCatalog catalog;
static AfLabels labels;
static AfApManage manager;
static void check(int ok,const char *at){if(!ok){printf("AF_VOLUME_FAIL %s\n",at);fflush(0);_exit(10);}}
static void call(const char *name,int32_t result){printf("AF_VOLUME_CALL %s result=%#x\n",name,(unsigned)result);fflush(0);check(!result,name);}
static int snapshot(void *ctx,uint8_t out[AF_FSYS406_SNAPSHOT_BYTES]){check(ctx==snapshot_image,"snapshot_context");memcpy(out,snapshot_image,AF_FSYS406_SNAPSHOT_BYTES);return AF_OK;}
static int encoding(void *ctx){check(ctx==&library_base,"encoding_context");return af_fsys406_utf8_policy(library_base,AF_FSYS406_LIBRARY_SPAN);}
static int cancel(void *ctx,uint32_t done,uint32_t total){(void)ctx;(void)total;return done!=0;}
static void find_log(const char *op,int32_t rc,void *out){
    uint8_t *p=out;uint64_t pointer=0;memcpy(&pointer,p,8);
    printf("AF_VOLUME_FIND %s rc=%#x pointer_delta=%ld attr=%#x short=%.*s long=%.*s\n",op,(unsigned)rc,(long)(pointer-(uintptr_t)p),(unsigned)p[0x26],13,p+0x5aa,128,p+0x5b7);fflush(0);
}
static int32_t first(const char *path,uint8_t attr,void *out){int32_t rc=Fsys_FindFirst(path,attr,out);find_log("first",rc,out);return rc;}
static int32_t next(void *out){int32_t rc=Fsys_FindNext(out);find_log("next",rc,out);return rc;}
static void put_file(char drive,const char *name,const void *bytes,size_t count){
    char path[256];snprintf(path,sizeof path,"%c:/Private/Sony/PRO/LUT/%s",drive,name);
    printf("AF_VOLUME_WRITE_PATH %s\n",path);fflush(0);
    uint64_t handle=0;call("OpenWrite",Fsys_Open(path,&handle,0xf));check(handle!=0,"write_token");
    check(Fsys_Write(handle,bytes,(int32_t)count)==(int32_t)count,"Write");call("Flush",Fsys_Flush(handle));call("CloseWrite",Fsys_Close(handle));
}
static void import_and_restore(const AfMediaProvider *provider){
    /* 普通客体目录承载生产仓库事务；不冒充机身/setting准入或掉电耐久性。 */
    check(!mkdir("/tmp/af-volume-body",0700),"body_directory");int fd=open("/tmp/af-volume-body",0);check(fd>=0,"body_fd");
    af_catalog_init(&catalog);af_ap_manage_init(&manager);int status=0;
    void *repository=af_repository_service_open(fd,&catalog,&labels,&status);check(repository&&!status,"repository_open");
    call("ReferenceImportBind",af_reference_import_bind(repository));
    AfApMediaProviderImporter importer;call("ProviderImporter",af_repository_service_media_provider_importer(repository,&importer));
    for(unsigned j=0;j<2;++j){
        unsigned index=0;while(index<list.count&&strcmp(list.entries[index].name,names[j]))++index;check(index<list.count,"import_index");
        AfApMediaInfo info={.generation=list.generation,.index=index};
        call("SelectedRead",provider->read(provider->context,&list,index,source,sizeof source,&info.source,0,0));
        call("ImportPrepare",importer.prepare(importer.context,provider,&list,&info));AfApManageRequest request;
        call("ImportRequest",importer.request(importer.context,&request));request.target_slot=7+j;
        call("ImportSubmit",af_ap_manage_submit(&manager,&catalog,&request));unsigned polls=0;
        do{status=af_repository_service_pump(repository,&manager);check(++polls<256,"import_budget");}while(status==AF_JOINT_MORE);
        call("ImportPump",status);check(manager.receipt.durable&&catalog.slots[6+j].present,"import_durable");
        check(catalog.slots[6+j].saved.kind==(j?0u:1u),"import_kind");
        printf("AF_VOLUME_IMPORTED slot=%u kind=%u generation=%lu polls=%u name=%s\n",7+j,(unsigned)catalog.slots[6+j].saved.kind,manager.receipt.generation,polls,labels.slots[6+j].text);fflush(0);
    }
    AfPreset expected[2]={catalog.slots[6].saved,catalog.slots[7].saved};
    call("RepositoryClose",af_repository_service_close(repository));af_catalog_init(&catalog);memset(&labels,0,sizeof labels);
    repository=af_repository_service_open(fd,&catalog,&labels,&status);check(repository&&!status,"repository_reopen");
    check(catalog.slots[6].present&&catalog.slots[7].present&&!memcmp(&expected[0],&catalog.slots[6].saved,sizeof expected[0])&&!memcmp(&expected[1],&catalog.slots[7].saved,sizeof expected[1]),"restore_exact_presets");
    call("RepositoryReclose",af_repository_service_close(repository));check(!close(fd),"body_close");
    printf("AF_VOLUME_RESTORED slots=7,8 source=production_repository_guest_directory\n");fflush(0);
}
static void export_volume(void){
    int fd=open("/image_mmca",0);check(fd>=0&&lseek(fd,0,2)==0x400000&&lseek(fd,0,0)==0,"export_file");
    int memory=open("/dev/mem",2);check(memory>=0,"export_memory");
    uint8_t *out=mmap(0,0x400000,3,1,memory,0x41e600000UL);close(memory);check(out!=(void *)-1,"export_map");
    size_t done=0;while(done<0x400000){long n=read(fd,out+done,0x400000-done);check(n>0,"export_read");done+=(size_t)n;}
    close(fd);uint8_t hash[32];check(!af_sha256(out,done,hash),"export_sha");
    __sync_synchronize();munmap(out,0x400000);
    printf("AF_VOLUME_EXPORTED bytes=%lu sha256=",done);for(unsigned i=0;i<32;++i)printf("%02x",hash[i]);printf("\n");fflush(0);
}
static int run(int argc,char **argv){
    check(argc==1||(argc==2&&!strcmp(argv[1],"long")),"arguments");uint32_t mount_flags=argc==2?0x400u:0;
    unsigned (*configured)(void)=dlsym(0,"af_volume_configured");check(configured!=0,"config_export");
    mcmn_init();check(configured()==1,"config_calls");call("Init",Fsys_Init());
    /* 原3174C..54把挂载flags bit10存入每卷65A8；FAT卷必须显式启用长名。
     * 原428E8..F8另在exFAT类型3时自动启用；不修改全局卷对象或产品挂载。 */
    printf("AF_VOLUME_MOUNT_FLAGS %#x\n",mount_flags);fflush(0);
    char drive=0;call("Mount",Fsys_Mount("/dev/mmca",mount_flags,&drive,0));check(drive>='A'&&drive<='Z',"drive");
    LibraryInfo info={0};check(dladdr(dlsym(0,"Fsys_Open"),&info)!=0&&info.base,"library_base");library_base=(uintptr_t)info.base;
    call("InitialUTF8Policy",encoding(&library_base));
    AfDocument d={.present=1,.name="电脑参数示例",.name_bytes=18};
    const int8_t params[8]={1,2,0,0,0,4,3,1};memcpy(d.initial.params,params,8);d.saved=d.initial;
    size_t document_bytes=0;check(!af_document_encode(&d,0,document,sizeof document,&document_bytes),"document_encode");
    put_file(drive,"PROBE.BIN",cube,sizeof cube-1);
    /* LUT库由独立主机VFAT夹具写入，符合用户从电脑复制至SD再机内只读导入的用途。
     * 原Fsys的短名写入只用于检查卸载持久化，不能把它当中文创建支持。 */
    call("UnmountWritten",Fsys_Unmount((unsigned char)drive,0));drive=0;
    call("Remount",Fsys_Mount("/dev/mmca",mount_flags,&drive,0));check(drive>='A'&&drive<='Z',"remount_drive");
    snapshot_image[0x19]=(uint8_t)drive;snapshot_image[0x1c]=3;
    AfFsys406Binding binding={.version=AF_FSYS406_VERSION,.bytes=sizeof binding,.snapshot_context=snapshot_image,.snapshot=snapshot,
      .fsys={Fsys_Open,Fsys_Read,Fsys_Close,first,next},.encoding_context=&library_base,.utf8_policy=encoding};
    call("AdapterInit",af_fsys406_init(&service,&binding));call("OriginalUTF8Policy",encoding(&library_base));
    AfMediaProvider provider={0};call("Provider",af_fsys406_provider(&service,&provider));
    call("Scan",provider.scan(provider.context,1,&work,&list));printf("AF_VOLUME_LIST_COUNT %u\n",list.count);fflush(0);check(list.count==3,"listing_count");
    for(unsigned i=0;i<list.count;++i){
        AfMediaSource metadata={0};call("ReadDoublePass",provider.read(provider.context,&list,i,source,sizeof source,&metadata,0,0));
        if(af_media_kind(list.entries[i].name,__builtin_strlen(list.entries[i].name))==AF_MEDIA_CUBE){
            check(metadata.bytes==sizeof cube-1&&!memcmp(source,cube,sizeof cube-1),"cube_exact");
            float cells[24],rgb[3]={0.25f,0.5f,0.75f},out[3];AfCube parsed;AfCubeLimits limits={2,sizeof source};
            check(!af_cube_parse((const char *)source,metadata.bytes,&parsed,cells,24,limits)&&!af_cube_eval(&parsed,rgb,out)&&!memcmp(rgb,out,sizeof rgb),"cube_parse_eval");
        }else{AfDocument parsed;check(!af_document_decode(source,metadata.bytes,0,&parsed)&&parsed.present&&parsed.name_bytes==18&&!memcmp(parsed.saved.params,params,8),"prepared_decode");}
        printf("AF_VOLUME_FILE name=%s bytes=%u sha256=",list.entries[i].name,metadata.bytes);for(unsigned j=0;j<32;++j)printf("%02x",metadata.sha256[j]);printf("\n");fflush(0);
    }
    AfMediaSource marker;memset(&marker,0xa5,sizeof marker);AfMediaSource before=marker;
    check(provider.read(provider.context,&list,0,source,sizeof source,&marker,cancel,0)==AF_GRID_CANCELLED&&!memcmp(&marker,&before,sizeof marker),"cancel_no_publish");
    snapshot_image[0x1c]=0;
    check(provider.read(provider.context,&list,0,source,sizeof source,&marker,0,0)==AF_STALE&&!memcmp(&marker,&before,sizeof marker),"stale_volume_no_publish");
    snapshot_image[0x1c]=3;import_and_restore(&provider);
    call("UnmountRead",Fsys_Unmount((unsigned char)drive,0));export_volume();
    printf("AF_VOLUME_DONE files=3 cancel=pass stale=pass source=original_fsys_file_backend\n");fflush(0);return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack){__libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();}
