#include "af_reference_domain.h"
#include "af_sha256.h"
#include <float.h>
#define DOMAIN_MAGIC 0x31444a41u
#define DOMAIN_SEEDS 125u

/* 固定8bd8564f版本photo_preview.py，228及241～244行显式定义预览解释。 */
const uint8_t af_reference_domain_policy_sha256[32]={
    0xc3,0xd9,0x87,0x64,0x4e,0x9d,0xe0,0x46,0x83,0x7c,0x83,0x0a,0x32,0xdc,0x3b,0x45,
    0x1c,0x8c,0x69,0x9e,0x0c,0x02,0x0b,0x14,0x1d,0x2f,0x3c,0x10,0x99,0x40,0x67,0x88};
typedef struct {
    AfEditJointEvalWork pixel;
    uint16_t seeds[DOMAIN_SEEDS][3];
    float colors[DOMAIN_SEEDS][3];
} DomainWork;
struct AfReferenceDomainState {
    uint32_t magic,phase,busy,seed_index,node,nodes,total,done;
    uint32_t attempts,direction,changed,initialized;
    uint16_t best[3];
    uint32_t step[3];
    float target[3],actual[3];
    double cost,error_sum;
    AfReferenceDomainConfig config;
    AfReferenceDomainBuffers buffers;
    AfReferenceDomainReport report;
    DomainWork *work;
    AfGridProgress progress;
    void *context;
};
typedef struct {const void *p;size_t n;} Span;
static int finite(float v){return v==v&&v>=-FLT_MAX&&v<=FLT_MAX;}
static int apart(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
static int equal(const uint8_t *a,const uint8_t *b){unsigned d=0;for(unsigned i=0;i<32;++i)d|=a[i]^b[i];return !d;}
static int nonzero(const uint8_t *a){unsigned d=0;for(unsigned i=0;i<32;++i)d|=a[i];return d!=0;}
static void put(uint8_t *out,unsigned *at,uint32_t v){for(unsigned i=0;i<4;++i)out[(*at)++]=(uint8_t)(v>>(8*i));}
static int source_hash(const AfReferenceDomainConfig *c,uint8_t digest[32]){
    uint8_t data[176];unsigned at=0;
    put(data,&at,DOMAIN_MAGIC);put(data,&at,c->policy);put(data,&at,c->base);
    put(data,&at,c->dimension);put(data,&at,c->evaluations_per_node);
    union{float f;uint32_t u;} tolerance={.f=c->unreachable_tolerance};put(data,&at,tolerance.u);
    for(unsigned i=0;i<3;++i){put(data,&at,c->native_minimum[i]);put(data,&at,c->native_maximum[i]);}
    for(unsigned i=0;i<32;++i)data[at++]=af_reference_domain_policy_sha256[i];
    for(unsigned i=0;i<32;++i)data[at++]=c->context_sha256[i];
    for(unsigned i=0;i<32;++i)data[at++]=c->baseline->recipe_sha256[i];
    return af_sha256(data,at,digest);
}
static int source_valid(const AfReferenceDomainState *s){
    return s->config.baseline&&s->config.baseline->valid==1&&
        equal(s->config.context_sha256,s->config.baseline->source_sha256);
}
static int forward(AfReferenceDomainState *s,const uint16_t point[3],float output[3]){
    uint16_t result[3];
    int status=af_edit_joint_eval(s->config.baseline,point,&s->work->pixel,result);
    if(status!=AF_OK)return status;
    for(unsigned c=0;c<3;++c)output[c]=(float)result[c]/16383.0f;
    ++s->report.evaluations;return AF_OK;
}
static double cost(const float a[3],const float b[3]){
    double value=0;for(unsigned c=0;c<3;++c){double d=(double)a[c]-b[c];value+=d*d;}return value;
}
static int notify(AfReferenceDomainState *s,uint32_t done){
    return s->progress&&s->progress(s->context,done,s->total);
}
static void begin_node(AfReferenceDomainState *s){
    unsigned n=s->config.dimension,index=s->node;
    s->target[0]=(float)(index%n)/(float)(n-1);index/=n;
    s->target[1]=(float)(index%n)/(float)(n-1);index/=n;
    s->target[2]=(float)index/(float)(n-1);
    unsigned best=0;double best_cost=cost(s->work->colors[0],s->target);
    for(unsigned i=1;i<DOMAIN_SEEDS;++i){double next=cost(s->work->colors[i],s->target);if(next<best_cost){best=i;best_cost=next;}}
    for(unsigned c=0;c<3;++c){
        s->best[c]=s->work->seeds[best][c];s->actual[c]=s->work->colors[best][c];
        s->step[c]=((uint32_t)s->config.native_maximum[c]-s->config.native_minimum[c])/4u;
        if(!s->step[c])s->step[c]=1;
    }
    s->cost=best_cost;s->attempts=s->direction=s->changed=0;s->initialized=1;
}
static void finish_node(AfReferenceDomainState *s){
    float maximum=0;
    for(unsigned c=0;c<3;++c){
        s->buffers.input_values[s->node*3+c]=(float)s->best[c];
        float d=s->actual[c]-s->target[c];if(d<0)d=-d;if(d>maximum)maximum=d;
    }
    s->error_sum+=maximum;if(maximum>s->report.max_abs_rgb)s->report.max_abs_rgb=maximum;
    if(maximum>s->config.unreachable_tolerance)++s->report.unreachable;
    s->done+=s->config.evaluations_per_node-s->attempts;
    ++s->node;s->initialized=0;
}
static int publish(AfReferenceDomainState *s){
    AfReferenceMap incoming={.schema=1,.input_domain=AF_REFERENCE_SRGB,.output_domain=AF_REFERENCE_EDIT_INPUT,
        .dimension=s->config.dimension,.base=s->config.base,.values=s->buffers.input_values,.count=s->nodes*3u};
    AfReferenceMap outgoing={.schema=1,.input_domain=AF_REFERENCE_EDIT_OUTPUT,.output_domain=AF_REFERENCE_SRGB,
        .dimension=2,.base=s->config.base,.values=s->buffers.output_values,.count=24};
    for(unsigned c=0;c<3;++c){incoming.maximum[c]=1;outgoing.maximum[c]=16383;}
    for(unsigned i=0;i<8;++i){
        s->buffers.output_values[3*i]=(float)(i&1u);
        s->buffers.output_values[3*i+1]=(float)((i>>1)&1u);
        s->buffers.output_values[3*i+2]=(float)((i>>2)&1u);
    }
    if(af_sha256(s->buffers.input_values,incoming.count*sizeof(float),incoming.data_sha256)||
       af_sha256(s->buffers.output_values,outgoing.count*sizeof(float),outgoing.data_sha256))return AF_INVALID;
    for(unsigned i=0;i<32;++i){
        incoming.context_sha256[i]=outgoing.context_sha256[i]=s->config.context_sha256[i];
        incoming.source_sha256[i]=outgoing.source_sha256[i]=s->report.source_sha256[i];
    }
    s->report.mean_max_abs_rgb=(float)(s->error_sum/s->nodes);
    if(notify(s,s->total))return AF_GRID_CANCELLED;
    if(!source_valid(s))return AF_STALE;
    *s->buffers.input_map=incoming;*s->buffers.output_map=outgoing;*s->buffers.report=s->report;
    return AF_OK;
}
size_t af_reference_domain_state_bytes(void){return sizeof(AfReferenceDomainState);}
size_t af_reference_domain_work_bytes(void){return sizeof(DomainWork);}
int af_reference_domain_start(AfReferenceDomainState *s,const AfReferenceDomainConfig *c,
    const AfReferenceDomainBuffers *b,void *work,AfGridProgress progress,void *context){
    if(!s||!c||!b||!work||((uintptr_t)s%_Alignof(AfReferenceDomainState))||
       ((uintptr_t)work%_Alignof(DomainWork)))return AF_INVALID;
    if(s->magic==DOMAIN_MAGIC&&s->phase<3)return AF_BUSY;
    if(s->magic&&s->magic!=DOMAIN_MAGIC)return AF_INVALID;
    if(c->schema!=1||c->policy!=AF_REFERENCE_DOMAIN_POLICY||c->base>=32||!(0x603ffu&(1u<<c->base))||
       c->dimension<2||c->dimension>17||c->evaluations_per_node<6||
       c->evaluations_per_node>AF_REFERENCE_DOMAIN_MAX_EVALUATIONS||
       !finite(c->unreachable_tolerance)||c->unreachable_tolerance<0||c->unreachable_tolerance>1||
       !c->baseline||c->baseline->valid!=1||!nonzero(c->context_sha256)||
       !equal(c->context_sha256,c->baseline->source_sha256))return AF_INVALID;
    for(unsigned i=0;i<3;++i)if(c->native_minimum[i]>=c->native_maximum[i])return AF_INVALID;
    unsigned nodes=c->dimension*c->dimension*c->dimension;
    if(b->input_capacity<nodes*3u||b->input_capacity>17u*17u*17u*3u||b->output_capacity!=24)return AF_INVALID;
    const Span spans[]={{s,sizeof(*s)},{c,sizeof(*c)},{b,sizeof(*b)},
        {work,sizeof(DomainWork)},{c->baseline,sizeof(*c->baseline)},
        {b->input_values,b->input_capacity*sizeof(float)},{b->output_values,24*sizeof(float)},
        {b->input_map,sizeof(*b->input_map)},{b->output_map,sizeof(*b->output_map)},{b->report,sizeof(*b->report)}};
    for(unsigned i=0;i<sizeof(spans)/sizeof(spans[0]);++i){
        if(!spans[i].p||(uintptr_t)spans[i].p>UINTPTR_MAX-spans[i].n)return AF_INVALID;
        for(unsigned j=0;j<i;++j)if(!apart(spans[i].p,spans[i].n,spans[j].p,spans[j].n))return AF_INVALID;
    }
    AfReferenceDomainState next={0};next.magic=DOMAIN_MAGIC;next.phase=1;next.config=*c;next.buffers=*b;
    next.work=work;next.progress=progress;next.context=context;next.nodes=nodes;
    next.total=DOMAIN_SEEDS+nodes*c->evaluations_per_node;
    next.report.nodes=nodes;next.report.research_only=1;next.report.unreachable_tolerance=c->unreachable_tolerance;
    for(unsigned i=0;i<3;++i){next.report.native_minimum[i]=c->native_minimum[i];next.report.native_maximum[i]=c->native_maximum[i];}
    for(unsigned i=0;i<32;++i){next.report.context_sha256[i]=c->context_sha256[i];next.report.policy_sha256[i]=af_reference_domain_policy_sha256[i];}
    if(source_hash(c,next.report.source_sha256))return AF_INVALID;
    *s=next;s->busy=1;int cancelled=notify(s,0);s->busy=0;
    if(cancelled){s->phase=4;return AF_GRID_CANCELLED;}return AF_JOINT_MORE;
}
int af_reference_domain_step(AfReferenceDomainState *s,uint32_t budget){
    if(!s||s->magic!=DOMAIN_MAGIC||!budget||budget>64)return AF_INVALID;
    if(s->busy)return AF_BUSY;
    if(s->phase>=3)return AF_STALE;
    s->busy=1;int result=AF_JOINT_MORE;
    for(unsigned unit=0;unit<budget;++unit){
        if(!source_valid(s)){result=AF_STALE;break;}
        if(notify(s,s->done)){result=AF_GRID_CANCELLED;break;}
        if(s->phase==1){
            static const unsigned numerator[5]={0,1,4,16,64};unsigned index=s->seed_index;
            for(unsigned c=0;c<3;++c){
                unsigned low=s->config.native_minimum[c],range=s->config.native_maximum[c]-low;
                s->work->seeds[s->seed_index][c]=(uint16_t)(low+(range*numerator[index%5]+32u)/64u);index/=5;
            }
            result=forward(s,s->work->seeds[s->seed_index],s->work->colors[s->seed_index]);
            if(result!=AF_OK)break;
            ++s->seed_index;++s->done;if(s->seed_index==DOMAIN_SEEDS)s->phase=2;
        }else{
            if(!s->initialized)begin_node(s);
            uint16_t trial[3];for(unsigned c=0;c<3;++c)trial[c]=s->best[c];
            unsigned axis=s->direction/2;int64_t value=(int64_t)trial[axis]+((s->direction&1u)?-(int64_t)s->step[axis]:(int64_t)s->step[axis]);
            if(value<s->config.native_minimum[axis])value=s->config.native_minimum[axis];
            if(value>s->config.native_maximum[axis])value=s->config.native_maximum[axis];
            if(value!=trial[axis]){
                trial[axis]=(uint16_t)value;float actual[3];result=forward(s,trial,actual);if(result!=AF_OK)break;
                double candidate=cost(actual,s->target);
                if(candidate<s->cost){s->cost=candidate;s->changed=1;for(unsigned c=0;c<3;++c){s->best[c]=trial[c];s->actual[c]=actual[c];}}
            }
            ++s->attempts;++s->done;unsigned complete=0;
            if(++s->direction==6){
                s->direction=0;
                if(!s->changed){
                    unsigned more=0;for(unsigned c=0;c<3;++c){if(s->step[c]>1){s->step[c]/=2;more=1;}}
                    if(!more)complete=1;
                }
                s->changed=0;
            }
            if(complete||s->attempts>=s->config.evaluations_per_node){finish_node(s);if(s->node==s->nodes){result=publish(s);break;}}
        }
        result=AF_JOINT_MORE;
    }
    s->busy=0;if(result!=AF_JOINT_MORE)s->phase=result==AF_OK?3:4;return result;
}
