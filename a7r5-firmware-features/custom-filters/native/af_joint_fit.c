/* 四组件共享同一量化目标的有界整数搜索；不内置未经验证的ISP替身。 */
#include "af_joint.h"
#include <float.h>
typedef struct { const void *p;size_t n; } Span;
static int finite(float v) { return v==v && v>=-FLT_MAX && v<=FLT_MAX; }
static int spans(const Span *s,unsigned n) {
    for (unsigned i=0;i<n;++i) {
        uintptr_t a=(uintptr_t)s[i].p;
        if (!a || a>UINTPTR_MAX-s[i].n) return 0;
        for (unsigned j=0;j<i;++j) {
            uintptr_t b=(uintptr_t)s[j].p;
            if (a<b+s[j].n && b<a+s[i].n) return 0;
        }
    }
    return 1;
}
int af_joint_model_valid(const AfJointModel *m,uint32_t base) {
    unsigned any=0;
    if (!m || m->schema!=1 || m->domain!=1 || m->components!=AF_JOINT_COMPONENTS || !m->predict ||
        !m->base_mask || (m->base_mask&~0x603ffu) || base>=32 || !(m->base_mask&(1u<<base))) return AF_INVALID;
    for (unsigned i=0;i<32;++i) {if (m->cp_sha256[i]!=af_joint_cp_sha256[i]) return AF_INVALID;any|=m->model_sha256[i];}
    return any?AF_OK:AF_INVALID;
}
static unsigned code(float v) {
    return (unsigned)((double)(v<0?0:v>1?1:v)*255.0+.5);
}
static int score(const AfJointModel *m,const AfJointRecipe *r,const AfGridSample *samples,size_t n,
                 AfJointWork *w,double *cost,AfJointFit *fit,AfGridProgress progress,void *context,unsigned total) {
    double sum=0;
    for (size_t i=0;i<n;++i) {
        float predicted[3];int status=m->predict(m->context,r,samples[i].rgb,predicted);++fit->predictions;
        if (status==AF_JOINT_SKIP) return status;
        if (status!=AF_OK) return AF_JOINT_MODEL_ERROR;
        for (unsigned j=0;j<3;++j) {
            double d;
            if (!finite(predicted[j])) return AF_JOINT_MODEL_ERROR;
            d=((double)code(predicted[j])-code(w->target[i][j]))/255.0;
            sum+=(double)w->mass[i]*d*d;
        }
        if ((i&63u)==63u && progress && progress(context,fit->evaluations,total)) return AF_GRID_CANCELLED;
    }
    *cost=sum/3;return AF_OK;
}
static int trial(AfJointWork *w,unsigned family,unsigned index,int sign,unsigned step,unsigned tone_step) {
    w->trial=w->current;
    if (!family) {
        if (index<3) {
            int16_t tone[3]={0};tone[index]=(int16_t)(sign*(int)tone_step);
            return af_joint_gamma(w->current.gamma,tone,w->trial.gamma);
        } else {
            unsigned i=index-2;int64_t v=(int64_t)w->current.gamma[i]+sign*(int)step;
            if (v<0 || v>0x3ffff || (i<128 && v>w->current.gamma[i+1]) || v<w->current.gamma[i-1]) return AF_JOINT_SKIP;
            w->trial.gamma[i]=(uint32_t)v;
        }
    } else if (family==1 || family==2) {
        int16_t *p=family==1?w->trial.matrix:w->trial.cc1;
        int value=p[index]+sign*(int)step;
        if (value<-1024 || value>1024) return AF_JOINT_SKIP;
        p[index]=(int16_t)value;
    } else {
        int value=w->trial.grid[index]+sign*(int)step;
        if (value<-64 || value>63) return AF_JOINT_SKIP;
        w->trial.grid[index]=(int8_t)value;
    }
    return af_joint_valid(&w->trial)==AF_OK?AF_OK:AF_JOINT_SKIP;
}
size_t af_joint_state_bytes(void) {return sizeof(AfJointState);}
int af_joint_fit_start(AfJointState *state,const AfJointModel *model,uint32_t base,const AfCube *cube,
                 const AfGridSample *samples,size_t n,const AfJointRecipe *seed,
                 const AfJointOptions *options,AfJointWork *w,AfJointRecipe *output,
                 AfJointFit *result,AfGridProgress progress,void *context) {
    float mass=0;
    if(!state)return AF_INVALID;
    if(state->phase==1 || state->phase==4)return AF_BUSY;
    if(state->phase>4)return AF_INVALID;
    if (af_joint_model_valid(model,base)!=AF_OK || !cube || cube->dimension<2 || cube->dimension>33 ||
        n<2 || n>AF_JOINT_SAMPLES || af_joint_valid(seed)!=AF_OK || !options ||
        options->evaluations<2 || options->evaluations>AF_JOINT_EVALUATIONS ||
        !options->gamma_step || options->gamma_step>4096 || !options->tone_step || options->tone_step>128 ||
        !options->matrix_step || options->matrix_step>256 || !options->cc1_step || options->cc1_step>256 ||
        !options->grid_step || options->grid_step>32) return AF_INVALID;
    {
        const Span s[]={{model,sizeof(*model)},{cube,sizeof(*cube)},
            {cube->values,(size_t)cube->dimension*cube->dimension*cube->dimension*12},
            {samples,n*sizeof(*samples)},{seed,sizeof(*seed)},{options,sizeof(*options)},
            {w,sizeof(*w)},{output,sizeof(*output)},{result,sizeof(*result)},
            {state,sizeof(*state)}};
        if (!spans(s,10)) return AF_INVALID;
    }
    AfJointState next={0};next.model=*model;next.options=*options;
    next.samples=samples;next.count=n;next.work=w;next.output=output;next.result=result;
    next.progress=progress;next.context=context;next.phase=4;*state=next;
    if (progress && progress(context,0,options->evaluations)) {state->phase=3;return AF_GRID_CANCELLED;}
    for (size_t i=0;i<n;++i) {
        if (!finite(samples[i].weight) || samples[i].weight<=0 || samples[i].weight>1000000 || (samples[i].group&~3u)) {state->phase=3;return AF_INVALID;}
        for (unsigned j=0;j<3;++j) if (!finite(samples[i].rgb[j]) || samples[i].rgb[j]<0 || samples[i].rgb[j]>1) {state->phase=3;return AF_INVALID;}
        if (af_cube_eval(cube,samples[i].rgb,w->target[i])!=AF_CUBE_OK) {state->phase=3;return AF_INVALID;}
        for (unsigned j=0;j<3;++j) if (!finite(w->target[i][j])) {state->phase=3;return AF_INVALID;}
        mass+=samples[i].weight;
    }
    for (size_t i=0;i<n;++i) w->mass[i]=samples[i].weight/mass;
    w->current=*seed;
    {
        int status=score(&state->model,&w->current,samples,n,w,&state->best,&state->fit,progress,context,options->evaluations);
        if (status!=AF_OK) {state->phase=3;return status==AF_JOINT_SKIP?AF_JOINT_MODEL_ERROR:status;}
    }
    state->fit.evaluations=1;state->fit.initial_mse=(float)state->best;state->fit.research_only=1;
    state->steps[0]=options->gamma_step;state->steps[1]=options->matrix_step;
    state->steps[2]=options->cc1_step;state->steps[3]=options->grid_step;
    state->tone_step=options->tone_step;state->phase=1;return AF_JOINT_MORE;
}
int af_joint_fit_step(AfJointState *s,uint32_t budget) {
    static const unsigned count[4]={131,18,24,1215};
    if(!s || !budget || budget>64)return AF_INVALID;
    if(s->phase!=1)return AF_STALE;
    AfJointWork *w=s->work;
    if(s->progress && s->progress(s->context,s->fit.evaluations,s->options.evaluations)) {s->phase=3;return AF_GRID_CANCELLED;}
    for(uint32_t i=0;i<budget && s->fit.evaluations<s->options.evaluations;++i) {
        unsigned family=s->family;double cost=0;
        int status=trial(w,family,s->cursor[family],s->polarity?-1:1,s->steps[family],s->tone_step);
        s->fit.attempted_components|=1u<<family;
        if(status==AF_OK)status=score(&s->model,&w->trial,s->samples,s->count,w,&cost,&s->fit,s->progress,s->context,s->options.evaluations);
        if(status==AF_GRID_CANCELLED || status==AF_JOINT_MODEL_ERROR){s->phase=3;return status;}
        if(status!=AF_OK)++s->fit.rejected;
        else if(cost<s->best){s->best=cost;w->current=w->trial;++s->fit.accepted[family];}
        ++s->fit.evaluations;
        if(s->progress && s->progress(s->context,s->fit.evaluations,s->options.evaluations)){s->phase=3;return AF_GRID_CANCELLED;}
        if(s->polarity) {
            s->polarity=0;
            if(++s->cursor[family]==count[family]) {
                s->cursor[family]=0;s->steps[family]=s->steps[family]>1?s->steps[family]/2:1;
                if(!family)s->tone_step=s->tone_step>1?s->tone_step/2:1;
            }
            s->family=(family+1)%4;
        } else s->polarity=1;
    }
    if(s->fit.evaluations<s->options.evaluations)return AF_JOINT_MORE;
    s->fit.final_mse=(float)s->best;*s->output=w->current;*s->result=s->fit;s->phase=2;return AF_OK;
}
int af_joint_fit(const AfJointModel *model,uint32_t base,const AfCube *cube,const AfGridSample *samples,size_t n,
                 const AfJointRecipe *seed,const AfJointOptions *options,AfJointWork *w,AfJointRecipe *output,
                 AfJointFit *result,AfGridProgress progress,void *context) {
    AfJointState state={0};
    int status=af_joint_fit_start(&state,model,base,cube,samples,n,seed,options,w,output,result,progress,context);
    while(status==AF_JOINT_MORE)status=af_joint_fit_step(&state,64);
    return status;
}
