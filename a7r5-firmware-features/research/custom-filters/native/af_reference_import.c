/* 固定参考模型只在导入时使用；所有大对象驻留，不进入消息/拍摄栈。 */
#include "af_reference_import.h"
#include "af_reference_assets.h"
#include "af_reference_samples.h"
#include "af_repository_service.h"
#ifdef AF_TARGET_GLIBC225
extern void *calloc(size_t,size_t);
extern void free(void *);
#else
#include <stdlib.h>
#endif
extern const uint8_t af_reference_context4_blob[],af_reference_context4_blob_end[];
extern const AfGridModel af_reference_paired_v2;
#define SAMPLE_SIDE 9u
#define SAMPLE_FLOATS (6u*(SAMPLE_SIDE*SAMPLE_SIDE*SAMPLE_SIDE+130u))
typedef struct {
    AfReferenceAssets assets;
    AfEditJointCache baseline,candidate;
    AfEditJointWork construction;
    AfJointRecipe seed;
    AfReferenceMap input_map,output_map;
    AfReferenceSamplesReport samples;
    float pairs[SAMPLE_FLOATS],output_values[24];
    AfGridSample training[AF_JOINT_SAMPLES],validation[AF_GRID_SAMPLES];
    AfJointModel model;
    AfImportRequest parameters;
    AfRepositoryImport binding;
    AfImportWork conversion;
    AfImportCandidate converted;
    float cube[33u*33u*33u*3u];
    char source[AF_IMPORT_SOURCE_MAX];
    void *joint_state,*joint_work,*sample_state,*sample_work,*service;
} ReferenceImport;
static ReferenceImport *resident;
static unsigned constructing;
static void copy32(uint8_t *a,const uint8_t *b){for(unsigned i=0;i<32;++i)a[i]=b[i];}
static void discard(ReferenceImport *p){
    if(!p)return;
    free(p->joint_state);free(p->joint_work);free(p->sample_state);free(p->sample_work);free(p);
}
static int construct(ReferenceImport *p){
    size_t bytes=(size_t)((uintptr_t)af_reference_context4_blob_end-(uintptr_t)af_reference_context4_blob);
    int status=af_reference_assets_bind(af_reference_context4_blob,bytes,&p->assets);
    if(status)return status;
    if((status=af_reference_assets_seed(&p->assets,&p->seed))!=AF_OK)return status;
    status=af_edit_joint_prepare(&p->assets.joint,&p->seed,&p->construction,&p->baseline,0,0);
    if(status)return status;
    p->sample_state=calloc(1,af_reference_samples_state_bytes());
    p->sample_work=calloc(1,af_reference_samples_work_bytes());
    p->joint_state=calloc(1,af_reference_joint_state_bytes());
    p->joint_work=calloc(1,af_reference_joint_work_bytes());
    if(!p->sample_state||!p->sample_work||!p->joint_state||!p->joint_work)return AF_STORE_CAPACITY;
    /* 这是uint16任务内的显式采样子范围，不声明传感器或完整输入白位。 */
    AfReferenceSamplesConfig sampling={1,0,SAMPLE_SIDE,{16383,16383,16383},&p->baseline};
    AfReferenceSamplesBuffers buffers={p->pairs,SAMPLE_FLOATS,p->output_values,24,
        p->training,AF_JOINT_SAMPLES,p->validation,AF_GRID_SAMPLES,
        &p->input_map,&p->output_map,&p->samples};
    status=af_reference_samples_start(p->sample_state,&sampling,&buffers,p->sample_work,0,0);
    if(status!=AF_JOINT_MORE)return status;
    /* 总前向数固定为side^3+130；循环上限防止异常状态占住启动。 */
    for(unsigned i=0;i<1024 && status==AF_JOINT_MORE;++i)
        status=af_reference_samples_step(p->sample_state,64);
    if(status!=AF_OK)return status==AF_JOINT_MORE?AF_EXHAUSTED:status;
    AfReferenceJointConfig config={.schema=1,
        .flags=AF_REFERENCE_RESEARCH|AF_REFERENCE_ZERO_ANCHOR|AF_REFERENCE_POST_COLOR_GRID|AF_REFERENCE_CROSS_BASE_GRID,
        .base=0,.grid_base=1,.edit=&p->assets.joint,.seed=&p->seed,.baseline=&p->baseline,
        .input_map=&p->input_map,.output_map=&p->output_map,.grid=&af_reference_paired_v2};
    config.reference_params[6]=3;
    copy32(config.target_cp_sha256,af_joint_cp_sha256);
    copy32(config.edit_source_sha256,p->baseline.source_sha256);
    copy32(config.grid_source_sha256,af_reference_paired_v2.sha256);
    status=af_reference_joint_init(p->joint_state,&config,p->joint_work,&p->candidate,0,0);
    if(status)return status;
    p->parameters.initial.base=0;p->parameters.initial.params[6]=3;
    status=af_reference_joint_model(p->joint_state,&p->parameters.initial,&p->model);
    if(status)return status;
    p->parameters.model=&p->model;p->parameters.seed=&p->seed;
    p->parameters.training=p->training;p->parameters.training_count=p->samples.training;
    p->parameters.validation=p->validation;p->parameters.validation_count=p->samples.validation;
    p->parameters.options=(AfJointOptions){257,256,16,4,4,4};
    p->binding.directory=-1;p->binding.source=p->source;p->binding.source_capacity=sizeof(p->source);
    p->binding.parameters=&p->parameters;p->binding.cube_storage=p->cube;
    p->binding.cube_capacity=sizeof(p->cube)/sizeof(p->cube[0]);
    p->binding.work=&p->conversion;p->binding.candidate=&p->converted;
    return AF_OK;
}
int af_reference_import_bind(void *service){
    if(!service)return AF_INVALID;
    if(constructing)return AF_BUSY;
    if(resident&&resident->service&&resident->service!=service)return AF_BUSY;
    constructing=1;
    if(!resident){
        ReferenceImport *p=calloc(1,sizeof(*p));
        if(!p){constructing=0;return AF_STORE_CAPACITY;}
        int status=construct(p);
        if(status){discard(p);constructing=0;return status;}
        resident=p;
    }
    int status=af_repository_service_bind_import(service,&resident->binding);
    if(status==AF_OK)resident->service=service;
    constructing=0;return status;
}
void af_reference_import_closed(void *service){
    if(resident&&resident->service==service)resident->service=0;
}
int af_reference_import_info(void *service,AfReferenceJointInfo *output){
    if(!service||!resident||resident->service!=service)return AF_EMPTY;
    return af_reference_joint_info(resident->joint_state,output);
}
