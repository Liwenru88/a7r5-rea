#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#include "af_repository_import.h"
#include "af_persist.h"
#include "af_sha256.h"
#ifdef AF_TARGET_GLIBC225
#include "af_target_posix.h"
#else
#include <sys/statvfs.h>
#endif
typedef struct {const void *p;size_t n;} Region;
static void zero(void *p,size_t n){uint8_t *b=p;while(n--)*b++=0;}
static void copy(void *p,const void *q,size_t n){uint8_t *a=p;const uint8_t *b=q;while(n--)*a++=*b++;}
static int equal(const void *p,const void *q,size_t n){const uint8_t *a=p,*b=q;while(n--)if(*a++!=*b++)return 0;return 1;}
static int apart(const void *a,size_t n,const void *b,size_t m){uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);}
size_t af_repository_import_task_bytes(void){return sizeof(AfRepositoryImportTask);}
int af_repository_import_busy(const AfRepositoryImportTask *t){return t&&t->phase>=1&&t->phase<=3;}
int af_repository_import_init(AfRepositoryImportTask *t){
    if(!t||t->phase>AF_REPOSITORY_IMPORT_FINISHED)return AF_INVALID;
    if(af_repository_import_busy(t))return AF_BUSY;
    zero(t,sizeof(*t));return AF_OK;
}
static int owned(const AfRepositoryImportTask *t,const AfRepository *r,const AfApManage *m){
    return apart(t,sizeof(*t),r,sizeof(*r))&&apart(t,sizeof(*t),m,sizeof(*m))&&
        apart(t,sizeof(*t),r->catalog,sizeof(*r->catalog))&&apart(t,sizeof(*t),r->labels,sizeof(*r->labels))&&
        apart(t,sizeof(*t),r->buffers.a,r->buffers.capacity)&&apart(t,sizeof(*t),r->buffers.b,r->buffers.capacity)&&
        apart(t,sizeof(*t),r->buffers.next,r->buffers.capacity);
}
static int binding(const AfRepositoryImportTask *t,const AfRepository *r,const AfApManage *m,
                   const AfRepositoryImport *i,const AfMediaSource *expected,const AfApManageJob *job){
    if(!i||!expected)return AF_MANAGE_NOT_READY;
    if(r->schema!=AF_JOINT_ASSET_SCHEMA||job->request.op!=AF_MANAGE_IMPORT||!job->request.target_slot||job->request.target_slot>AF_USERS||
       (job->request.target_slot<=6&&job->request.overwrite!=1)||
       (i->provider?(i->directory!=-1||!af_media_provider_valid(i->provider)):i->directory<0)||
       !i->listing||!i->listing->generation||i->listing->generation!=job->request.media_generation||
       i->listing->count>AF_MEDIA_MAX||job->request.media_index>=i->listing->count||
       !expected->bytes||expected->bytes>AF_MEDIA_SOURCE_MAX||
       expected->bytes!=i->listing->entries[job->request.media_index].size||
       !i->source_capacity||i->source_capacity>AF_MEDIA_SOURCE_MAX||i->source_capacity<expected->bytes)return AF_INVALID;
    uint8_t hash=0;for(unsigned k=0;k<32;++k)hash|=expected->sha256[k];if(!hash)return AF_INVALID;
    const char *name=i->listing->entries[job->request.media_index].name;size_t n=0;
    while(n<AF_MEDIA_NAME_BYTES&&name[n])++n;
    unsigned kind=af_media_kind(name,n);if(!kind)return AF_INVALID;
    if(kind==AF_MEDIA_PREPARED){
        if(expected->bytes>AF_PREPARED_FILE_MAX)return AF_INVALID;
        const Region writes[]={{t,sizeof(*t)},{i->source,i->source_capacity}};
        const Region borrowed[]={{r,sizeof(*r)},{r->catalog,sizeof(*r->catalog)},{r->labels,sizeof(*r->labels)},
            {m,sizeof(*m)},{r->buffers.a,r->buffers.capacity},{r->buffers.b,r->buffers.capacity},
            {r->buffers.next,r->buffers.capacity},{i,sizeof(*i)},{i->listing,sizeof(*i->listing)},
            {expected,sizeof(*expected)}};
        for(unsigned a=0;a<2;++a){
            for(unsigned b=0;b<a;++b)if(!apart(writes[a].p,writes[a].n,writes[b].p,writes[b].n))return AF_INVALID;
            for(unsigned b=0;b<sizeof(borrowed)/sizeof(*borrowed);++b)
                if(!apart(writes[a].p,writes[a].n,borrowed[b].p,borrowed[b].n))return AF_INVALID;
            if(i->provider&&(!apart(writes[a].p,writes[a].n,i->provider,sizeof(*i->provider))||
                !apart(writes[a].p,writes[a].n,i->provider->context,1)))return AF_INVALID;
        }
        return AF_OK;
    }
    if(!i->parameters||!i->parameters->model)return AF_MANAGE_NOT_READY;
    const AfImportRequest *q=i->parameters;
    if(i->cube_capacity<24||i->cube_capacity>33u*33u*33u*3u||!q->seed||
       q->training_count<2||q->training_count>AF_JOINT_SAMPLES||
       q->validation_count<3||q->validation_count>AF_GRID_SAMPLES)return AF_INVALID;
    if(af_joint_model_valid(q->model,job->request.initial.base)!=AF_OK||
       q->model->base_mask!=(1u<<job->request.initial.base)||af_joint_valid(q->seed)!=AF_OK)return AF_INVALID;
    const Region writes[]={{t,sizeof(*t)},{i->source,i->source_capacity},
        {i->cube_storage,i->cube_capacity*sizeof(float)},{i->work,sizeof(*i->work)},{i->candidate,sizeof(*i->candidate)}};
    const Region borrowed[]={{r,sizeof(*r)},{r->catalog,sizeof(*r->catalog)},{r->labels,sizeof(*r->labels)},
        {m,sizeof(*m)},{r->buffers.a,r->buffers.capacity},{r->buffers.b,r->buffers.capacity},
        {r->buffers.next,r->buffers.capacity},{i,sizeof(*i)},{i->listing,sizeof(*i->listing)},
        {expected,sizeof(*expected)},{q,sizeof(*q)},{q->model,sizeof(*q->model)},
        {q->seed,sizeof(*q->seed)},{q->training,q->training_count*sizeof(*q->training)},
        {q->validation,q->validation_count*sizeof(*q->validation)}};
    for(unsigned a=0;a<sizeof(writes)/sizeof(*writes);++a){
        if(!writes[a].p||(uintptr_t)writes[a].p>UINTPTR_MAX-writes[a].n)return AF_INVALID;
        for(unsigned b=0;b<a;++b)if(!apart(writes[a].p,writes[a].n,writes[b].p,writes[b].n))return AF_INVALID;
        for(unsigned b=0;b<sizeof(borrowed)/sizeof(*borrowed);++b)
            if(!apart(writes[a].p,writes[a].n,borrowed[b].p,borrowed[b].n))return AF_INVALID;
        if(i->provider&&(!apart(writes[a].p,writes[a].n,i->provider,sizeof(*i->provider))||
           !apart(writes[a].p,writes[a].n,i->provider->context,1)))return AF_INVALID;
    }
    return AF_OK;
}
static int finish_job(AfRepository *r,AfApManage *m,const AfApManageJob *job,int status){
    AfApManageReceipt receipt={0};
    if(status==AF_GRID_CANCELLED&&!af_ap_manage_cancelled(m,job->ticket))status=AF_STALE;
    if(status==AF_STORE_UNCERTAIN&&m->phase!=AF_MANAGE_COMMITTING)status=AF_MANAGE_NOT_READY;
    receipt.ticket=job->ticket;receipt.result=status;receipt.durable=status==AF_OK;
    receipt.uncertain=status==AF_STORE_UNCERTAIN;
    receipt.generation=status==AF_OK?r->stores[job->request.target_slot-1].generation:0;
    int result=af_ap_manage_finish(m,r->catalog,&receipt);return result==AF_OK?status:result;
}
static int finished(AfRepositoryImportTask *t,int status){
    int result=finish_job(t->repository,t->manager,&t->job,status);
    t->phase=AF_REPOSITORY_IMPORT_FINISHED;t->last_result=result;return result;
}
int af_repository_import_start(AfRepositoryImportTask *t,AfRepository *r,AfApManage *m,
                               const AfRepositoryImport *input,const AfMediaSource *expected){
    AfApManageJob job;int status;
    if(!t||!r||!r->opened||!m||t->phase>AF_REPOSITORY_IMPORT_FINISHED||!owned(t,r,m))return AF_INVALID;
    if(af_repository_import_busy(t))return AF_BUSY;
    status=af_ap_manage_take(m,&job);if(status)return status;
    status=binding(t,r,m,input,expected,&job);if(status)return finish_job(r,m,&job,status);
    zero(t,sizeof(*t));t->repository=r;t->manager=m;t->job=job;t->input=*input;
    t->listing=*input->listing;t->expected=*expected;
    if(input->provider){t->provider=*input->provider;t->input.provider=&t->provider;}
    const char *name=t->listing.entries[job.request.media_index].name;size_t n=0;
    while(n<AF_MEDIA_NAME_BYTES&&name[n])++n;
    t->kind=af_media_kind(name,n);t->input.listing=&t->listing;
    t->phase=AF_REPOSITORY_IMPORT_MEDIA;
    if(t->kind==AF_MEDIA_PREPARED)return AF_JOINT_MORE;
    t->parameters=*input->parameters;
    t->model=*input->parameters->model;t->seed=*input->parameters->seed;
    copy(t->training,input->parameters->training,t->parameters.training_count*sizeof(*t->training));
    copy(t->validation,input->parameters->validation,t->parameters.validation_count*sizeof(*t->validation));
    t->parameters.model=&t->model;t->parameters.seed=&t->seed;
    t->parameters.training=t->training;t->parameters.validation=t->validation;
    t->parameters.source=t->input.source;t->parameters.source_bytes=t->expected.bytes;
    t->parameters.name=t->job.request.name;t->parameters.name_bytes=t->job.request.name_bytes;
    t->parameters.initial=t->job.request.initial;
    t->input.parameters=&t->parameters;t->input.listing=&t->listing;
    t->phase=AF_REPOSITORY_IMPORT_MEDIA;return AF_JOINT_MORE;
}
static int progress(void *opaque,uint32_t done,uint32_t total){
    AfRepositoryImportTask *t=opaque;if(!total||done>total)return 1;
    uint32_t value=(t->fitting?100000u:0u)+(uint32_t)((uint64_t)done*(t->fitting?900000u:100000u)/total);
    return af_ap_manage_progress(t->manager,t->job.ticket,value,1000000)!=AF_OK||
        af_ap_manage_cancelled(t->manager,t->job.ticket)!=0;
}
static int capacity(int directory,size_t payload){
    struct statvfs s;if(fstatvfs(directory,&s)||!s.f_frsize||(s.f_flag&ST_RDONLY))return AF_STORE_IO;
    uint64_t blocks=s.f_bavail,unit=s.f_frsize,need=AF_REPOSITORY_RESERVE+payload+AF_RECORD_HEADER;
    return blocks>UINT64_MAX/unit||blocks*unit>=need?AF_OK:AF_STORE_CAPACITY;
}
int af_repository_import_poll(AfRepositoryImportTask *t,uint32_t budget){
    if(!t||!budget||budget>64)return AF_INVALID;
    if(!af_repository_import_busy(t))return AF_STALE;
    AfRepository *r=t->repository;AfApManage *m=t->manager;int status;
    if(!r->opened||m->job.ticket!=t->job.ticket||m->phase!=AF_MANAGE_RUNNING){
        t->phase=AF_REPOSITORY_IMPORT_FINISHED;t->last_result=AF_STALE;return AF_STALE;}
    if(af_ap_manage_cancelled(m,t->job.ticket))return finished(t,AF_MANAGE_CANCEL);
    if(t->phase==AF_REPOSITORY_IMPORT_MEDIA){
        AfMediaSource actual;
        status=af_repository_import_read(&t->input,&t->listing,t->job.request.media_index,&actual,progress,t);
        if(status)return finished(t,status);
        if(actual.bytes!=t->expected.bytes||!equal(actual.sha256,t->expected.sha256,32))return finished(t,AF_STALE);
        if(t->kind==AF_MEDIA_PREPARED){
            AfDocument document;
            status=af_import_prepared(t->input.source,t->expected.bytes,&t->prepared_work,&t->prepared_asset,&document);
            if(status)return finished(t,status);
            t->phase=AF_REPOSITORY_IMPORT_COMMIT;return AF_JOINT_MORE;
        }
        t->fitting=1;
        status=af_import_start(&t->conversion,&t->parameters,t->input.cube_storage,t->input.cube_capacity,
                               t->input.work,t->input.candidate,progress,t);
        if(status!=AF_JOINT_MORE)return finished(t,status);
        t->phase=AF_REPOSITORY_IMPORT_FITTING;return AF_JOINT_MORE;
    }
    if(t->phase==AF_REPOSITORY_IMPORT_FITTING){
        status=af_import_step(&t->conversion,budget);
        if(status==AF_JOINT_MORE)return status;
        if(status)return finished(t,status);
        if(af_sha256(t->input.candidate,sizeof(*t->input.candidate),t->candidate_sha256))return finished(t,AF_INVALID);
        t->phase=AF_REPOSITORY_IMPORT_COMMIT;return AF_JOINT_MORE;
    }
    uint8_t digest[32];AfDocument document;
    if(af_sha256(t->input.source,t->expected.bytes,digest)||!equal(digest,t->expected.sha256,32))return finished(t,AF_STALE);
    if(t->kind==AF_MEDIA_PREPARED){
        status=af_import_prepared(t->input.source,t->expected.bytes,&t->prepared_work,&t->prepared_asset,&document);
    }else{
        if(af_sha256(t->input.candidate,sizeof(*t->input.candidate),digest)||!equal(digest,t->candidate_sha256,32))return finished(t,AF_STALE);
        status=af_import_document(t->input.candidate,&document);
    }
    if(status)return finished(t,status);
    uint32_t slot=t->job.request.target_slot;AfStore *store=&r->stores[slot-1];
    if(!(r->ready_mask&(1u<<(slot-1))))return finished(t,r->status[slot-1]);
    if(store->uncertain)return finished(t,AF_MANAGE_NOT_READY);
    if((status=capacity(r->posix.directory,store->max_payload))!=AF_OK)return finished(t,status);
    if((status=af_ap_manage_commit_begin(m,r->catalog,t->job.ticket))!=AF_OK)return finished(t,status);
    status=af_persist_replace(r->catalog,store,&r->io,&r->buffers,&document,(int)t->job.request.overwrite);
    if(!status){status=af_labels_from_store(r->labels,r->catalog,store,&r->buffers,0);
        if(status){store->uncertain=1;store->ready=0;status=AF_STORE_UNCERTAIN;}}
    return finished(t,status);
}
