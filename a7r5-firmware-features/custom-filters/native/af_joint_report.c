#include "af_joint_report.h"
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
int af_joint_report(const AfJointModel *m,uint32_t base,const AfCube *cube,const AfJointRecipe *r,
                    const AfGridSample *samples,size_t n,AfJointReportWork *w,AfGridReport *output,
                    AfGridProgress progress,void *context) {
    AfGridReport answer;
    if (af_joint_model_valid(m,base)!=AF_OK || af_joint_valid(r)!=AF_OK || !cube ||
        cube->dimension<2 || cube->dimension>33 || !n || n>AF_GRID_SAMPLES) return AF_INVALID;
    {
        const Span s[]={{m,sizeof(*m)},{cube,sizeof(*cube)},
            {cube->values,(size_t)cube->dimension*cube->dimension*cube->dimension*12},
            {r,sizeof(*r)},{samples,n*sizeof(*samples)},{w,sizeof(*w)},{output,sizeof(*output)}};
        if (!spans(s,7)) return AF_INVALID;
    }
    if (progress && progress(context,0,(uint32_t)n)) return AF_GRID_CANCELLED;
    for (size_t i=0;i<n;++i) {
        AfGridColor *color=&w->colors[i];
        if (!finite(samples[i].weight) || samples[i].weight<=0 || samples[i].weight>1000000 ||
            (samples[i].group&~3u)) return AF_INVALID;
        for (unsigned j=0;j<3;++j) if (!finite(samples[i].rgb[j]) || samples[i].rgb[j]<0 || samples[i].rgb[j]>1)
            return AF_INVALID;
        if (af_cube_eval(cube,samples[i].rgb,color->target)!=AF_CUBE_OK) return AF_INVALID;
        if (m->predict(m->context,r,samples[i].rgb,color->predicted)!=AF_OK) return AF_JOINT_MODEL_ERROR;
        for (unsigned j=0;j<3;++j) if (!finite(color->predicted[j])) return AF_JOINT_MODEL_ERROR;
        color->group=samples[i].group;
        if (progress && progress(context,(uint32_t)i+1,(uint32_t)n)) return AF_GRID_CANCELLED;
    }
    if (af_grid_color_report(w->colors,n,w->errors,&answer)!=AF_OK) return AF_INVALID;
    *output=answer;return AF_OK;
}
