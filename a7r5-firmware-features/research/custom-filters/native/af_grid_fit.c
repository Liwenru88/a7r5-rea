/* 独立的矩阵无关投影优化；研究响应模型不能代替真实ISP/基底适用性验收。 */
#include "af_grid.h"
#include <float.h>
static int finite(float x) { return x==x && x<=FLT_MAX && x>=-FLT_MAX; }
static float absolute(float x) { return x<0?-x:x; }
static float clip(float v,float low,float high) { return v<low?low:(v>high?high:v); }
static float root(float x) {
    union { float value;uint32_t bits; } a;
    float y;
    if (x<=0) return 0;
    a.value=x;a.bits=(a.bits>>1)+0x1fc00000u;y=a.value;
    for (unsigned i=0;i<6;++i) y=.5f*(y+x/y);
    return y;
}
typedef struct { const void *p;size_t n; } Span;
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
static int cube_size(const AfCube *c,size_t *bytes) {
    if (!c || c->dimension<2 || c->dimension>33 || !c->values) return 0;
    *bytes=(size_t)c->dimension*c->dimension*c->dimension*12;
    return 1;
}
static int sample_valid(const AfGridSample *s) {
    if (!s || !finite(s->weight) || s->weight<=0 || s->weight>1000000 || (s->group&~3u)) return 0;
    for (unsigned i=0;i<3;++i) if (!finite(s->rgb[i]) || s->rgb[i]<0 || s->rgb[i]>1) return 0;
    return 1;
}
static void raw(const AfGridRow *row,const float *grid,float out[3]) {
    float delta[3]={0};
    for (unsigned c=0;c<3;++c) for (unsigned j=0;j<8;++j)
        delta[c]+=row->weights[j]*grid[c*AF_GRID_NODES+row->index[j]];
    for (unsigned o=0;o<3;++o) {
        out[o]=row->base[o];
        for (unsigned c=0;c<3;++c) out[o]+=delta[c]*row->response[c*3+o];
    }
}
/* 同时计算相邻平滑损失及其梯度；每条无向边只访问一次。 */
static float smooth(const float *x,float *gradient,float strength) {
    float total=0;
    for (unsigned c=0;c<3;++c) for (unsigned y=0;y<5;++y)
    for (unsigned u=0;u<9;++u) for (unsigned v=0;v<9;++v) {
        unsigned a=c*405+y*81+u*9+v;
        const unsigned step[3]={81,9,1};
        const unsigned yes[3]={y<4,u<8,v<8};
        for (unsigned axis=0;axis<3;++axis) if (yes[axis]) {
            unsigned b=a+step[axis];float d=x[a]-x[b];total+=d*d;
            if (gradient) {gradient[a]+=strength*d;gradient[b]-=strength*d;}
        }
    }
    return .5f*strength*total;
}
static float mse(const AfGridWork *w,size_t n,const float *grid) {
    float total=0;
    for (size_t i=0;i<n;++i) {
        float p[3];raw(&w->rows[i],grid,p);
        for (unsigned o=0;o<3;++o) {float d=clip(p[o],0,1)-w->rows[i].target[o];total+=w->rows[i].mass*d*d;}
    }
    return total/3;
}
static int rounded(float v) {
    int x=(int)v;float fraction=v-(float)x;
    if (fraction>.5f || (fraction==.5f && x%2)) ++x;
    else if (fraction<-.5f || (fraction==-.5f && x%2)) --x;
    return x;
}
int af_grid_fit(const AfGridModel *model,uint32_t base,const AfCube *cube,const AfGridSample *samples,size_t n,
                unsigned iterations,float regularization,int8_t *out,AfGridWork *w,AfGridFit *result,
                AfGridProgress progress,void *context) {
    size_t bytes;float mass=0,lipschitz=0,momentum=1,best_loss;
    AfGridFit answer={0};AfGridModel m;
    if (af_grid_model_valid(model)!=AF_OK || base>=32 || !(model->base_mask&(1u<<base)) ||
        !cube_size(cube,&bytes) || n<2 || n>AF_GRID_SAMPLES || !iterations || iterations>AF_GRID_ITERATIONS ||
        !finite(regularization) || regularization<0 || regularization>1) return AF_INVALID;
    {
        const Span s[]={{model,sizeof(*model)},{cube,sizeof(*cube)},{cube->values,bytes},
            {samples,n*sizeof(*samples)},{out,AF_GRID_BYTES},{w,sizeof(*w)},{result,sizeof(*result)}};
        if (!spans(s,7)) return AF_INVALID;
    }
    m=*model;
    if (progress && progress(context,0,iterations)) return AF_GRID_CANCELLED;
    for (size_t i=0;i<n;++i) {
        float target[3];
        if (!sample_valid(&samples[i]) || af_grid_row(&m,samples[i].rgb,&w->rows[i])!=AF_OK ||
            af_cube_eval(cube,samples[i].rgb,target)!=AF_CUBE_OK) return AF_INVALID;
        for (unsigned o=0;o<3;++o) {
            if (!finite(target[o])) return AF_INVALID;
            w->rows[i].target[o]=clip(target[o],0,1);
        }
        mass+=samples[i].weight;
    }
    for (unsigned j=0;j<AF_GRID_BYTES;++j) w->x[j]=w->y[j]=w->best[j]=w->gradient[j]=0;
    for (size_t i=0;i<n;++i) {
        AfGridRow *r=&w->rows[i];r->mass=samples[i].weight/mass;
        for (unsigned o=0;o<3;++o) {
            float row_sum=0;
            for (unsigned c=0;c<3;++c) row_sum+=absolute(r->response[c*3+o]);
            for (unsigned c=0;c<3;++c) for (unsigned k=0;k<8;++k)
                w->gradient[c*405+r->index[k]]+=r->mass*r->weights[k]*absolute(r->response[c*3+o])*row_sum;
        }
    }
    regularization/=405.0f*65536;
    for (unsigned j=0;j<AF_GRID_BYTES;++j) if (w->gradient[j]>lipschitz) lipschitz=w->gradient[j];
    lipschitz+=12*regularization+1e-10f;
    answer.zero_mse=mse(w,n,w->x);best_loss=1.5f*answer.zero_mse;
    for (unsigned step=0;step<iterations;++step) {
        float change=0,loss,next_momentum=(1+root(1+4*momentum*momentum))*.5f;
        for (unsigned j=0;j<AF_GRID_BYTES;++j) w->gradient[j]=1e-10f*w->y[j];
        for (size_t i=0;i<n;++i) {
            const AfGridRow *r=&w->rows[i];float p[3],d[3];raw(r,w->y,p);
            for (unsigned o=0;o<3;++o) d[o]=p[o]>0 && p[o]<1?p[o]-r->target[o]:0;
            for (unsigned c=0;c<3;++c) {
                float g=0;
                for (unsigned o=0;o<3;++o) g+=d[o]*r->response[c*3+o];
                for (unsigned k=0;k<8;++k) w->gradient[c*405+r->index[k]]+=r->mass*r->weights[k]*g;
            }
        }
        (void)smooth(w->y,w->gradient,regularization);
        for (unsigned j=0;j<AF_GRID_BYTES;++j) {
            float d;
            w->next[j]=clip(w->y[j]-w->gradient[j]/lipschitz,-64,63);
            d=absolute(w->next[j]-w->x[j]);if (d>change) change=d;
        }
        loss=1.5f*mse(w,n,w->next)+smooth(w->next,0,regularization);
        if (loss<best_loss) {best_loss=loss;for (unsigned j=0;j<AF_GRID_BYTES;++j) w->best[j]=w->next[j];}
        for (unsigned j=0;j<AF_GRID_BYTES;++j) {
            w->y[j]=w->next[j]+(momentum-1)/next_momentum*(w->next[j]-w->x[j]);w->x[j]=w->next[j];
        }
        momentum=next_momentum;answer.iterations=step+1;answer.converged=change<.0001f;
        if (progress && progress(context,step+1,iterations)) return AF_GRID_CANCELLED;
        if (answer.converged) break;
    }
    for (unsigned j=0;j<AF_GRID_BYTES;++j) w->x[j]=(float)rounded(w->best[j]);
    answer.quantized_mse=mse(w,n,w->x);
    if (answer.quantized_mse>answer.zero_mse) {
        for (unsigned j=0;j<AF_GRID_BYTES;++j) w->x[j]=0;
        answer.quantized_mse=answer.zero_mse;answer.zero_selected=1;
    }
    for (unsigned j=0;j<AF_GRID_BYTES;++j) {
        int v=(int)w->x[j];if (v==-64 || v==63) ++answer.limited;
        out[j]=(int8_t)v;
    }
    *result=answer;return AF_OK;
}
/* 标准sRGB/D65 Lab计算；固定次数Newton迭代，不引入目标libm依赖。 */
static void lab(const float rgb[3],float out[3]) {
    static const float matrix[9]={.4124564f,.3575761f,.1804375f,.2126729f,.7151522f,.0721750f,.0193339f,.1191920f,.9503041f};
    static const float white[3]={.95047f,1,1.08883f};
    float linear[3],f[3];
    for (unsigned j=0;j<3;++j) {
        /* 先提升精度再按半入取整，避免float乘法把邻近半整数提前舍成精确半整数。 */
        float v=(float)(unsigned)((double)clip(rgb[j],0,1)*255.0+.5)/255;
        if (v<=.04045f) linear[j]=v/12.92f;
        else {
            float a=(v+.055f)/1.055f,t=a*a,y=1;
            for (unsigned k=0;k<16;++k) y=(4*y+t/(y*y*y*y))/5;
            linear[j]=a*a*y;
        }
    }
    for (unsigned j=0;j<3;++j) {
        float v=0;
        for (unsigned k=0;k<3;++k) v+=linear[k]*matrix[3*j+k];
        v/=white[j];
        if (v>216.0f/24389) {
            float y=1;for (unsigned k=0;k<12;++k) y=(2*y+v/(y*y))/3;f[j]=y;
        } else f[j]=v*(841.0f/108)+4.0f/29;
    }
    out[0]=116*f[1]-16;out[1]=500*(f[0]-f[1]);out[2]=200*(f[1]-f[2]);
}
static void down(float *a,size_t n,size_t root_index) {
    for (;;) {
        size_t child=root_index*2+1,big=root_index;
        if (child<n && a[child]>a[big]) big=child;
        if (child+1<n && a[child+1]>a[big]) big=child+1;
        if (big==root_index) return;
        {float v=a[root_index];a[root_index]=a[big];a[big]=v;}
        root_index=big;
    }
}
int af_grid_color_report(const AfGridColor *colors,size_t n,float *errors,AfGridReport *output) {
    AfGridReport r={0};float total=0,gray=0,skin=0,squared=0;
    if (!n || n>AF_GRID_SAMPLES) return AF_INVALID;
    {
        const Span s[]={{colors,n*sizeof(*colors)},{errors,n*sizeof(*errors)},{output,sizeof(*output)}};
        if (!spans(s,3)) return AF_INVALID;
    }
    for (size_t i=0;i<n;++i) {
        float target[3],predicted[3],a[3],b[3],delta=0;unsigned clipped=0;
        if (colors[i].group&~3u) return AF_INVALID;
        for (unsigned j=0;j<3;++j) {
            float t=colors[i].target[j],p=colors[i].predicted[j],d;
            if (!finite(t) || !finite(p)) return AF_INVALID;
            clipped|=t<0 || t>1 || p<0 || p>1;
            target[j]=(float)(unsigned)((double)clip(t,0,1)*255.0+.5)/255;
            predicted[j]=(float)(unsigned)((double)clip(p,0,1)*255.0+.5)/255;
            d=target[j]-predicted[j];squared+=d*d;
        }
        lab(target,a);lab(predicted,b);
        for (unsigned j=0;j<3;++j) {float d=a[j]-b[j];delta+=d*d;}
        delta=root(delta);errors[i]=delta;total+=delta;
        if (delta>r.delta_e76[2]) r.delta_e76[2]=delta;
        if (colors[i].group&1) {gray+=delta;++r.gray_samples;}
        if (colors[i].group&2) {skin+=delta;++r.skin_samples;}
        r.clipped+=clipped;
    }
    for (size_t i=n/2;i>0;--i) down(errors,n,i-1);
    for (size_t i=n;i>1;--i) {float v=errors[0];errors[0]=errors[i-1];errors[i-1]=v;down(errors,i-1,0);}
    r.samples=(uint32_t)n;r.rgb_rmse=root(squared/((float)n*3));r.delta_e76[0]=total/(float)n;
    r.delta_e76[1]=errors[(95*n+99)/100-1];
    r.delta_e76[3]=r.gray_samples?gray/(float)r.gray_samples:0;
    r.delta_e76[4]=r.skin_samples?skin/(float)r.skin_samples:0;
    *output=r;return AF_OK;
}
int af_grid_report(const AfGridModel *model,const AfCube *cube,const int8_t *grid,const AfGridSample *samples,
                   size_t n,AfGridWork *w,AfGridReport *report) {
    size_t bytes;AfGridReport r={0};float total=0,gray=0,skin=0,squared=0;
    if (af_grid_model_valid(model)!=AF_OK || !cube_size(cube,&bytes) || !n || n>AF_GRID_SAMPLES) return AF_INVALID;
    {
        const Span s[]={{model,sizeof(*model)},{cube,sizeof(*cube)},{cube->values,bytes},{grid,AF_GRID_BYTES},
            {samples,n*sizeof(*samples)},{w,sizeof(*w)},{report,sizeof(*report)}};
        if (!spans(s,7)) return AF_INVALID;
    }
    for (unsigned j=0;j<AF_GRID_BYTES;++j) {if (grid[j]<-64 || grid[j]>63) return AF_INVALID;w->x[j]=grid[j];}
    for (size_t i=0;i<n;++i) {
        AfGridRow row;float target[3],predicted[3],a[3],b[3],delta=0;unsigned clipped=0;
        if (!sample_valid(&samples[i]) || af_grid_row(model,samples[i].rgb,&row)!=AF_OK ||
            af_cube_eval(cube,samples[i].rgb,target)!=AF_CUBE_OK) return AF_INVALID;
        raw(&row,w->x,predicted);
        for (unsigned j=0;j<3;++j) {
            float d;
            if (!finite(target[j]) || !finite(predicted[j])) return AF_INVALID;
            clipped|=target[j]<0 || target[j]>1 || predicted[j]<0 || predicted[j]>1;
            target[j]=clip(target[j],0,1);predicted[j]=clip(predicted[j],0,1);
            d=target[j]-predicted[j];squared+=d*d;
        }
        lab(target,a);lab(predicted,b);
        for (unsigned j=0;j<3;++j) {float d=a[j]-b[j];delta+=d*d;}
        delta=root(delta);w->errors[i]=delta;total+=delta;
        if (delta>r.delta_e76[2]) r.delta_e76[2]=delta;
        if (samples[i].group&1) {gray+=delta;++r.gray_samples;}
        if (samples[i].group&2) {skin+=delta;++r.skin_samples;}
        r.clipped+=clipped;
    }
    /* 原地堆排序：最坏O(n log n)，不用递归或动态分配。 */
    for (size_t i=n/2;i>0;--i) down(w->errors,n,i-1);
    for (size_t i=n;i>1;--i) {float v=w->errors[0];w->errors[0]=w->errors[i-1];w->errors[i-1]=v;down(w->errors,i-1,0);}
    r.samples=(uint32_t)n;r.rgb_rmse=root(squared/((float)n*3));r.delta_e76[0]=total/(float)n;
    r.delta_e76[1]=w->errors[(95*n+99)/100-1];
    r.delta_e76[3]=r.gray_samples?gray/(float)r.gray_samples:0;
    r.delta_e76[4]=r.skin_samples?skin/(float)r.skin_samples:0;
    *report=r;return AF_OK;
}
