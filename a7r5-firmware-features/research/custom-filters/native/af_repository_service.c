#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#include "af_repository_service.h"
#include "af_persist.h"
#include "af_repository_import.h"
#include "af_text.h"
#include "af_repository_recipe.h"
#ifdef AF_REFERENCE_IMPORT406
#include "af_reference_import.h"
#endif
#ifdef AF_TARGET_GLIBC225
#include "af_target_posix.h"
extern void *calloc(size_t,size_t);
extern void free(void *);
#else
#include <stdlib.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif
typedef struct {
    AfRepository repository;
    uint8_t memory[3][AF_DOCUMENT_MAX+AF_RECORD_HEADER];
    uint8_t export_memory[AF_DOCUMENT_MAX];
    int library;
    uint32_t busy;
    AfRepositoryImportTask import_task;
    AfRepositoryImport import_binding,input;
    AfMediaList listing;
    AfMediaSource expected;
    AfApManageRequest selection;
    int selected_directory;
    AfMediaProvider selected_provider;
    uint32_t import_bound,selected;
    /* 已拟合文件无需借用机内模型或CUBE工作区。 */
    uint8_t prepared_source[AF_PREPARED_FILE_MAX];
} Service;
static int separate(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
void *af_repository_service_open(int parent,AfCatalog *catalog,AfLabels *labels,int *status){
    if(!status)return NULL;
    Service *s=calloc(1,sizeof(*s));if(!s){*status=AF_STORE_CAPACITY;return NULL;}
    s->library=s->selected_directory=-1;
    AfStoreBuffers b={s->memory[0],s->memory[1],s->memory[2],sizeof(s->memory[0])};
    /* 标记与纯参数记录不迁移；只显式扩展可解码的内部文档能力。 */
    *status=af_repository_open_documents(&s->repository,parent,1,0,AF_JOINT_ASSET_SCHEMA,AF_DOCUMENT_MAX,&b,catalog,labels);
    if(*status!=AF_STORE_OK&&*status!=AF_REPOSITORY_PARTIAL){free(s);return NULL;}
    return s;
}
uint32_t af_repository_service_capabilities(void *context){
    Service *s=context;return s&&s->repository.opened?
        AF_MANAGE_CAP_PERSIST|AF_MANAGE_CAP(AF_MANAGE_IMPORT)|
        (s->library>=0?AF_MANAGE_CAP(AF_MANAGE_EXPORT):0):0;
}
int af_repository_service_bind_library(void *context,int directory){
    Service *s=context;struct stat media,body;
    if(!s||!s->repository.opened||directory< -1)return AF_STORE_INVALID;
    if(s->busy||af_repository_import_busy(&s->import_task))return AF_PERSIST_BUSY;
    int next=-1;
    if(directory>=0){
        next=fcntl(directory,F_DUPFD_CLOEXEC,0);if(next<0)return AF_STORE_IO;
        if(fstat(next,&media)||!S_ISDIR(media.st_mode)||fstat(s->repository.posix.directory,&body)||
           (body.st_dev==media.st_dev&&body.st_ino==media.st_ino)){(void)close(next);return AF_STORE_INVALID;}
    }
    int old=s->library;s->library=next;
    return old>=0&&close(old)?AF_STORE_IO:AF_STORE_OK;
}
static int selection_cancel(void *context){
    Service *s=context;if(!s)return AF_INVALID;
    if(s->busy||af_repository_import_busy(&s->import_task))return AF_BUSY;
    int fd=s->selected_directory;s->selected_directory=-1;s->selected=0;
    return fd>=0&&close(fd)?AF_STORE_IO:AF_OK;
}
int af_repository_service_bind_import(void *context,const AfRepositoryImport *b){
    Service *s=context;if(!s||!s->repository.opened)return AF_STORE_INVALID;
    if(s->busy||s->selected||af_repository_import_busy(&s->import_task))return AF_PERSIST_BUSY;
    if(!b){s->import_bound=0;return AF_OK;}
    const AfImportRequest *q=b->parameters;
    if(!q||!separate(b,sizeof(*b),s,sizeof(*s))||!separate(q,sizeof(*q),s,sizeof(*s))||
       af_validate(&q->initial)!=AF_OK||q->initial.kind||
       af_joint_model_valid(q->model,q->initial.base)!=AF_OK||q->model->base_mask!=(1u<<q->initial.base)||
       af_joint_valid(q->seed)!=AF_OK||q->training_count<2||q->training_count>AF_JOINT_SAMPLES||
       q->validation_count<3||q->validation_count>AF_GRID_SAMPLES||!q->training||!q->validation||
       q->options.evaluations<9||q->options.evaluations>AF_JOINT_EVALUATIONS||
       !b->source_capacity||b->source_capacity>AF_MEDIA_SOURCE_MAX||b->cube_capacity<24||
       b->cube_capacity>33u*33u*33u*3u||
       !separate(b->source,b->source_capacity,s,sizeof(*s))||
       !separate(b->cube_storage,b->cube_capacity*sizeof(float),s,sizeof(*s))||
       !separate(b->work,sizeof(*b->work),s,sizeof(*s))||
       !separate(b->candidate,sizeof(*b->candidate),s,sizeof(*s)))return AF_INVALID;
    s->import_binding=*b;s->import_bound=1;return AF_OK;
}
static int import_display_name(const char *name,size_t n,AfApManageRequest *request){
    unsigned kind=af_media_kind(name,n);if(!kind)return AF_INVALID;
    /* 先验证完整原文件名，短默认名不能掩盖后部非法UTF8。 */
    for(size_t at=0;at<n;){
        size_t end=at+63;if(end>n)end=n;
        while(end<n&&((uint8_t)name[end]&0xc0u)==0x80u)--end;
        if(end==at||!af_text_name_valid(name+at,end-at))return AF_INVALID;
        at=end;
    }
    size_t bytes=n-(kind==AF_MEDIA_CUBE?5u:9u),prefix=bytes;
    if(bytes>63){
        prefix=60;
        while(prefix&&((uint8_t)name[prefix]&0xc0u)==0x80u)--prefix;
    }
    for(size_t i=0;i<prefix;++i)request->name[i]=name[i];
    if(bytes>63){request->name[prefix++]='.';request->name[prefix++]='.';request->name[prefix++]='.';}
    request->name_bytes=(uint32_t)prefix;return AF_OK;
}
static int selection_prepare_common(void *context,int directory,const AfMediaProvider *provider,
                                    const AfMediaList *list,const AfApMediaInfo *info){
    Service *s=context;struct stat st;
    if(!s||!s->repository.opened)return AF_MANAGE_NOT_READY;
    if(s->busy||af_repository_import_busy(&s->import_task))return AF_BUSY;
    if((provider?(directory!=-1||!af_media_provider_valid(provider)):directory<0)||
       !list||!info||!info->generation||info->reserved||
       info->generation!=list->generation||list->count>AF_MEDIA_MAX||info->index>=list->count||
       !info->source.bytes||info->source.bytes>AF_MEDIA_SOURCE_MAX||
       info->source.bytes!=list->entries[info->index].size||
       !separate(list,sizeof(*list),s,sizeof(*s))||!separate(info,sizeof(*info),s,sizeof(*s)))return AF_INVALID;
    if(provider&&(!separate(provider,sizeof(*provider),s,sizeof(*s))||
       !separate(provider->context,1,s,sizeof(*s))))return AF_INVALID;
    AfApManageRequest next={0};next.op=AF_MANAGE_IMPORT;next.initial.params[6]=3;
    next.media_generation=info->generation;next.media_index=info->index;
    const char *name=list->entries[info->index].name;size_t n=0;
    while(n<AF_MEDIA_NAME_BYTES&&name[n])++n;
    unsigned kind=af_media_kind(name,n);
    if(!kind)return AF_INVALID;
    if(kind==AF_MEDIA_CUBE){
        if(!s->import_bound)return AF_MANAGE_NOT_READY;
        next.initial=s->import_binding.parameters->initial;
    }else if(info->source.bytes>AF_PREPARED_FILE_MAX)return AF_INVALID;
    if(import_display_name(name,n,&next)!=AF_OK)return AF_INVALID;
    AfDocument document={0};uint8_t encoded[AF_DOCUMENT_HEADER+AF_DOCUMENT_NAME_MAX];size_t count;
    document.present=1;document.initial=document.saved=next.initial;document.name=next.name;document.name_bytes=next.name_bytes;
    if(af_document_encode(&document,0,encoded,sizeof(encoded),&count))return AF_INVALID;
    int fd=-1;
    if(!provider){
        fd=fcntl(directory,F_DUPFD_CLOEXEC,0);if(fd<0)return AF_STORE_IO;
        if(fstat(fd,&st)||!S_ISDIR(st.st_mode)||(uint64_t)st.st_dev!=list->device||
           (uint64_t)st.st_ino!=list->inode){(void)close(fd);return AF_STALE;}
    }
    int released=selection_cancel(s);if(released){if(fd>=0)(void)close(fd);return released;}
    s->selected_directory=fd;s->listing=*list;s->expected=info->source;s->selection=next;s->selected=1;
    s->input=kind==AF_MEDIA_CUBE?s->import_binding:(AfRepositoryImport){0};
    if(kind==AF_MEDIA_PREPARED){s->input.source=s->prepared_source;s->input.source_capacity=sizeof(s->prepared_source);}
    s->input.directory=fd;s->input.listing=&s->listing;s->input.provider=NULL;
    if(provider){s->selected_provider=*provider;s->input.provider=&s->selected_provider;}
    return AF_OK;
}
static int selection_prepare(void *context,int directory,const AfMediaList *list,const AfApMediaInfo *info){
    return selection_prepare_common(context,directory,NULL,list,info);
}
static int selection_prepare_provider(void *context,const AfMediaProvider *p,const AfMediaList *list,const AfApMediaInfo *info){
    return selection_prepare_common(context,-1,p,list,info);
}
static int selection_request(void *context,AfApManageRequest *out){
    Service *s=context;if(!s||!out||!separate(out,sizeof(*out),s,sizeof(*s)))return AF_INVALID;
    if(!s->selected||af_repository_import_busy(&s->import_task))return AF_MANAGE_NOT_READY;
    *out=s->selection;return AF_OK;
}
int af_repository_service_media_importer(void *context,AfApMediaImporter *out){
    Service *s=context;if(!s||!s->repository.opened||!out||!separate(out,sizeof(*out),s,sizeof(*s)))return AF_INVALID;
    *out=(AfApMediaImporter){AF_AP_MEDIA_VERSION,sizeof(*out),s,selection_prepare,selection_request,selection_cancel};return AF_OK;
}
int af_repository_service_media_provider_importer(void *context,AfApMediaProviderImporter *out){
    Service *s=context;if(!s||!s->repository.opened||!out||!separate(out,sizeof(*out),s,sizeof(*s)))return AF_INVALID;
    *out=(AfApMediaProviderImporter){AF_AP_MEDIA_VERSION,sizeof(*out),s,selection_prepare_provider,selection_request,selection_cancel};return AF_OK;
}
int af_repository_service_pump(void *context,AfApManage *manager){
    Service *s=context;if(!s||!s->repository.opened)return AF_STORE_INVALID;
    if(s->busy)return AF_PERSIST_BUSY;
    s->busy=1;
    int status;
    if(af_repository_import_busy(&s->import_task)){
        status=manager==s->import_task.manager?af_repository_import_poll(&s->import_task,64):AF_BUSY;
    }else if(manager&&manager->phase==AF_MANAGE_QUEUED&&manager->job.request.op==AF_MANAGE_IMPORT){
        const AfApManageRequest *q=&manager->job.request;
        int match=s->selected&&q->media_generation==s->selection.media_generation&&
            q->media_index==s->selection.media_index&&q->name_bytes==s->selection.name_bytes;
        if(match)for(size_t i=0;i<sizeof(q->initial);++i)if(((const uint8_t *)&q->initial)[i]!=((const uint8_t *)&s->selection.initial)[i])match=0;
        if(match)for(uint32_t i=0;i<q->name_bytes;++i)if(q->name[i]!=s->selection.name[i])match=0;
        status=match?af_repository_import_start(&s->import_task,&s->repository,manager,&s->input,&s->expected):
            af_repository_execute(&s->repository,manager,NULL);
    }else status=manager&&manager->phase==AF_MANAGE_QUEUED&&manager->job.request.op==AF_MANAGE_EXPORT?
        af_repository_export(&s->repository,manager,s->library,s->export_memory,sizeof(s->export_memory)):
        af_repository_execute(&s->repository,manager,NULL);
    int complete=s->import_task.phase==AF_REPOSITORY_IMPORT_FINISHED;
    s->busy=0;if(complete)selection_cancel(s);
    return status;
}
#ifdef AF_RECIPE_BRIDGE406
static int same_recipe_preset(const AfPreset *a,const AfPreset *b){
    unsigned difference=a->base^b->base;difference|=a->kind^b->kind;
    for(unsigned i=0;i<8;++i)difference|=(uint8_t)a->params[i]^(uint8_t)b->params[i];
    for(unsigned i=0;i<32;++i){difference|=a->payload_sha256[i]^b->payload_sha256[i];difference|=a->lut_sha256[i]^b->lut_sha256[i];}
    return !difference;
}
int af_repository_service_recipe_capture(void *context,uint32_t slot,const AfPreset *expected,
    uint64_t session,uint64_t version,AfRecipeTx *out){
    Service *s=context;
    if(!s||!s->repository.opened||!session||!version||slot<1||slot>AF_USERS||
       af_validate(expected)!=AF_OK||expected->kind!=1||
       !separate(expected,sizeof(*expected),s,sizeof(*s))||!separate(out,sizeof(*out),s,sizeof(*s))||
       !separate(expected,sizeof(*expected),out,sizeof(*out)))return AF_INVALID;
    if(s->busy||af_repository_import_busy(&s->import_task))return AF_BUSY;
    const AfSlot *entry=&s->repository.catalog->slots[slot-1];
    if(!same_recipe_preset(expected,&entry->working))return AF_STALE;
    uint64_t revision=entry->saved_revision;s->busy=1;
    int result=af_repository_recipe_capture(&s->repository,slot,revision,session,version,out);
    if(result==AF_STORE_OK)result=af_repository_recipe_current(&s->repository,out,revision);
    if(result==AF_STORE_OK&&!same_recipe_preset(expected,&out->message.preset))result=AF_STORE_STALE;
    s->busy=0;
    if(result==AF_STORE_OK)return AF_OK;
    if(result==AF_STORE_STALE||result==AF_STORE_CONFLICT)return AF_STALE;
    if(result==AF_PERSIST_BUSY)return AF_BUSY;
    if(result==AF_STORE_INVALID||result==AF_STORE_UNSUPPORTED)return AF_INVALID;
    return AF_IO;
}
#else
int af_repository_service_recipe_capture(void *context,uint32_t slot,const AfPreset *expected,
    uint64_t session,uint64_t version,AfRecipeTx *out){
    (void)context;(void)slot;(void)expected;(void)session;(void)version;(void)out;return AF_INVALID;
}
#endif
int af_repository_service_close(void *context){
    Service *s=context;if(!s)return AF_STORE_INVALID;
    if(s->busy||af_repository_import_busy(&s->import_task))return AF_PERSIST_BUSY;
    int released=selection_cancel(s);
    int failed=s->library>=0&&close(s->library),status=af_repository_close(&s->repository);
#ifdef AF_REFERENCE_IMPORT406
    af_reference_import_closed(s);
#endif
    free(s);return released?released:failed?AF_STORE_IO:status;
}
