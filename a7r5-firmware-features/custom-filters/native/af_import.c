#include "af_import.h"
#include "af_sha256.h"
#include <float.h>
typedef struct {const void *p;size_t n;} Span;
static int spans(const Span *s,unsigned count) {
    for (unsigned i=0;i<count;++i) {
        uintptr_t a=(uintptr_t)s[i].p;
        if (!a || a>UINTPTR_MAX-s[i].n) return 0;
        for (unsigned j=0;j<i;++j) {
            uintptr_t b=(uintptr_t)s[j].p;
            if (a<b+s[j].n && b<a+s[i].n) return 0;
        }
    }
    return 1;
}
static int finite(float v) {return v==v && v>=-FLT_MAX && v<=FLT_MAX;}
static int sample(const AfGridSample *s) {
    if (!finite(s->weight) || s->weight<=0 || s->weight>1000000 || (s->group&~3u)) return 0;
    for (unsigned j=0;j<3;++j) if (!finite(s->rgb[j]) || s->rgb[j]<0 || s->rgb[j]>1) return 0;
    return 1;
}
static int same_color(const AfGridSample *a,const AfGridSample *b) {
    return a->rgb[0]==b->rgb[0] && a->rgb[1]==b->rgb[1] && a->rgb[2]==b->rgb[2];
}
static int samples_valid(const AfImportRequest *q) {
    unsigned groups=0;
    for (size_t i=0;i<q->training_count;++i) if (!sample(&q->training[i])) return 0;
    for (size_t i=0;i<q->validation_count;++i) {
        if (!sample(&q->validation[i])) return 0;
        groups|=q->validation[i].group;
        for (size_t j=0;j<q->training_count;++j) if (same_color(&q->validation[i],&q->training[j])) return 0;
        for (size_t j=0;j<i;++j) if (same_color(&q->validation[i],&q->validation[j])) return 0;
    }
    return groups==3;
}
static int report_value(float value,uint32_t *out) {
    if (!finite(value) || value<0 || value>1000000) return AF_INVALID;
    *out=(uint32_t)((double)value*1000+.5);return AF_OK;
}
int af_import_prepared(const void *raw,size_t bytes,AfJointAssetDecodeWork *work,
                       AfJointAsset *asset,AfDocument *output){
    AfDocument d;int status;
    const Span s[]={{raw,bytes},{work,sizeof(*work)},{asset,sizeof(*asset)},{output,sizeof(*output)}};
    if(bytes<AF_DOCUMENT_HEADER||bytes>AF_PREPARED_FILE_MAX||!spans(s,4))return AF_INVALID;
    status=af_document_decode(raw,bytes,AF_JOINT_ASSET_SCHEMA,&d);if(status)return status;
    if(d.present!=1)return AF_INVALID;
    if(d.initial.kind){
        if((d.converter!=2&&d.converter!=3)||!af_joint_asset_size_valid(d.image_bytes))return AF_JOINT_ASSET_UNSUPPORTED;
        status=af_joint_asset_decode_work(d.image,d.image_bytes,work,asset);if(status)return status;
        if(asset->native_mode!=1||asset->base!=d.initial.base||d.converter!=af_joint_asset_converter(asset))return AF_JOINT_ASSET_UNSUPPORTED;
#ifndef AF_JOINT_ASSET_LEGACY_ONLY406
        status=af_joint_matrix_native406_representable(asset->base,asset->matrix_mode,
            asset->recipe.matrix,asset->sector_matrix);if(status)return status;
#endif
        for(unsigned i=0;i<32;++i)
            if(asset->model_sha256[i]!=d.report.model_sha256[i])return AF_INVALID;
    }
    *output=d;return AF_OK;
}
int af_import_asset(const AfDocument *d,AfJointAsset *output) {
    AfJointAsset asset;size_t bytes;
    uint8_t checked[AF_DOCUMENT_HEADER+AF_DOCUMENT_NAME_MAX+AF_JOINT_ASSET_MAX_BYTES];
    if (!d || !output || d->present!=1 || d->initial.kind!=1 || !af_joint_asset_size_valid(d->image_bytes) ||
        !d->name_bytes || d->name_bytes>AF_DOCUMENT_NAME_MAX) return AF_INVALID;
    if (d->schema!=AF_JOINT_ASSET_SCHEMA || (d->converter<1||d->converter>3)) return AF_JOINT_ASSET_UNSUPPORTED;
    {
        const Span a[]={{d,sizeof(*d)},{output,sizeof(*output)}};
        const Span b[]={{d->image,d->image_bytes},{output,sizeof(*output)}};
        const Span c[]={{d->name,d->name_bytes},{output,sizeof(*output)}};
        if (!spans(a,2) || !spans(b,2) || !spans(c,2)) return AF_INVALID;
    }
    if (af_document_encode(d,AF_JOINT_ASSET_SCHEMA,checked,sizeof(checked),&bytes)!=AF_DOCUMENT_OK ||
        af_joint_asset_decode(d->image,d->image_bytes,&asset)!=AF_OK || asset.base!=d->initial.base ||
        d->converter!=af_joint_asset_converter(&asset)) return AF_INVALID;
    for (unsigned i=0;i<32;++i) if (asset.model_sha256[i]!=d->report.model_sha256[i]) return AF_INVALID;
    *output=asset;return AF_OK;
}
int af_import_document(const AfImportCandidate *candidate,AfDocument *output) {
    AfDocument d={0};AfJointAsset asset;size_t bytes;
    uint8_t checked[AF_DOCUMENT_HEADER+AF_DOCUMENT_NAME_MAX+AF_JOINT_ASSET_BYTES];
    if (!candidate || !output || !candidate->name_bytes || candidate->name_bytes>AF_DOCUMENT_NAME_MAX) return AF_INVALID;
    {
        const Span s[]={{candidate,sizeof(*candidate)},{output,sizeof(*output)}};
        if (!spans(s,2)) return AF_INVALID;
    }
    if (candidate->initial.kind!=1 || candidate->fit.research_only!=1 || candidate->fit.attempted_components!=15 ||
        candidate->fit.evaluations<9 || candidate->fit.evaluations>AF_JOINT_EVALUATIONS ||
        !finite(candidate->fit.initial_mse) || candidate->fit.initial_mse<0 ||
        !finite(candidate->fit.final_mse) || candidate->fit.final_mse<0 ||
        candidate->fit.final_mse>candidate->fit.initial_mse ||
        !candidate->validation.gray_samples || !candidate->validation.skin_samples ||
        candidate->report.samples!=candidate->validation.samples || candidate->report.clipped!=candidate->validation.clipped ||
        af_joint_asset_decode(candidate->image,sizeof(candidate->image),&asset)!=AF_OK || asset.base!=candidate->initial.base)
        return AF_INVALID;
    for (unsigned i=0;i<32;++i) if (asset.model_sha256[i]!=candidate->report.model_sha256[i]) return AF_INVALID;
    for (unsigned i=0;i<5;++i) {
        uint32_t value;
        if (report_value(candidate->validation.delta_e76[i],&value)!=AF_OK || candidate->report.delta_e[i]!=value)
            return AF_INVALID;
    }
    d.present=1;d.initial=candidate->initial;d.saved=d.initial;
    d.schema=AF_JOINT_ASSET_SCHEMA;d.converter=asset.native_mode?2:1;
    d.name=candidate->name;d.name_bytes=candidate->name_bytes;
    d.image=candidate->image;d.image_bytes=sizeof(candidate->image);d.report=candidate->report;
    if (af_document_encode(&d,AF_JOINT_ASSET_SCHEMA,checked,sizeof(checked),&bytes)!=AF_DOCUMENT_OK) return AF_INVALID;
    *output=d;return AF_OK;
}
size_t af_import_state_bytes(void) {return sizeof(AfImportState);}
static int notify(AfImportState *s,uint32_t done) {
    return s->progress?s->progress(s->context,done,s->total):0;
}
static int search_progress(void *opaque,uint32_t done,uint32_t total) {
    AfImportState *s=opaque;(void)total;return notify(s,1+done);
}
static int failed(AfImportState *s,int status) {s->phase=4;return status;}
int af_import_start(AfImportState *state,const AfImportRequest *q,float *storage,size_t capacity,
                    AfImportWork *w,AfImportCandidate *output,AfGridProgress callback,void *context) {
    AfDocument check={0};int status;size_t bytes;
    uint8_t checked[AF_DOCUMENT_HEADER+AF_DOCUMENT_NAME_MAX];
    if(!state)return AF_INVALID;
    if(state->phase==1 || state->phase==2 || state->phase==5)return AF_BUSY;
    if(state->phase>5)return AF_INVALID;
    if (!q || af_validate(&q->initial)!=AF_OK || q->initial.kind ||
        af_joint_model_valid(q->model,q->initial.base)!=AF_OK || q->model->base_mask!=(1u<<q->initial.base) ||
        af_joint_valid(q->seed)!=AF_OK || !q->source_bytes || q->source_bytes>AF_IMPORT_SOURCE_MAX ||
        !q->name_bytes || q->name_bytes>AF_DOCUMENT_NAME_MAX ||
        capacity<24 || capacity>33u*33u*33u*3u || q->training_count<2 || q->training_count>AF_JOINT_SAMPLES ||
        q->validation_count<3 || q->validation_count>AF_GRID_SAMPLES ||
        q->options.evaluations<9 || q->options.evaluations>AF_JOINT_EVALUATIONS) return AF_INVALID;
    {
        const Span s[]={{q,sizeof(*q)},{q->model,sizeof(*q->model)},{q->seed,sizeof(*q->seed)},
            {q->source,q->source_bytes},{q->name,q->name_bytes},{q->training,q->training_count*sizeof(*q->training)},
            {q->validation,q->validation_count*sizeof(*q->validation)},{storage,capacity*sizeof(*storage)},
            {w,sizeof(*w)},{output,sizeof(*output)},{state,sizeof(*state)}};
        if (!spans(s,11)) return AF_INVALID;
    }
    if (!samples_valid(q)) return AF_INVALID;
    check.present=1;check.initial=q->initial;check.saved=q->initial;check.name=q->name;check.name_bytes=q->name_bytes;
    if (af_document_encode(&check,0,checked,sizeof(checked),&bytes)!=AF_DOCUMENT_OK) return AF_INVALID;
    AfImportState next={0};next.request=*q;next.model=*q->model;next.seed=*q->seed;
    next.work=w;next.output=output;next.progress=callback;next.context=context;next.phase=5;
    next.total=q->options.evaluations+(uint32_t)q->validation_count+2;
    for(size_t i=0;i<q->name_bytes;++i)next.name[i]=q->name[i];
    *state=next;state->request.model=&state->model;state->request.seed=&state->seed;state->request.name=state->name;
    if(notify(state,0))return failed(state,AF_GRID_CANCELLED);
    if(af_sha256(q->source,q->source_bytes,state->source_sha256))return failed(state,AF_INVALID);
    status=af_cube_parse(q->source,q->source_bytes,&state->cube,storage,capacity,(AfCubeLimits){33,AF_IMPORT_SOURCE_MAX});
    if(status!=AF_CUBE_OK)return failed(state,AF_INVALID);
    if(notify(state,1))return failed(state,AF_GRID_CANCELLED);
    {
        AfImportCandidate empty={0};w->candidate=empty;
    }
    q=&state->request;
#ifdef AF_JOINT_BASIS406
    /* 机内构建使用受约束共享基函数；边界仅限制搜索，不宣称相机标定。
     * 仍由q->model预测完整量化组合，完整配方与保存ABI保持。 */
    const AfJointBasisOptions basis={q->options.evaluations,q->options.tone_step,
        q->options.matrix_step,q->options.cc1_step,q->options.grid_step,{32,64,64},16,16};
    status=af_joint_basis_start(&state->search,q->model,q->initial.base,&state->cube,q->training,
        q->training_count,q->seed,&basis,&w->fit,&w->recipe,&w->candidate.fit,search_progress,state);
#else
    status=af_joint_fit_start(&state->search,q->model,q->initial.base,&state->cube,q->training,
        q->training_count,q->seed,&q->options,&w->fit,&w->recipe,&w->candidate.fit,search_progress,state);
#endif
    if(status!=AF_JOINT_MORE)return failed(state,status);
    state->phase=1;return AF_JOINT_MORE;
}
static int complete(AfImportState *s) {
    const AfImportRequest *q=&s->request;AfImportWork *w=s->work;
    AfDocument check;AfJointAsset asset={0};size_t bytes;uint8_t digest[32];
    if(af_sha256(q->source,q->source_bytes,digest))return AF_INVALID;
    for(unsigned i=0;i<32;++i)if(digest[i]!=s->source_sha256[i])return AF_STALE;
    asset.base=q->initial.base;asset.recipe=w->recipe;
#ifdef AF_JOINT_BASIS406
    asset.native_mode=1;
    for(unsigned i=0;i<3;++i)asset.native_tone[i]=s->search.controls[i];
    for(unsigned i=0;i<129;++i)asset.native_seed[i]=s->search.seed.gamma[i];
#endif
    for(unsigned i=0;i<32;++i)asset.model_sha256[i]=q->model->model_sha256[i];
    int status=af_joint_asset_encode(&asset,w->candidate.image,sizeof(w->candidate.image),&bytes);
    if(status!=AF_OK)return status;
    w->candidate.initial=q->initial;w->candidate.initial.kind=1;
    for(unsigned i=0;i<32;++i)w->candidate.initial.lut_sha256[i]=s->source_sha256[i];
    (void)af_sha256(w->candidate.image,bytes,w->candidate.initial.payload_sha256);
    w->candidate.name_bytes=(uint32_t)q->name_bytes;
    for (unsigned i=0;i<q->name_bytes;++i) w->candidate.name[i]=q->name[i];
    w->candidate.report.samples=w->candidate.validation.samples;
    w->candidate.report.clipped=w->candidate.validation.clipped;w->candidate.report.scope=1;
    for (unsigned i=0;i<32;++i) w->candidate.report.model_sha256[i]=q->model->model_sha256[i];
    for (unsigned i=0;i<5;++i)
        if (report_value(w->candidate.validation.delta_e76[i],&w->candidate.report.delta_e[i])!=AF_OK) return AF_INVALID;
    if(af_import_document(&w->candidate,&check)!=AF_OK)return AF_INVALID;
    if(notify(s,s->total))return AF_GRID_CANCELLED;
    *s->output=w->candidate;s->phase=3;return AF_OK;
}
int af_import_step(AfImportState *s,uint32_t budget) {
    if(!s || !budget || budget>64)return AF_INVALID;
    if(s->phase!=1 && s->phase!=2)return AF_STALE;
    if(s->phase==1) {
#ifdef AF_JOINT_BASIS406
        int status=af_joint_basis_step(&s->search,budget);
#else
        int status=af_joint_fit_step(&s->search,budget);
#endif
        if(status==AF_JOINT_MORE)return status;
        if(status!=AF_OK)return failed(s,status);
        if(s->work->candidate.fit.attempted_components!=15)return failed(s,AF_INVALID);
        s->phase=2;return AF_JOINT_MORE;
    }
    const AfImportRequest *q=&s->request;AfImportWork *w=s->work;
    if(notify(s,1+q->options.evaluations+s->validated))return failed(s,AF_GRID_CANCELLED);
    for(uint32_t batch=0;batch<budget && s->validated<q->validation_count;++batch) {
        const AfGridSample *sample=&q->validation[s->validated];
        AfGridColor *color=&w->report.colors[s->validated];
        if(af_cube_eval(&s->cube,sample->rgb,color->target)!=AF_CUBE_OK)return failed(s,AF_INVALID);
        if(q->model->predict(q->model->context,&w->recipe,sample->rgb,color->predicted)!=AF_OK)
            return failed(s,AF_JOINT_MODEL_ERROR);
        for(unsigned j=0;j<3;++j)if(!finite(color->predicted[j]))return failed(s,AF_JOINT_MODEL_ERROR);
        color->group=sample->group;++s->validated;
        if(notify(s,1+q->options.evaluations+s->validated))return failed(s,AF_GRID_CANCELLED);
    }
    if(s->validated<q->validation_count)return AF_JOINT_MORE;
    if(af_grid_color_report(w->report.colors,q->validation_count,w->report.errors,&w->candidate.validation)!=AF_OK)
        return failed(s,AF_INVALID);
    int status=complete(s);return status==AF_OK?status:failed(s,status);
}
int af_import_cube(const AfImportRequest *q,float *storage,size_t capacity,AfImportWork *w,
                    AfImportCandidate *output,AfGridProgress callback,void *context) {
    AfImportState state={0};
    int status=af_import_start(&state,q,storage,capacity,w,output,callback,context);
    while(status==AF_JOINT_MORE)status=af_import_step(&state,64);
    return status;
}
