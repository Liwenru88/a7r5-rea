/* 仅宿主C预测桥；复用固件数值源码，不执行ARM或模拟硬件。 */
#include "af_reference_assets.h"
#include "af_reference_joint.h"
#include "af_reference_samples.h"
#include "af_joint_basis.h"
#include "af_import.h"
#include <stdlib.h>
#include <string.h>

extern const AfGridModel af_reference_paired_v2;
#define SIDE 9u
#define PAIRS (6u*(SIDE*SIDE*SIDE+130u))
typedef struct {
    AfReferenceAssets assets;
    AfEditJointCache baseline,candidate;
    AfEditJointWork construction;
    AfJointRecipe seed,trial,basis_recipe;
    AfReferenceMap input,output;
    AfReferenceSamplesReport samples;
    AfReferenceJointInfo info;
    AfJointModel model,legacy_model;
    int16_t sector_matrix[288];
    uint32_t matrix_mode;
    float pairs[PAIRS],output_values[24],cube_values[33*33*33*3];
    AfCube cube;
    AfGridSample training[512],validation[4096],sets[3][4096];
    float targets[3][4096][3];
    uint32_t count[3];uint64_t cells[3];
    AfJointBasisState basis;
    AfJointWork basis_work;
    AfJointFit basis_fit;
    AfJointReportWork report_work;
    void *raw,*joint_state,*joint_work,*sample_state,*sample_work;
    uint32_t cube_ready;
} DesktopFit;
static int desktop_predict(void *opaque,const AfJointRecipe *r,const float *input,float *output){
    DesktopFit *p=opaque;
    return p->matrix_mode?af_reference_joint_predict_sector(p->joint_state,r,p->sector_matrix,input,output):
        af_reference_joint_predict(p->joint_state,r,input,output);
}
int desktop_mode(DesktopFit *p,unsigned mode){
    if(!p||mode>1)return AF_INVALID;
    AfReferenceJointInfo info;int status=mode?af_reference_joint_info_sector(p->joint_state,&info):
        af_reference_joint_info(p->joint_state,&info);
    if(status)return status;
    p->matrix_mode=mode;p->info=info;p->model=p->legacy_model;
    p->model.predict=desktop_predict;p->model.context=p;memcpy(p->model.model_sha256,info.model_sha256,32);
    return AF_OK;
}

static unsigned cell(const float *rgb){
    unsigned key=0;
    for(unsigned i=0;i<3;++i){unsigned n=(unsigned)(rgb[i]*4);key=key*4+(n<4?n:3);}
    return key;
}
void desktop_close(DesktopFit *p){
    if(!p)return;
    free(p->raw);free(p->joint_state);free(p->joint_work);free(p->sample_state);free(p->sample_work);free(p);
}
DesktopFit *desktop_open(const void *raw,size_t bytes,int *error){
    int status=AF_INVALID;DesktopFit *p=0;
    if(!error)return 0;*error=status;
    if(!raw||bytes!=AF_REFERENCE_ASSETS_BYTES)return 0;
    p=calloc(1,sizeof(*p));if(!p)return 0;
    p->raw=malloc(bytes);if(!p->raw)goto fail;memcpy(p->raw,raw,bytes);
    if((status=af_reference_assets_bind(p->raw,bytes,&p->assets)))goto fail;
    if((status=af_reference_assets_seed(&p->assets,&p->seed)))goto fail;
    if((status=af_edit_joint_prepare(&p->assets.joint,&p->seed,&p->construction,&p->baseline,0,0)))goto fail;
    p->joint_state=calloc(1,af_reference_joint_state_bytes());p->joint_work=calloc(1,af_reference_joint_work_bytes());
    p->sample_state=calloc(1,af_reference_samples_state_bytes());p->sample_work=calloc(1,af_reference_samples_work_bytes());
    if(!p->joint_state||!p->joint_work||!p->sample_state||!p->sample_work){status=AF_EXHAUSTED;goto fail;}
    AfReferenceSamplesConfig sampling={1,0,SIDE,{16383,16383,16383},&p->baseline};
    AfReferenceSamplesBuffers buffers={p->pairs,PAIRS,p->output_values,24,p->training,512,p->validation,4096,
        &p->input,&p->output,&p->samples};
    status=af_reference_samples_start(p->sample_state,&sampling,&buffers,p->sample_work,0,0);
    for(unsigned i=0;i<1024&&status==AF_JOINT_MORE;++i)status=af_reference_samples_step(p->sample_state,64);
    if(status)goto fail;
    AfReferenceJointConfig config={.schema=1,.flags=AF_REFERENCE_RESEARCH|AF_REFERENCE_ZERO_ANCHOR|
        AF_REFERENCE_POST_COLOR_GRID|AF_REFERENCE_CROSS_BASE_GRID,.base=0,.grid_base=1,
        .edit=&p->assets.joint,.seed=&p->seed,.baseline=&p->baseline,.input_map=&p->input,
        .output_map=&p->output,.grid=&af_reference_paired_v2};
    config.reference_params[6]=3;
    memcpy(config.target_cp_sha256,af_joint_cp_sha256,32);memcpy(config.edit_source_sha256,p->baseline.source_sha256,32);
    memcpy(config.grid_source_sha256,af_reference_paired_v2.sha256,32);
    if((status=af_reference_joint_init(p->joint_state,&config,p->joint_work,&p->candidate,0,0)))goto fail;
    AfPreset preset={0};preset.params[6]=3;
    if((status=af_reference_joint_model(p->joint_state,&preset,&p->model)))goto fail;
    if((status=af_reference_joint_info(p->joint_state,&p->info)))goto fail;
    p->legacy_model=p->model;if((status=desktop_mode(p,0)))goto fail;
    /* 保留两类代理所在区域作最终测试，其余验证区域轮流留作选优/测试。 */
    uint64_t mandatory=((uint64_t)1<<cell(p->validation[0].rgb))|((uint64_t)1<<cell(p->validation[1].rgb));
    unsigned rank=0;
    for(unsigned key=0;key<64;++key)if((p->samples.validation_cells&((uint64_t)1<<key))&&!(mandatory&((uint64_t)1<<key))){
        if(!(rank++&1))p->cells[1]|=(uint64_t)1<<key;
    }
    p->cells[0]=p->samples.training_cells;p->cells[2]=p->samples.validation_cells&~p->cells[1];
    for(unsigned i=0;i<p->samples.training;++i)p->sets[0][p->count[0]++]=p->training[i];
    for(unsigned i=0;i<p->samples.validation;++i){
        unsigned set=(p->cells[1]&((uint64_t)1<<cell(p->validation[i].rgb)))?1:2;
        p->sets[set][p->count[set]++]=p->validation[i];
    }
    if(!p->count[0]||!p->count[1]||!p->count[2]){status=AF_REFERENCE_SAMPLES_INSUFFICIENT;goto fail;}
    *error=AF_OK;return p;
fail:
    *error=status?status:AF_EXHAUSTED;desktop_close(p);return 0;
}
uint32_t desktop_count(DesktopFit *p,unsigned set){return p&&set<3?p->count[set]:0;}
uint64_t desktop_cells(DesktopFit *p,unsigned set){return p&&set<3?p->cells[set]:0;}
int desktop_digest(DesktopFit *p,unsigned kind,uint8_t *out){
    if(!p||!out||kind>2)return AF_INVALID;
    memcpy(out,kind==0?p->info.model_sha256:kind==1?p->info.target_cp_sha256:af_reference_assets_sha256,32);return 0;
}
int desktop_load_cube(DesktopFit *p,const char *raw,size_t bytes){
    if(!p)return AF_INVALID;p->cube_ready=0;
    int status=af_cube_parse(raw,bytes,&p->cube,p->cube_values,33*33*33*3,(AfCubeLimits){33,4*1024*1024});
    if(status)return status;
    for(unsigned set=0;set<3;++set)for(unsigned i=0;i<p->count[set];++i)
        if(af_cube_eval(&p->cube,p->sets[set][i].rgb,p->targets[set][i]))return AF_INVALID;
    p->cube_ready=1;return 0;
}
static int recipe(DesktopFit *p,const int16_t *v,const int8_t *grid){
    if(!p||!v||!grid||!p->cube_ready)return AF_INVALID;
    p->trial=p->seed;
    int result=af_joint_gamma(p->seed.gamma,v,p->trial.gamma);if(result)return AF_JOINT_SKIP;
    if(p->matrix_mode){
        for(unsigned i=0;i<18;++i)p->trial.matrix[i]=0;
        for(unsigned i=0;i<288;++i){if(v[3+i]<-1024||v[3+i]>1024)return AF_JOINT_SKIP;p->sector_matrix[i]=v[3+i];}
    }else memcpy(p->trial.matrix,v+3,36);
    memcpy(p->trial.cc1,v+3+(p->matrix_mode?288:18),48);memcpy(p->trial.grid,grid,1215);
    return af_joint_valid(&p->trial)?AF_JOINT_SKIP:0;
}
static unsigned code(float v){return (unsigned)((double)(v<0?0:v>1?1:v)*255+.5);}
static int trial_loss(DesktopFit *p,unsigned set,double *out){
    int result;
    double quantized=0,continuous=0;
    for(unsigned i=0;i<p->count[set];++i){
        float rgb[3];result=p->model.predict(p->model.context,&p->trial,p->sets[set][i].rgb,rgb);
        if(result)return result;
        for(unsigned c=0;c<3;++c){
            float target=p->targets[set][i][c];
            double delta=(double)code(rgb[c])-code(target);quantized+=delta*delta;
            double d=(double)rgb[c]-(target<0?0:target>1?1:target);continuous+=d*d;
        }
    }
    out[0]=quantized/(3*p->count[set]*65025.0);out[1]=continuous/(3*p->count[set]);return 0;
}
int desktop_loss(DesktopFit *p,const int16_t *v,const int8_t *grid,unsigned set,double *out){
    if(!p||set>2||!out)return AF_INVALID;
    int status=recipe(p,v,grid);return status?status:trial_loss(p,set,out);
}
int desktop_baseline(DesktopFit *p,int16_t *v,int8_t *grid,AfGridProgress callback){
    if(!p||!v||!grid||!p->cube_ready)return AF_INVALID;
    memset(&p->basis,0,sizeof(p->basis));
    AfJointBasisOptions options={257,16,4,4,4,{32,64,64},16,16};
    int status=af_joint_basis_start(&p->basis,&p->legacy_model,0,&p->cube,p->sets[0],p->count[0],&p->seed,
        &options,&p->basis_work,&p->basis_recipe,&p->basis_fit,callback,0);
    while(status==AF_JOINT_MORE)status=af_joint_basis_step(&p->basis,64);
    if(status)return status;
    memcpy(v,p->basis.controls,6);
    if(p->matrix_mode){for(unsigned e=0;e<3;++e)for(unsigned s=0;s<16;++s)for(unsigned j=0;j<6;++j)
        v[3+(e*16+s)*6+j]=p->basis_recipe.matrix[e*6+j];}
    else memcpy(v+3,p->basis_recipe.matrix,36);
    memcpy(v+3+(p->matrix_mode?288:18),p->basis_recipe.cc1,48);memcpy(grid,p->basis_recipe.grid,1215);return 0;
}
static int trial_report(DesktopFit *p,unsigned set,double *out){
    AfGridReport report;
    int status=af_joint_report(&p->model,0,&p->cube,&p->trial,p->sets[set],p->count[set],&p->report_work,&report,0,0);
    if(status)return status;
    out[0]=report.samples;out[1]=report.clipped;
    for(unsigned i=0;i<5;++i)out[2+i]=report.delta_e76[i];out[7]=report.rgb_rmse;return 0;
}
int desktop_report(DesktopFit *p,const int16_t *v,const int8_t *grid,unsigned set,double *out){
    if(!p||set>2||!out)return AF_INVALID;
    int status=recipe(p,v,grid);return status?status:trial_report(p,set,out);
}
/* 完整Gamma仅用于宿主对照；真实源摘要、18bit、单调及61440表示政策不放宽。 */
static int gamma_recipe(DesktopFit *p,const int16_t *v,const int8_t *grid,const uint32_t *curve){
    if(!curve)return AF_INVALID;
    int status=recipe(p,v,grid);if(status)return status;
    AfEditCpGamma converted;
    status=af_edit_cp_gamma(p->assets.joint.cp_gamma_record,576,curve,129,&converted,0,0);
    if(status)return status;
    memcpy(p->trial.gamma,curve,516);return af_joint_valid(&p->trial);
}
int desktop_gamma_source(DesktopFit *p,void *record){
    if(!p||!record)return AF_INVALID;
    memcpy(record,p->assets.joint.cp_gamma_record,576);return AF_OK;
}
int desktop_gamma_seed(DesktopFit *p,const int16_t *v,const int8_t *grid,uint32_t *curve,uint32_t *axis){
    if(!curve||!axis)return AF_INVALID;
    uintptr_t a=(uintptr_t)curve,b=(uintptr_t)axis;
    if(a>UINTPTR_MAX-516||b>UINTPTR_MAX-516||!(a+516<=b||b+516<=a))return AF_INVALID;
    int status=recipe(p,v,grid);if(status)return status;
    uint32_t native_axis[129];AfEditCpGamma converted;
    status=af_edit_cp_gamma(p->assets.joint.cp_gamma_record,576,p->trial.gamma,129,&converted,0,0);
    if(!status)status=af_gamma406_axis(p->assets.joint.cp_gamma_record,native_axis);
    if(status)return status;
    memcpy(curve,p->trial.gamma,516);memcpy(axis,native_axis,516);return AF_OK;
}
int desktop_gamma_loss(DesktopFit *p,const int16_t *v,const int8_t *grid,const uint32_t *curve,unsigned set,double *out){
    if(!p||set>1||!out)return AF_INVALID;
    int status=gamma_recipe(p,v,grid,curve);return status?status:trial_loss(p,set,out);
}
int desktop_gamma_report(DesktopFit *p,const int16_t *v,const int8_t *grid,const uint32_t *curve,unsigned set,double *out){
    if(!p||set!=2||!out)return AF_INVALID;
    int status=gamma_recipe(p,v,grid,curve);return status?status:trial_report(p,set,out);
}
int desktop_grid_order(DesktopFit *p,const int16_t *v,uint32_t *order){
    int8_t zero[1215]={0};double priority[1215]={0};
    if(!order)return AF_INVALID;int status=recipe(p,v,zero);if(status)return status;
    for(unsigned i=0;i<p->count[0];++i){
        float rgb[3];status=p->model.predict(p->model.context,&p->trial,p->sets[0][i].rgb,rgb);if(status)return status;
        unsigned low[3];float fraction[3];
        for(unsigned c=0;c<3;++c){
            float at=af_reference_paired_v2.coordinates[c*4+3];
            for(unsigned j=0;j<3;++j)at+=rgb[j]*af_reference_paired_v2.coordinates[c*4+j];
            unsigned maximum=c?8:4;at=at*maximum+(c?4:0);at=at<0?0:at>maximum?(float)maximum:at;
            low[c]=(unsigned)at;if(low[c]>=maximum)--low[c];fraction[c]=at-low[c];
        }
        for(unsigned y=0;y<2;++y)for(unsigned u=0;u<2;++u)for(unsigned b=0;b<2;++b){
            unsigned node=(low[0]+y)*81+(low[1]+u)*9+low[2]+b;
            double w=(y?fraction[0]:1-fraction[0])*(u?fraction[1]:1-fraction[1])*(b?fraction[2]:1-fraction[2]);
            for(unsigned c=0;c<3;++c){double d=rgb[c]-p->targets[0][i][c];priority[c*405+node]+=w*(d<0?-d:d);}
        }
    }
    /* 优先级只用于训练候选顺序；接受仍调用完整整数模型，不把它当梯度证明。 */
    for(unsigned i=0;i<1215;++i){unsigned n=i;while(n&&priority[order[n-1]]<priority[i]){order[n]=order[n-1];--n;}order[n]=i;}
    return 0;
}
int desktop_asset(DesktopFit *p,const int16_t *v,const int8_t *grid,void *out,size_t cap){
    int status=recipe(p,v,grid);if(status)return status;
    AfJointAsset asset={0};asset.recipe=p->trial;asset.native_mode=1;
    asset.matrix_mode=p->matrix_mode;
    if(p->matrix_mode)memcpy(asset.sector_matrix,p->sector_matrix,576);
    memcpy(asset.native_seed,p->seed.gamma,516);memcpy(asset.native_tone,v,6);memcpy(asset.model_sha256,p->model.model_sha256,32);
    size_t written=0;status=af_joint_asset_encode(&asset,out,cap,&written);
    return status?status:written==af_joint_asset_size(&asset)?0:AF_INVALID;
}
int desktop_decode(DesktopFit *p,const void *raw,size_t bytes,int16_t *v,int8_t *grid){
    AfJointAsset a;
    if(!p||!v||!grid)return AF_INVALID;
    int status=af_joint_asset_decode(raw,bytes,&a);if(status)return status;
    if(a.base||a.native_mode!=1||a.matrix_mode!=p->matrix_mode||memcmp(a.model_sha256,p->model.model_sha256,32)||
       memcmp(a.native_seed,p->seed.gamma,516))return AF_STALE;
    memcpy(v,a.native_tone,6);
    memcpy(v+3,p->matrix_mode?a.sector_matrix:a.recipe.matrix,p->matrix_mode?576:36);
    memcpy(v+3+(p->matrix_mode?288:18),a.recipe.cc1,48);memcpy(grid,a.recipe.grid,1215);
    return 0;
}
int recipe_file_asset(const void *raw,size_t bytes){AfJointAsset a;return af_joint_asset_decode(raw,bytes,&a);}
int recipe_file_document(const void *raw,size_t bytes){
    AfDocument d;AfJointAsset a;int status=af_document_decode(raw,bytes,AF_JOINT_ASSET_SCHEMA,&d);
    if(status)return status;if(d.present!=1)return AF_INVALID;
    return d.initial.kind?af_import_asset(&d,&a):AF_OK;
}
