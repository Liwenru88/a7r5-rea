/* 先实际前向，再固定颜色区域划分；没有全RGB反解或最近点回退。 */
#include "af_reference_samples.h"
#include "af_sha256.h"
#define SAMPLES_MAGIC 0x31535052u
typedef struct {AfEditJointEvalWork pixels;uint8_t groups[AF_REFERENCE_MAP_MAX_PAIRS];} SamplesWork;
struct AfReferenceSamplesState {
    uint32_t magic,phase,busy,total,cursor;
    AfReferenceSamplesConfig config;
    AfReferenceSamplesBuffers buffers;
    SamplesWork *work;
    AfGridProgress progress;void *context;
    uint8_t context_sha256[32],recipe_sha256[32];
};
typedef struct {const void *p;size_t n;} Span;
static int apart(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
static int independent(const Span *s,unsigned n){
    for(unsigned i=0;i<n;++i){
        if(!s[i].p||(uintptr_t)s[i].p>UINTPTR_MAX-s[i].n)return 0;
        for(unsigned j=0;j<i;++j)if(!apart(s[i].p,s[i].n,s[j].p,s[j].n))return 0;
    }
    return 1;
}
static int equal(const uint8_t *a,const uint8_t *b,unsigned n){unsigned d=0;for(unsigned i=0;i<n;++i)d|=a[i]^b[i];return !d;}
static int nonzero(const uint8_t *p){unsigned v=0;for(unsigned i=0;i<32;++i)v|=p[i];return v!=0;}
static float absolute(float v){return v<0?-v:v;}
static void word(uint8_t *p,unsigned *at,uint32_t value){for(unsigned j=0;j<4;++j)p[(*at)++]=(uint8_t)(value>>(8*j));}
static int changed(const AfReferenceSamplesState *s){
    return s->config.baseline->valid!=1||!equal(s->context_sha256,s->config.baseline->source_sha256,32)||
        !equal(s->recipe_sha256,s->config.baseline->recipe_sha256,32);
}
static int notify(AfReferenceSamplesState *s,unsigned done){return s->progress&&s->progress(s->context,done,s->total+1);}
size_t af_reference_samples_state_bytes(void){return sizeof(AfReferenceSamplesState);}
size_t af_reference_samples_work_bytes(void){return sizeof(SamplesWork);}
int af_reference_samples_start(AfReferenceSamplesState *s,const AfReferenceSamplesConfig *c,
    const AfReferenceSamplesBuffers *b,void *work,AfGridProgress progress,void *context){
    if(!s||!c||!b||!c->baseline||c->schema!=1||c->base>=32||!(0x603ffu&(1u<<c->base))||
       c->side<3||c->side>AF_REFERENCE_SAMPLE_MAX_SIDE||c->baseline->valid!=1||
       !nonzero(c->baseline->source_sha256)||!nonzero(c->baseline->recipe_sha256))return AF_INVALID;
    if(s->magic==SAMPLES_MAGIC&&(s->phase==1||s->busy))return AF_BUSY;
    unsigned total=c->side*c->side*c->side+2*AF_REFERENCE_SAMPLE_PROXY_STEPS;
    for(unsigned j=0;j<3;++j)if(!c->native_maximum[j])return AF_INVALID;
    if(b->pair_capacity<6u*total||b->pair_capacity>6u*AF_REFERENCE_MAP_MAX_PAIRS||
       b->output_capacity<24||b->output_capacity>6u*AF_REFERENCE_MAP_MAX_PAIRS||
       b->training_capacity<2||b->training_capacity>AF_JOINT_SAMPLES||
       b->validation_capacity<3||b->validation_capacity>AF_GRID_SAMPLES)return AF_INVALID;
    const Span inputs[]={{s,sizeof(*s)},{c,sizeof(*c)},{b,sizeof(*b)},{work,sizeof(SamplesWork)},
        {c->baseline,sizeof(*c->baseline)},{b->pairs,b->pair_capacity*4},{b->output_values,b->output_capacity*4},
        {b->training,b->training_capacity*sizeof(AfGridSample)},{b->validation,b->validation_capacity*sizeof(AfGridSample)},
        {b->input_map,sizeof(*b->input_map)},{b->output_map,sizeof(*b->output_map)},{b->report,sizeof(*b->report)}};
    if(!independent(inputs,sizeof(inputs)/sizeof(inputs[0])))return AF_INVALID;
    AfReferenceSamplesState next={0};next.magic=SAMPLES_MAGIC;next.phase=1;next.busy=1;
    next.total=total;next.config=*c;next.buffers=*b;next.work=work;next.progress=progress;next.context=context;
    for(unsigned i=0;i<32;++i){next.context_sha256[i]=c->baseline->source_sha256[i];next.recipe_sha256[i]=c->baseline->recipe_sha256[i];}
    *s=next;
    int stopped=notify(s,0);s->busy=0;if(stopped){s->phase=3;return AF_GRID_CANCELLED;}
    return AF_JOINT_MORE;
}
static uint16_t squared(unsigned limit,unsigned index,unsigned last){
    unsigned denominator=last*last;return (uint16_t)((limit*index*index+denominator/2)/denominator);
}
static void native_point(const AfReferenceSamplesState *s,uint16_t rgb[3],uint8_t *group){
    unsigned side=s->config.side,lattice=side*side*side,index=s->cursor;
    if(index<lattice){
        for(unsigned j=0;j<3;++j){rgb[j]=squared(s->config.native_maximum[j],index%side,side-1);index/=side;}
        *group=0;return;
    }
    index-=lattice;unsigned maximum=s->config.native_maximum[0];
    if(index<AF_REFERENCE_SAMPLE_PROXY_STEPS){
        for(unsigned j=1;j<3;++j)if(s->config.native_maximum[j]<maximum)maximum=s->config.native_maximum[j];
        uint16_t v=squared(maximum,index,AF_REFERENCE_SAMPLE_PROXY_STEPS-1);
        for(unsigned j=0;j<3;++j)rgb[j]=v;*group=1;
    }else{
        index-=AF_REFERENCE_SAMPLE_PROXY_STEPS;
        unsigned g=(unsigned)s->config.native_maximum[1]*100/72,b=(unsigned)s->config.native_maximum[2]*100/48;
        if(g<maximum)maximum=g;if(b<maximum)maximum=b;
        unsigned v=squared(maximum,index,AF_REFERENCE_SAMPLE_PROXY_STEPS-1);
        rgb[0]=(uint16_t)v;rgb[1]=(uint16_t)((v*72+50)/100);rgb[2]=(uint16_t)((v*48+50)/100);*group=2;
    }
}
static int compare_source(const float *a,const float *b){
    for(unsigned i=0;i<3;++i){if(a[i]<b[i])return -1;if(a[i]>b[i])return 1;}return 0;
}
static int compare_row(const AfReferenceSamplesState *s,unsigned a,unsigned b){
    const float *x=s->buffers.pairs+a*6,*y=s->buffers.pairs+b*6;
    int result=compare_source(x,y);if(result)return result;
    unsigned ag=s->work->groups[a]?s->work->groups[a]-1:2,bg=s->work->groups[b]?s->work->groups[b]-1:2;
    if(ag<bg)return -1;if(ag>bg)return 1;
    return compare_source(x+3,y+3);
}
static void swap(AfReferenceSamplesState *s,unsigned a,unsigned b){
    for(unsigned j=0;j<6;++j){float t=s->buffers.pairs[a*6+j];s->buffers.pairs[a*6+j]=s->buffers.pairs[b*6+j];s->buffers.pairs[b*6+j]=t;}
    uint8_t t=s->work->groups[a];s->work->groups[a]=s->work->groups[b];s->work->groups[b]=t;
}
static void sift(AfReferenceSamplesState *s,unsigned root,unsigned count){
    for(;;){unsigned child=root*2+1;if(child>=count)return;
        if(child+1<count&&compare_row(s,child,child+1)<0)++child;
        if(compare_row(s,root,child)>=0)return;swap(s,root,child);root=child;
    }
}
static unsigned sorted_unique(AfReferenceSamplesState *s){
    unsigned count=s->total;
    for(unsigned i=count/2;i>0;--i)sift(s,i-1,count);
    for(unsigned i=count;i>1;--i){swap(s,0,i-1);sift(s,0,i-1);}
    unsigned next=0;
    for(unsigned i=0;i<count;++i){
        if(next&&!compare_source(s->buffers.pairs+(next-1)*6,s->buffers.pairs+i*6))continue;
        if(next!=i)for(unsigned j=0;j<6;++j)s->buffers.pairs[next*6+j]=s->buffers.pairs[i*6+j];
        s->work->groups[next++]=s->work->groups[i];
    }
    return next;
}
static unsigned cell(const float *rgb){
    unsigned key=0;for(unsigned j=0;j<3;++j){unsigned v=(unsigned)(rgb[j]*4);key=key*4+(v<4?v:3);}return key;
}
static int unclipped(const float *rgb){for(unsigned j=0;j<3;++j)if(rgb[j]<=.02f||rgb[j]>=.98f)return 0;return 1;}
static void sample(AfGridSample *out,const float *rgb,unsigned group){
    for(unsigned j=0;j<3;++j)out->rgb[j]=rgb[j];out->weight=1;out->group=group;
}
static unsigned bits(uint64_t v){unsigned n=0;while(v){n+=(unsigned)(v&1u);v>>=1;}return n;}
static int publish(AfReferenceSamplesState *s){
    unsigned n=sorted_unique(s),gray=n,warm=n;float gray_cost=4,warm_cost=4;
    uint64_t occupied=0,validation=0;unsigned counts[64]={0};
    for(unsigned i=0;i<n;++i){
        const float *rgb=s->buffers.pairs+i*6;unsigned key=cell(rgb);occupied|=(uint64_t)1<<key;++counts[key];
        if(!unclipped(rgb))continue;
        if(s->work->groups[i]==1){float d=absolute((rgb[0]+rgb[1]+rgb[2])/3-.5f);
            if(d<gray_cost){gray=i;gray_cost=d;}}
        if(s->work->groups[i]==2){float d=absolute(rgb[0]-.65f)+absolute(rgb[1]-.45f)+absolute(rgb[2]-.3f);
            if(d<warm_cost){warm=i;warm_cost=d;}}
    }
    if(gray==n||warm==n)return AF_REFERENCE_SAMPLES_INSUFFICIENT;
    uint64_t mandatory=((uint64_t)1<<cell(s->buffers.pairs+gray*6))|((uint64_t)1<<cell(s->buffers.pairs+warm*6));
    validation=mandatory;
    for(unsigned key=0;key<64;++key)if((occupied&((uint64_t)1<<key))&&(key*37u+11u)%4u==0)
        validation|=(uint64_t)1<<key;
    /* 可选区域不能吃光训练集；代理所在区域始终留在验证。 */
    if(!(occupied&~validation))validation=mandatory;
    unsigned nt=0,nv=0;
    for(unsigned key=0;key<64;++key)if(validation&((uint64_t)1<<key))nv+=counts[key];else nt+=counts[key];
    if(nt<2||nv<3)return AF_REFERENCE_SAMPLES_INSUFFICIENT;
    unsigned train=nt<s->buffers.training_capacity?nt:(unsigned)s->buffers.training_capacity;
    unsigned valid=nv<s->buffers.validation_capacity?nv:(unsigned)s->buffers.validation_capacity;
    sample(s->buffers.validation,s->buffers.pairs+gray*6,1);
    sample(s->buffers.validation+1,s->buffers.pairs+warm*6,2);
    unsigned trank=0,vrank=0,ti=0,vi=0;
    for(unsigned i=0;i<n;++i){
        const float *rgb=s->buffers.pairs+i*6;uint64_t bit=(uint64_t)1<<cell(rgb);
        if(validation&bit){
            if(i==gray||i==warm)continue;
            if(vi<valid-2&&vrank==vi*(nv-2)/(valid-2)){sample(s->buffers.validation+vi+2,rgb,s->work->groups[i]);++vi;}
            ++vrank;
        }else{
            if(ti<train&&trank==ti*nt/train){sample(s->buffers.training+ti,rgb,s->work->groups[i]);++ti;}
            ++trank;
        }
    }
    if(ti!=train||vi!=valid-2)return AF_INVALID;
    for(unsigned i=0;i<8;++i){s->buffers.output_values[i*3]=(float)(i&1u);
        s->buffers.output_values[i*3+1]=(float)((i>>1)&1u);s->buffers.output_values[i*3+2]=(float)((i>>2)&1u);}
    AfReferenceMap input={0},output={0};AfReferenceSamplesReport report={0};
    input.schema=2;input.input_domain=AF_REFERENCE_SRGB;input.output_domain=AF_REFERENCE_EDIT_INPUT;
    input.base=s->config.base;input.values=s->buffers.pairs;input.count=n*6;
    output.schema=1;output.input_domain=AF_REFERENCE_EDIT_OUTPUT;output.output_domain=AF_REFERENCE_SRGB;
    output.dimension=2;output.base=s->config.base;output.values=s->buffers.output_values;output.count=24;
    for(unsigned j=0;j<3;++j){input.maximum[j]=1;output.maximum[j]=16383;}
    if(af_sha256(input.values,input.count*4,input.data_sha256)||af_sha256(output.values,96,output.data_sha256))return AF_INVALID;
    uint8_t origin[256]={0};unsigned at=0;static const char algorithm[]="A7R5-forward-reachable-samples-v1";
    for(unsigned i=0;i<sizeof(algorithm)-1;++i)origin[at++]=(uint8_t)algorithm[i];
    for(unsigned i=0;i<32;++i)origin[at++]=s->context_sha256[i];
    for(unsigned i=0;i<32;++i)origin[at++]=s->recipe_sha256[i];
    for(unsigned i=0;i<32;++i)origin[at++]=af_reference_domain_policy_sha256[i];
    word(origin,&at,s->config.base);word(origin,&at,s->config.side);
    for(unsigned i=0;i<3;++i)word(origin,&at,s->config.native_maximum[i]);
    word(origin,&at,65);word(origin,&at,72);word(origin,&at,48);word(origin,&at,4);word(origin,&at,37);word(origin,&at,11);
    for(unsigned i=0;i<32;++i)origin[at++]=input.data_sha256[i];
    if(af_sha256(origin,at,input.source_sha256))return AF_INVALID;
    for(unsigned i=0;i<32;++i){
        input.context_sha256[i]=output.context_sha256[i]=report.context_sha256[i]=s->context_sha256[i];
        output.source_sha256[i]=report.source_sha256[i]=input.source_sha256[i];
        report.recipe_sha256[i]=s->recipe_sha256[i];report.policy_sha256[i]=af_reference_domain_policy_sha256[i];
    }
    report.evaluations=s->total;report.unique=n;report.duplicates=s->total-n;
    report.training=train;report.validation=valid;report.occupied_cells=bits(occupied);
    report.research_only=1;report.camera_apply_allowed=0;
    for(unsigned i=0;i<train;++i)report.training_cells|=(uint64_t)1<<cell(s->buffers.training[i].rgb);
    for(unsigned i=0;i<valid;++i){if(s->buffers.validation[i].group&1u)++report.gray_validation;
        if(s->buffers.validation[i].group&2u)++report.warm_validation;
        report.validation_cells|=(uint64_t)1<<cell(s->buffers.validation[i].rgb);}
    if(changed(s))return AF_STALE;
    if(notify(s,s->total+1))return AF_GRID_CANCELLED;
    if(changed(s))return AF_STALE;
    *s->buffers.input_map=input;*s->buffers.output_map=output;*s->buffers.report=report;
    return AF_OK;
}
int af_reference_samples_step(AfReferenceSamplesState *s,uint32_t budget){
    if(!s||s->magic!=SAMPLES_MAGIC||!budget||budget>64)return AF_INVALID;
    if(s->busy)return AF_BUSY;if(s->phase!=1)return AF_STALE;
    s->busy=1;int result=AF_JOINT_MORE;
    if(changed(s)){result=AF_STALE;goto done;}
    if(notify(s,s->cursor)){result=AF_GRID_CANCELLED;goto done;}
    for(unsigned i=0;i<budget&&s->cursor<s->total;++i){
        uint16_t native[3],rgb[3];uint8_t group;native_point(s,native,&group);
        result=af_edit_joint_eval(s->config.baseline,native,&s->work->pixels,rgb);
        if(result!=AF_OK)goto done;
        for(unsigned j=0;j<3;++j){
            if(rgb[j]>16383){result=AF_INVALID;goto done;}
            s->buffers.pairs[s->cursor*6+j]=(float)rgb[j]/16383.0f;
            s->buffers.pairs[s->cursor*6+3+j]=(float)native[j];
        }
        s->work->groups[s->cursor]=group;++s->cursor;
        if(notify(s,s->cursor)){result=AF_GRID_CANCELLED;goto done;}
    }
    result=s->cursor==s->total?publish(s):AF_JOINT_MORE;
done:
    s->busy=0;if(result==AF_OK)s->phase=2;else if(result!=AF_JOINT_MORE)s->phase=3;
    return result;
}
