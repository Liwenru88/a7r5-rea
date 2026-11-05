#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#include "af_repository.h"
#include "af_persist.h"
#ifdef AF_TARGET_GLIBC225
#include "af_target_posix.h"
#else
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
#include <stdio.h>
#endif
static int equal(const void *a,const void *b,size_t n){const uint8_t *x=a,*y=b;for(size_t i=0;i<n;++i)if(x[i]!=y[i])return 0;return 1;}
static int apart(const void *a,size_t n,const void *b,size_t m){uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);}
static int text(const char *a,const char *b){for(size_t i=0;i<128;++i){if(a[i]!=b[i])return 0;if(!a[i])return 1;}return 0;}
static void word(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(v>>(i*8));}
static int private_directory(int fd){struct stat s;return !fstat(fd,&s)&&S_ISDIR(s.st_mode)&&s.st_uid==geteuid()&&!(s.st_mode&0022);}
static int space(int fd,size_t payload){struct statvfs s;if(fstatvfs(fd,&s)||!s.f_frsize||(s.f_flag&ST_RDONLY))return AF_STORE_IO;
    uint64_t blocks=s.f_bavail,unit=s.f_frsize,need=AF_REPOSITORY_RESERVE+payload+AF_RECORD_HEADER;
    return blocks>UINT64_MAX/unit || blocks*unit>=need?AF_STORE_OK:AF_STORE_CAPACITY;}
static int regular(int fd,size_t bytes){struct stat s;return !fstat(fd,&s)&&S_ISREG(s.st_mode)&&s.st_nlink==1&&s.st_uid==geteuid()&&s.st_size>=0&&(uint64_t)s.st_size==bytes;}
static int marker(int directory,int created,uint32_t schema,size_t payload){
    static const uint8_t baseline[32]={0x3c,0xb8,0x7f,0xd4,0x1d,0xe7,0xbf,0x66,0x93,0x37,0x5b,0xac,0x66,0xd7,0x80,0x55,0x6d,0x87,0xe1,0xf7,0x32,0x70,0xca,0xdb,0x1a,0x8f,0x02,0xeb,0x8c,0x0f,0x24,0xc2};
    uint8_t wanted[96]={0},got[96];const char magic[]="A7STORE1";size_t at=0;int status=AF_STORE_OK;
    for(unsigned i=0;i<8;++i)wanted[i]=(uint8_t)magic[i];word(wanted+8,1);word(wanted+12,(uint32_t)payload);word(wanted+16,schema);word(wanted+20,20);
    for(unsigned i=0;i<32;++i)wanted[24+i]=baseline[i];
    int fd=openat(directory,"STORE.ID",(created?O_WRONLY|O_CREAT|O_EXCL:O_RDONLY)|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC,0600);
    if(fd<0)return AF_STORE_INVALID;
    if(created){while(at<sizeof(wanted)){ssize_t n=write(fd,wanted+at,sizeof(wanted)-at);if(n<0&&errno==EINTR)continue;if(n<=0){status=AF_STORE_IO;break;}at+=(size_t)n;}
        if(!status&&fsync(fd))status=AF_STORE_IO;
    }else{if(!regular(fd,sizeof(got)))status=AF_STORE_INVALID;
        while(!status&&at<sizeof(got)){ssize_t n=read(fd,got+at,sizeof(got)-at);if(n<0&&errno==EINTR)continue;if(n<=0){status=AF_STORE_IO;break;}at+=(size_t)n;}
        if(!status&&!equal(got,wanted,sizeof(got)))status=AF_STORE_UNSUPPORTED;}
    if(close(fd)&&!status)status=AF_STORE_IO;return status;
}
static int known_name(const char *n){
    if(text(n,"STORE.ID")||text(n,"OWNER.LCK"))return 1;
    if(n[0]!='C'||n[1]<'0'||n[1]>'2'||n[2]<'0'||n[2]>'9'||n[3]!='_'||(n[4]!='A'&&n[4]!='B')||n[5]!='.')return 0;
    unsigned slot=(unsigned)(n[1]-'0')*10u+(unsigned)(n[2]-'0');return slot>=1&&slot<=20&&(text(n+6,"rec")||text(n+6,"new"));
}
static int contents(int directory,size_t max){
    int fd=openat(directory,".",O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(fd<0)return AF_STORE_IO;
    DIR *d=fdopendir(fd);if(!d){(void)close(fd);return AF_STORE_IO;}int status=0;unsigned count=0;struct dirent *e;struct stat s;
    for(;;){errno=0;e=readdir(d);if(!e){if(errno)status=AF_STORE_IO;break;}if(text(e->d_name,".")||text(e->d_name,".."))continue;
        if(++count>82 || !known_name(e->d_name)||fstatat(directory,e->d_name,&s,AT_SYMLINK_NOFOLLOW)||!S_ISREG(s.st_mode)||s.st_nlink!=1||s.st_uid!=geteuid()||s.st_size<0||(uint64_t)s.st_size>max+AF_RECORD_HEADER){status=AF_STORE_INVALID;break;}}
    if(closedir(d)&&!status)status=AF_STORE_IO;return status;
}
size_t af_repository_bytes(void){return sizeof(AfRepository);}
int af_repository_recover(AfRepository *r,uint32_t slot){
    if(!r||!r->opened||!slot||slot>AF_USERS)return AF_STORE_INVALID;
    uint32_t bit=1u<<(slot-1);int status=af_persist_load(r->catalog,&r->stores[slot-1],&r->io,&r->buffers,1);
    if(!status)status=af_labels_from_store(r->labels,r->catalog,&r->stores[slot-1],&r->buffers,1);
    if(status==AF_STORE_MISSING&&r->stores[slot-1].ready)status=AF_STORE_OK;
    r->status[slot-1]=status;
    if(status){r->ready_mask&=~bit;r->error_mask|=bit;r->stores[slot-1].ready=0;}
    else{r->ready_mask|=bit;r->error_mask&=~bit;}
    return status;
}
int af_repository_open(AfRepository *r,int parent,int create,uint32_t schema,size_t payload,
                       const AfStoreBuffers *buffers,AfCatalog *catalog,AfLabels *labels){
    return af_repository_open_documents(r,parent,create,schema,schema,payload,buffers,catalog,labels);
}
int af_repository_open_documents(AfRepository *r,int parent,int create,uint32_t marker_schema,
                       uint32_t document_schema,size_t payload,const AfStoreBuffers *buffers,
                       AfCatalog *catalog,AfLabels *labels){
    AfRepository next={0};int directory=-1,created=0,status;
    if((create!=0&&create!=1)||payload<AF_DOCUMENT_HEADER||payload>AF_DOCUMENT_MAX||!buffers||buffers->capacity<payload+AF_RECORD_HEADER||
       !apart(r,sizeof(*r),catalog,sizeof(*catalog))||!apart(r,sizeof(*r),labels,sizeof(*labels))||!apart(catalog,sizeof(*catalog),labels,sizeof(*labels))||
       !private_directory(parent))return AF_STORE_INVALID;
    if(r->opened)return AF_PERSIST_BUSY;
    const void *objects[]={r,catalog,labels,buffers,buffers->a,buffers->b,buffers->next};
    const size_t sizes[]={sizeof(*r),sizeof(*catalog),sizeof(*labels),sizeof(*buffers),buffers->capacity,buffers->capacity,buffers->capacity};
    for(unsigned i=0;i<7;++i)for(unsigned j=0;j<i;++j)if(!apart(objects[i],sizes[i],objects[j],sizes[j]))return AF_STORE_INVALID;
    for(unsigned i=0;i<AF_USERS;++i)if(catalog->slots[i].present||catalog->slots[i].saved_revision||catalog->slots[i].pending.request)return AF_STORE_INVALID;
    if(create){if(!mkdirat(parent,AF_REPOSITORY_NAMESPACE,0700))created=1;else if(errno!=EEXIST)return AF_STORE_IO;}
    directory=openat(parent,AF_REPOSITORY_NAMESPACE,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(directory<0)return AF_STORE_IO;
    if(!private_directory(directory)){status=AF_STORE_INVALID;goto fail;}
    if((status=marker(directory,created,marker_schema,payload))!=AF_STORE_OK)goto fail;
    if(created&&(fsync(directory)||fsync(parent))){status=AF_STORE_IO;goto fail;}
    if((status=contents(directory,payload))!=AF_STORE_OK)goto fail;
    next.owner_fd=openat(directory,"OWNER.LCK",O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600);
    if(next.owner_fd<0){status=AF_STORE_IO;goto fail;}
    if(!regular(next.owner_fd,0)||flock(next.owner_fd,LOCK_EX|LOCK_NB)){status=AF_PERSIST_BUSY;goto fail_owner;}
    if(af_posix_init(&next.posix,directory,&next.io)){status=AF_STORE_INVALID;goto fail_owner;}
    if(close(directory)){directory=-1;status=AF_STORE_IO;(void)af_posix_close(&next.posix);goto fail_owner;}directory=-1;
    next.schema=document_schema;next.catalog=catalog;next.labels=labels;next.buffers=*buffers;next.opened=1;
    for(unsigned i=0;i<AF_USERS;++i)if(af_store_init(&next.stores[i],i+1,document_schema,payload)){status=AF_STORE_INVALID;(void)af_posix_close(&next.posix);goto fail_owner;}
    *r=next;r->io.context=&r->posix;af_labels_init(labels);
    for(uint32_t slot=1;slot<=AF_USERS;++slot)(void)af_repository_recover(r,slot);
    return r->error_mask?AF_REPOSITORY_PARTIAL:AF_STORE_OK;
fail_owner:(void)close(next.owner_fd);
fail:if(directory>=0)(void)close(directory);return status;
}
int af_repository_close(AfRepository *r){if(!r||!r->opened)return AF_STORE_INVALID;int status=af_posix_close(&r->posix);if(close(r->owner_fd))status=-1;r->opened=0;return status?AF_STORE_IO:AF_STORE_OK;}
typedef struct{AfApManage *manager;uint64_t ticket;uint32_t fitting;} Task;
static int progress(void *context,uint32_t done,uint32_t total){Task *t=context;if(!total||done>total)return 1;
    uint32_t part=t->fitting?100000u:0u,range=t->fitting?900000u:100000u;
    uint32_t value=part+(uint32_t)((uint64_t)done*range/total);
    return af_ap_manage_progress(t->manager,t->ticket,value,1000000)!=AF_OK || af_ap_manage_cancelled(t->manager,t->ticket)!=0;}
typedef struct{const void *p;size_t bytes;} Region;
static int import_independent(const AfRepository *r,const AfApManage *manager,const AfRepositoryImport *i){
    const AfImportRequest *q=i->parameters;
    if(i->provider&&(i->directory!=-1||!af_media_provider_valid(i->provider)))return 0;
    if(!q->model||!q->seed||!q->training||!q->validation||!i->source_capacity||
       i->cube_capacity<24||i->cube_capacity>33u*33u*33u*3u||i->cube_capacity>SIZE_MAX/sizeof(float)||
       q->training_count<2||q->training_count>AF_JOINT_SAMPLES||q->validation_count<3||q->validation_count>AF_GRID_SAMPLES)return 0;
    const Region writes[]={{i->source,i->source_capacity},{i->cube_storage,i->cube_capacity*sizeof(float)},
                          {i->work,sizeof(*i->work)},{i->candidate,sizeof(*i->candidate)}};
    const Region borrowed[]={{r,sizeof(*r)},{r->catalog,sizeof(*r->catalog)},{r->labels,sizeof(*r->labels)},
        {manager,sizeof(*manager)},{r->buffers.a,r->buffers.capacity},{r->buffers.b,r->buffers.capacity},
        {r->buffers.next,r->buffers.capacity},{i,sizeof(*i)},{i->listing,sizeof(*i->listing)},
        {q,sizeof(*q)},{q->model,sizeof(*q->model)},{q->seed,sizeof(*q->seed)},
        {q->training,q->training_count*sizeof(*q->training)},{q->validation,q->validation_count*sizeof(*q->validation)}};
    /* 内层转换器不知道目录/管理器的所有权；必须在第一次媒体写入前隔离。
     * 模型context无大小字段，仍由可信唯一拥有者保持稳定，不猜测其内存范围。 */
    for(unsigned a=0;a<sizeof(writes)/sizeof(writes[0]);++a){
        if(!writes[a].p||(uintptr_t)writes[a].p>UINTPTR_MAX-writes[a].bytes)return 0;
        for(unsigned b=0;b<a;++b)if(!apart(writes[a].p,writes[a].bytes,writes[b].p,writes[b].bytes))return 0;
        for(unsigned b=0;b<sizeof(borrowed)/sizeof(borrowed[0]);++b)
            if(!apart(writes[a].p,writes[a].bytes,borrowed[b].p,borrowed[b].bytes))return 0;
        if(i->provider&&(!apart(writes[a].p,writes[a].bytes,i->provider,sizeof(*i->provider))||
           !apart(writes[a].p,writes[a].bytes,i->provider->context,1)))return 0;
    }
    return 1;
}
int af_repository_execute(AfRepository *r,AfApManage *manager,const AfRepositoryImport *import){
    AfApManageJob job;AfDocument document={0};AfApManageReceipt receipt={0};int status;
    if(!r||!r->opened||!manager)return AF_STORE_INVALID;
    status=af_ap_manage_take(manager,&job);if(status)return status;
    Task task={manager,job.ticket,0};uint32_t slot=job.request.target_slot;AfStore *store=&r->stores[slot-1];
    if(job.request.op==AF_MANAGE_EXPORT){status=AF_MANAGE_NOT_READY;goto finish;}
    if(!(r->ready_mask&(1u<<(slot-1)))){status=r->status[slot-1];goto finish;}
    if(job.request.op==AF_MANAGE_IMPORT){
        /* SD双入口由分批任务处理；同步旧接口不能把配方误送CUBE解析器。 */
        if(import&&import->listing&&job.request.media_index<import->listing->count&&
           job.request.media_index<AF_MEDIA_MAX){
            const char *name=import->listing->entries[job.request.media_index].name;size_t n=0;
            while(n<AF_MEDIA_NAME_BYTES&&name[n])++n;
            if(af_media_kind(name,n)==AF_MEDIA_PREPARED){status=AF_JOINT_ASSET_UNSUPPORTED;goto finish;}
        }
        if(!import||!import->parameters||!import->parameters->model||!import->listing||import->listing->generation!=job.request.media_generation){status=AF_MANAGE_NOT_READY;goto finish;}
        if(!import_independent(r,manager,import)){status=AF_STORE_INVALID;goto finish;}
        AfMediaSource source;status=af_repository_import_read(import,import->listing,job.request.media_index,&source,progress,&task);if(status)goto finish;
        AfImportRequest request=*import->parameters;request.source=import->source;request.source_bytes=source.bytes;request.name=job.request.name;request.name_bytes=job.request.name_bytes;request.initial=job.request.initial;
        task.fitting=1;
        status=af_import_cube(&request,import->cube_storage,import->cube_capacity,import->work,import->candidate,progress,&task);if(status)goto finish;
        status=af_import_document(import->candidate,&document);if(status)goto finish;
    }else if(job.request.op==AF_MANAGE_CREATE){document.present=1;document.initial=job.request.initial;document.saved=document.initial;document.name=job.request.name;document.name_bytes=job.request.name_bytes;}
    if((status=space(r->posix.directory,store->max_payload))!=0)goto finish;
    if((status=af_ap_manage_commit_begin(manager,r->catalog,job.ticket))!=0)goto finish;
    if(job.request.op==AF_MANAGE_SAVE)status=af_persist_save(r->catalog,store,&r->io,&r->buffers);
    else if(job.request.op==AF_MANAGE_COPY)status=af_persist_copy(r->catalog,&r->stores[job.request.source_slot-1],store,&r->io,&r->io,&r->buffers,job.request.name,job.request.name_bytes,(int)job.request.overwrite);
    else if(job.request.op==AF_MANAGE_CLEAR)status=af_persist_clear(r->catalog,store,&r->io,&r->buffers);
    else if(job.request.op==AF_MANAGE_RENAME)status=af_persist_rename(r->catalog,store,&r->io,&r->buffers,job.request.name,job.request.name_bytes);
    else status=af_persist_replace(r->catalog,store,&r->io,&r->buffers,&document,(int)job.request.overwrite);
    if(!status){status=af_labels_from_store(r->labels,r->catalog,store,&r->buffers,0);if(status){store->uncertain=1;store->ready=0;status=AF_STORE_UNCERTAIN;}}
finish:
    receipt.ticket=job.ticket;receipt.result=status;receipt.durable=status==0;receipt.uncertain=status==AF_STORE_UNCERTAIN;
    receipt.generation=status==AF_OK?store->generation:0;int completed=af_ap_manage_finish(manager,r->catalog,&receipt);
    if(completed!=AF_OK)return completed;
    return status;
}

static int export_independent(const AfRepository *r,const AfApManage *manager,const void *scratch,size_t capacity){
    return capacity && capacity<=AF_DOCUMENT_MAX &&
        apart(scratch,capacity,r,sizeof(*r)) && apart(scratch,capacity,manager,sizeof(*manager)) &&
        apart(scratch,capacity,r->catalog,sizeof(*r->catalog)) && apart(scratch,capacity,r->labels,sizeof(*r->labels)) &&
        apart(scratch,capacity,r->buffers.a,r->buffers.capacity) && apart(scratch,capacity,r->buffers.b,r->buffers.capacity) &&
        apart(scratch,capacity,r->buffers.next,r->buffers.capacity);
}
static int export_directory(const AfRepository *r,int library){
    struct stat body,media;
    if(fstat(library,&media)||!S_ISDIR(media.st_mode)||fstat(r->posix.directory,&body))return AF_STORE_INVALID;
    return body.st_dev==media.st_dev&&body.st_ino==media.st_ino?AF_STORE_INVALID:AF_STORE_OK;
}
static int export_file(int directory,const char *name,const uint8_t *raw,size_t bytes,int *created){
    struct stat initial,now;size_t at=0;int status=AF_STORE_OK;
    int fd=openat(directory,name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if(fd<0)return errno==EEXIST?AF_PERSIST_EXISTS:AF_STORE_IO;
    *created=1;
    if(fstat(fd,&initial)||!S_ISREG(initial.st_mode)||initial.st_nlink!=1||initial.st_size!=0)status=AF_STORE_UNCERTAIN;
    while(!status&&at<bytes){ssize_t n=write(fd,raw+at,bytes-at);if(n<0&&errno==EINTR)continue;
        if(n<=0){status=AF_STORE_UNCERTAIN;break;}at+=(size_t)n;}
    if(!status&&fsync(fd))status=AF_STORE_UNCERTAIN;
    if(close(fd))status=AF_STORE_UNCERTAIN;
    if(status)return status;
    fd=openat(directory,name,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
    if(fd<0)return AF_STORE_UNCERTAIN;
    if(fstat(fd,&now)||!regular(fd,bytes)||now.st_dev!=initial.st_dev||now.st_ino!=initial.st_ino)status=AF_STORE_UNCERTAIN;
    uint8_t block[1024];at=0;
    while(!status&&at<bytes){size_t wanted=bytes-at;if(wanted>sizeof(block))wanted=sizeof(block);
        ssize_t n=read(fd,block,wanted);if(n<0&&errno==EINTR)continue;
        if(n<=0){status=AF_STORE_UNCERTAIN;break;}
        if(!equal(block,raw+at,(size_t)n)){status=AF_STORE_UNCERTAIN;break;}at+=(size_t)n;}
    if(!status){uint8_t extra;ssize_t n;do{n=read(fd,&extra,1);}while(n<0&&errno==EINTR);
        if(n!=0||fstat(fd,&now)||!regular(fd,bytes)||now.st_dev!=initial.st_dev||now.st_ino!=initial.st_ino)status=AF_STORE_UNCERTAIN;}
    if(close(fd))status=AF_STORE_UNCERTAIN;
    if(!status&&fsync(directory))status=AF_STORE_UNCERTAIN;
    return status;
}
int af_repository_export(AfRepository *r,AfApManage *manager,int library,void *scratch,size_t capacity){
    AfApManageJob job;AfApManageReceipt receipt={0};size_t bytes=0;int status,created=0;char name[40];
    if(!r||!r->opened||!manager)return AF_STORE_INVALID;
    status=af_ap_manage_take(manager,&job);if(status)return status;
    AfStore *store=&r->stores[job.request.target_slot-1];
    if(job.request.op!=AF_MANAGE_EXPORT){status=AF_STORE_INVALID;goto finish;}
    if(library<0){status=AF_MANAGE_NOT_READY;goto finish;}
    if(!export_independent(r,manager,scratch,capacity)){status=AF_STORE_INVALID;goto finish;}
    if((status=export_directory(r,library))!=0)goto finish;
    if(!(r->ready_mask&(1u<<(store->slot-1)))){status=r->status[store->slot-1];goto finish;}
    if(store->uncertain){status=AF_MANAGE_NOT_READY;goto finish;}
    status=af_persist_export(r->catalog,store,&r->io,&r->buffers,0,scratch,capacity,&bytes);if(status)goto finish;
    if((status=space(library,bytes))!=0)goto finish;
    int n=snprintf(name,sizeof(name),"C%02u_G%016llx.a7filter",store->slot,(unsigned long long)job.target.revision);
    if(n<0||(size_t)n>=sizeof(name)){status=AF_STORE_INVALID;goto finish;}
    if((status=af_ap_manage_commit_begin(manager,r->catalog,job.ticket))!=0)goto finish;
    status=export_file(library,name,scratch,bytes,&created);
finish:
    receipt.ticket=job.ticket;receipt.result=status;receipt.durable=status==AF_STORE_OK;
    receipt.generation=status==AF_STORE_OK?job.target.revision:0;receipt.uncertain=status==AF_STORE_UNCERTAIN;
    int completed=af_ap_manage_finish(manager,r->catalog,&receipt);
    if(completed!=AF_OK&&created){
        /* 文件已创建后，连最终身份核对失败也不得伪装成确定的未发布。 */
        receipt.result=AF_STORE_UNCERTAIN;receipt.durable=0;receipt.generation=0;receipt.uncertain=1;
        if(af_ap_manage_finish(manager,r->catalog,&receipt)==AF_OK)return AF_STORE_UNCERTAIN;
    }
    return completed==AF_OK?status:completed;
}
