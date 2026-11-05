/* 从固定seed构造量化基函数，所有组件共享一次完整预测选优。 */
#include "af_joint_basis.h"
#include <float.h>
typedef struct {const void *pointer;size_t bytes;} Span;
static int finite(float value) {return value==value && value>=-FLT_MAX && value<=FLT_MAX;}
static int apart(const void *a,size_t na,const void *b,size_t nb) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-na && y<=UINTPTR_MAX-nb &&
        (x+na<=y || y+nb<=x);
}
static int spans(const Span *items,unsigned count) {
    for(unsigned i=0;i<count;++i) {
        if(!items[i].pointer || (uintptr_t)items[i].pointer>UINTPTR_MAX-items[i].bytes)return 0;
        for(unsigned j=0;j<i;++j)
            if(!apart(items[i].pointer,items[i].bytes,items[j].pointer,items[j].bytes))return 0;
    }
    return 1;
}
int af_joint_basis_recipe(const AfJointRecipe *seed,const int16_t *controls,AfJointRecipe *output) {
    const Span inputs[]={{seed,sizeof(*seed)},{controls,17*sizeof(*controls)},{output,sizeof(*output)}};
    if(!spans(inputs,3) || af_joint_valid(seed)!=AF_OK)return AF_INVALID;
    for(unsigned i=0;i<17;++i)if(controls[i]<-1024 || controls[i]>1024)return AF_INVALID;
    AfJointRecipe next=*seed;
    if(af_joint_gamma(seed->gamma,controls,next.gamma)!=AF_OK)return AF_JOINT_SKIP;
    for(unsigned i=0;i<18;++i) {
        int value=seed->matrix[i]+controls[3+i%6];
        if(value<-1024 || value>1024)return AF_JOINT_SKIP;
        next.matrix[i]=(int16_t)value;
    }
    for(unsigned i=0;i<24;++i) {
        int value=seed->cc1[i]+controls[9+i%8];
        if(value<-1024 || value>1024)return AF_JOINT_SKIP;
        next.cc1[i]=(int16_t)value;
    }
    *output=next;return AF_OK;
}
size_t af_joint_basis_state_bytes(void) {return sizeof(AfJointBasisState);}
static int options_valid(const AfJointBasisOptions *o) {
    if(!o || o->evaluations<2 || o->evaluations>AF_JOINT_EVALUATIONS ||
        !o->tone_step || o->tone_step>1024 || !o->matrix_step || o->matrix_step>1024 ||
        !o->cc1_step || o->cc1_step>1024 || !o->grid_step || o->grid_step>32 ||
        !o->matrix_bound || o->matrix_bound>1024 || !o->cc1_bound || o->cc1_bound>1024)return 0;
    for(unsigned i=0;i<3;++i)if(!o->tone_bound[i] || o->tone_bound[i]>1024)return 0;
    return 1;
}
static unsigned code(float value) {
    return (unsigned)((double)(value<0?0:value>1?1:value)*255.0+.5);
}
static int score(AfJointBasisState *s,const AfJointRecipe *recipe,double *cost) {
    double sum=0;
    for(size_t i=0;i<s->count;++i) {
        float predicted[3];
        int status=s->model.predict(s->model.context,recipe,s->samples[i].rgb,predicted);
        ++s->fit.predictions;
        if(status==AF_JOINT_SKIP)return status;
        if(status!=AF_OK)return AF_JOINT_MODEL_ERROR;
        for(unsigned j=0;j<3;++j) {
            if(!finite(predicted[j]))return AF_JOINT_MODEL_ERROR;
            double difference=((double)code(predicted[j])-code(s->work->target[i][j]))/255.0;
            sum+=(double)s->work->mass[i]*difference*difference;
        }
        if((i&63u)==63u && s->progress &&
            s->progress(s->context,s->fit.evaluations,s->options.evaluations))return AF_GRID_CANCELLED;
    }
    *cost=sum/3;return AF_OK;
}
int af_joint_basis_start(AfJointBasisState *state,const AfJointModel *model,uint32_t base,
    const AfCube *cube,const AfGridSample *samples,size_t count,const AfJointRecipe *seed,
    const AfJointBasisOptions *options,AfJointWork *work,AfJointRecipe *output,
    AfJointFit *result,AfGridProgress progress,void *context) {
    if(!state)return AF_INVALID;
    if(state->phase==1 || state->phase==4)return AF_BUSY;
    if(state->phase>4 || af_joint_model_valid(model,base)!=AF_OK ||
        !cube || cube->dimension<2 || cube->dimension>33 || count<2 ||
        count>AF_JOINT_SAMPLES || af_joint_valid(seed)!=AF_OK || !options_valid(options))return AF_INVALID;
    const Span sources[]={{state,sizeof(*state)},{model,sizeof(*model)},{cube,sizeof(*cube)},
        {cube->values,(size_t)cube->dimension*cube->dimension*cube->dimension*12},
        {samples,count*sizeof(*samples)},{seed,sizeof(*seed)},{options,sizeof(*options)},
        {work,sizeof(*work)},{output,sizeof(*output)},{result,sizeof(*result)}};
    if(!spans(sources,10))return AF_INVALID;
    AfJointBasisState next={0};
    next.model=*model;next.options=*options;next.seed=*seed;next.samples=samples;
    next.count=count;next.work=work;next.output=output;next.result=result;
    next.progress=progress;next.context=context;next.phase=4;*state=next;
    if(progress && progress(context,0,options->evaluations)){state->phase=3;return AF_GRID_CANCELLED;}
    float mass=0;
    for(size_t i=0;i<count;++i) {
        if(!finite(samples[i].weight) || samples[i].weight<=0 || samples[i].weight>1000000 ||
            (samples[i].group&~3u)){state->phase=3;return AF_INVALID;}
        for(unsigned j=0;j<3;++j)if(!finite(samples[i].rgb[j]) ||
            samples[i].rgb[j]<0 || samples[i].rgb[j]>1){state->phase=3;return AF_INVALID;}
        if(af_cube_eval(cube,samples[i].rgb,work->target[i])!=AF_CUBE_OK){state->phase=3;return AF_INVALID;}
        for(unsigned j=0;j<3;++j)if(!finite(work->target[i][j])){state->phase=3;return AF_INVALID;}
        mass+=samples[i].weight;
    }
    for(size_t i=0;i<count;++i)work->mass[i]=samples[i].weight/mass;
    work->current=*seed;
    int status=score(state,&work->current,&state->best);
    if(status!=AF_OK){state->phase=3;return status==AF_JOINT_SKIP?AF_JOINT_MODEL_ERROR:status;}
    state->fit.evaluations=1;state->fit.initial_mse=(float)state->best;state->fit.research_only=1;
    state->steps[0]=options->tone_step;state->steps[1]=options->matrix_step;
    state->steps[2]=options->cc1_step;state->steps[3]=options->grid_step;
    state->phase=1;return AF_JOINT_MORE;
}
static int trial(AfJointBasisState *s,int16_t proposed[17]) {
    AfJointWork *w=s->work;unsigned family=s->family,index=s->cursor[family];
    int delta=s->polarity?-(int)s->steps[family]:(int)s->steps[family];
    for(unsigned i=0;i<17;++i)proposed[i]=s->controls[i];
    if(family<3) {
        unsigned dimension=index+(family==0?0:family==1?3:9);
        int value=proposed[dimension]+delta;
        unsigned limit=family==0?s->options.tone_bound[index]:
            family==1?s->options.matrix_bound:s->options.cc1_bound;
        if(value<-(int)limit || value>(int)limit)return AF_JOINT_SKIP;
        proposed[dimension]=(int16_t)value;
        int status=af_joint_basis_recipe(&s->seed,proposed,&w->trial);
        if(status!=AF_OK)return status;
        for(unsigned i=0;i<AF_GRID_BYTES;++i)w->trial.grid[i]=w->current.grid[i];
    } else {
        w->trial=w->current;
        /* 先评估三通道整体平移，再细化单节点；稀疏训练时不浪费全部预算。 */
        unsigned begin=index<3?index*AF_GRID_NODES:index-3;
        unsigned end=index<3?begin+AF_GRID_NODES:begin+1;
        for(unsigned i=begin;i<end;++i) {
            int value=w->trial.grid[i]+delta;
            if(value<-64 || value>63)return AF_JOINT_SKIP;
            w->trial.grid[i]=(int8_t)value;
        }
    }
    return AF_OK;
}
int af_joint_basis_step(AfJointBasisState *s,uint32_t budget) {
    static const unsigned count[4]={3,6,8,AF_GRID_BYTES+3};
    if(!s || !budget || budget>64)return AF_INVALID;
    if(s->phase==4)return AF_BUSY;
    if(s->phase!=1)return AF_STALE;
    s->phase=4;
    if(s->progress && s->progress(s->context,s->fit.evaluations,s->options.evaluations)){
        s->phase=3;return AF_GRID_CANCELLED;
    }
    for(unsigned i=0;i<budget && s->fit.evaluations<s->options.evaluations;++i) {
        unsigned family=s->family;double cost=0;int16_t proposed[17];
        int status=trial(s,proposed);s->fit.attempted_components|=1u<<family;
        if(status==AF_OK)status=score(s,&s->work->trial,&cost);
        if(status==AF_GRID_CANCELLED || status==AF_JOINT_MODEL_ERROR){s->phase=3;return status;}
        if(status!=AF_OK)++s->fit.rejected;
        else if(cost<s->best) {
            s->best=cost;s->work->current=s->work->trial;++s->fit.accepted[family];
            for(unsigned j=0;j<17;++j)s->controls[j]=proposed[j];
        }
        ++s->fit.evaluations;
        if(s->progress && s->progress(s->context,s->fit.evaluations,s->options.evaluations)){
            s->phase=3;return AF_GRID_CANCELLED;
        }
        if(s->polarity) {
            s->polarity=0;
            if(++s->cursor[family]==count[family]) {
                s->cursor[family]=0;s->steps[family]=s->steps[family]>1?s->steps[family]/2:1;
            }
            s->family=(family+1)%4;
        } else s->polarity=1;
    }
    if(s->fit.evaluations<s->options.evaluations){s->phase=1;return AF_JOINT_MORE;}
    s->fit.final_mse=(float)s->best;*s->output=s->work->current;*s->result=s->fit;
    s->phase=2;return AF_OK;
}
int af_joint_basis_fit(const AfJointModel *model,uint32_t base,const AfCube *cube,
    const AfGridSample *samples,size_t count,const AfJointRecipe *seed,
    const AfJointBasisOptions *options,AfJointWork *work,AfJointRecipe *output,
    AfJointFit *result,AfGridProgress progress,void *context) {
    AfJointBasisState state={0};
    int status=af_joint_basis_start(&state,model,base,cube,samples,count,seed,options,
        work,output,result,progress,context);
    while(status==AF_JOINT_MORE)status=af_joint_basis_step(&state,64);
    return status;
}
