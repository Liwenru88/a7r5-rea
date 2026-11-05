#include "af_reference_joint.h"
#include "af_sha256.h"
#include <float.h>
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "Reference table hashes require a little-endian target"
#endif
_Static_assert(sizeof(float)==4,"Reference float table width");
#define REFERENCE_MAGIC 0x31524a41u
typedef struct {
    AfEditJointWork build;
    AfEditJointEvalWork pixels;
    AfJointRecipe native;
} ReferenceWork;
struct AfReferenceJoint {
    uint32_t magic,busy;
    AfReferenceJointInfo info;
    AfReferenceMap input_map,output_map;
    AfGridModel grid;
    const AfEditJointInput *edit;
    const AfEditJointCache *baseline;
    AfEditJointCache *candidate;
    ReferenceWork *work;
    AfJointRecipe seed,current;
    uint32_t matrix_mode;
    int16_t current_sector[288];
};
typedef struct {const void *p;size_t n;} Span;
static int finite(float f){return f==f&&f>=-FLT_MAX&&f<=FLT_MAX;}
static int apart(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
static int separate(const Span *s,unsigned count){
    for(unsigned i=0;i<count;++i){
        if(!s[i].p||(uintptr_t)s[i].p>UINTPTR_MAX-s[i].n)return 0;
        for(unsigned j=0;j<i;++j)if(!apart(s[i].p,s[i].n,s[j].p,s[j].n))return 0;
    }
    return 1;
}
static int equal(const uint8_t *a,const uint8_t *b,size_t n){
    unsigned difference=0;for(size_t i=0;i<n;++i)difference|=a[i]^b[i];return !difference;
}
static int nonzero(const uint8_t *a){unsigned any=0;for(unsigned i=0;i<32;++i)any|=a[i];return any!=0;}
static int base_valid(uint32_t base){return base<32&&(0x603ffu&(1u<<base));}
static int grid_valid(const AfReferenceJointConfig *c){
    const AfGridModel *m=c->grid;
    static const uint8_t paired[32]={0x88,0x79,0x49,0x9f,0xbd,0x9b,0x24,0x89,
        0x9d,0xcb,0xd8,0xfe,0xe4,0x13,0x5b,0x80,0x6f,0xdc,0xba,0x1f,0xd1,0x8a,0x67,0x7b,
        0x09,0x0b,0x7a,0xf2,0x12,0xb8,0x5a,0x45};
    if(!m||m->schema!=1||m->smooth>1||!nonzero(m->sha256))return 0;
    for(unsigned i=0;i<12;++i)if(!finite(m->coordinates[i])||m->coordinates[i]<-16||m->coordinates[i]>16)return 0;
    for(unsigned i=0;i<36;++i)if(!finite(m->response[i])||m->response[i]<-16||m->response[i]>16)return 0;
    /* 研究路径原样保留公开源摘要及PT条件，不更名伪装成已准入模型。
     * 原af_grid_model_valid仍拒绝该原摘要；这里不调用或改变设备入口。 */
    if(equal(m->sha256,paired,32))return equal(c->grid_source_sha256,paired,32)&&
        c->grid_base==1&&(m->base_mask==0||m->base_mask==2);
    return af_grid_model_valid(m)==AF_OK&&(m->base_mask&(1u<<c->grid_base));
}
static int grid_predict(const AfGridModel *m,const int8_t *grid,const float rgb[3],float output[3]){
    unsigned low[3];float fraction[3],delta[3]={0},result[3];
    for(unsigned c=0;c<3;++c){
        if(!finite(rgb[c])||rgb[c]<0||rgb[c]>1)return AF_INVALID;
        float value=m->coordinates[c*4+3];
        for(unsigned j=0;j<3;++j)value+=rgb[j]*m->coordinates[c*4+j];
        unsigned maximum=c?8u:4u;
        value=value*(float)maximum+(c?4.0f:0.0f);
        value=value<0?0:value>(float)maximum?(float)maximum:value;
        low[c]=(unsigned)value;if(low[c]>=maximum)--low[c];
        fraction[c]=value-(float)low[c];
    }
    for(unsigned y=0;y<2;++y)for(unsigned u=0;u<2;++u)for(unsigned v=0;v<2;++v){
        unsigned index=(low[0]+y)*81+(low[1]+u)*9+low[2]+v;
        float weight=(y?fraction[0]:1-fraction[0])*(u?fraction[1]:1-fraction[1])*(v?fraction[2]:1-fraction[2]);
        for(unsigned c=0;c<3;++c)delta[c]+=weight*grid[c*AF_GRID_NODES+index];
    }
    for(unsigned o=0;o<3;++o){
        float value=rgb[o];
        for(unsigned c=0;c<3;++c){
            float response=m->response[c*3+o];
            if(m->smooth)for(unsigned j=0;j<3;++j)response+=(rgb[j]-.5f)*m->response[(3+3*c+j)*3+o];
            value+=delta[c]*(response/256.0f);
        }
        result[o]=value<0?0:value>1?1:value;
    }
    for(unsigned c=0;c<3;++c)output[c]=result[c];return AF_OK;
}
static int map_valid(const AfReferenceMap *m){
    if(!m||(m->schema!=1&&m->schema!=2)||!base_valid(m->base)||!m->values||
       !nonzero(m->source_sha256)||!nonzero(m->context_sha256)||!nonzero(m->data_sha256))return 0;
    if(m->schema==1){
        if(m->dimension<2||m->dimension>AF_REFERENCE_MAP_MAX_DIMENSION||
           m->count!=(size_t)m->dimension*m->dimension*m->dimension*3u)return 0;
    }else if(m->dimension||m->input_domain!=AF_REFERENCE_SRGB||m->output_domain!=AF_REFERENCE_EDIT_INPUT||
        m->count<6||m->count%6||m->count>AF_REFERENCE_MAP_MAX_PAIRS*6u)return 0;
    if(!((m->input_domain==AF_REFERENCE_SRGB&&m->output_domain==AF_REFERENCE_EDIT_INPUT)||
         (m->input_domain==AF_REFERENCE_EDIT_OUTPUT&&m->output_domain==AF_REFERENCE_SRGB)))return 0;
    float input_max=m->input_domain==AF_REFERENCE_SRGB?1.0f:65535.0f;
    float output_max=m->output_domain==AF_REFERENCE_SRGB?1.0f:65535.0f;
    for(unsigned i=0;i<3;++i)if(!finite(m->minimum[i])||!finite(m->maximum[i])||
       m->minimum[i]<0||m->maximum[i]>input_max||m->minimum[i]>=m->maximum[i])return 0;
    if(m->schema==1){
        for(size_t i=0;i<m->count;++i)if(!finite(m->values[i])||m->values[i]<0||m->values[i]>output_max)return 0;
    }else for(size_t i=0;i<m->count;i+=6){
        for(unsigned c=0;c<3;++c){
            float rgb=m->values[i+c],native=m->values[i+3+c];
            if(!finite(rgb)||rgb<m->minimum[c]||rgb>m->maximum[c]||
               !finite(native)||native<0||native>65535||(float)(uint16_t)native!=native)return 0;
        }
        if(i){
            int order=0;
            for(unsigned c=0;c<3&&!order;++c){
                if(m->values[i+c]<m->values[i-6+c])order=-1;
                if(m->values[i+c]>m->values[i-6+c])order=1;
            }
            if(order!=1)return 0;
        }
    }
    uint8_t hash[32];
    return !af_sha256(m->values,m->count*sizeof(float),hash)&&equal(hash,m->data_sha256,32);
}
static int lookup(const AfReferenceMap *m,const float input[3],float output[3]){
    if(m->schema==2){
        for(unsigned c=0;c<3;++c){
            if(!finite(input[c]))return AF_INVALID;
            if(input[c]<m->minimum[c]||input[c]>m->maximum[c])return AF_JOINT_SKIP;
        }
        size_t low=0,high=m->count/6;
        while(low<high){
            size_t middle=low+(high-low)/2;const float *row=m->values+middle*6;int order=0;
            for(unsigned c=0;c<3&&!order;++c){if(input[c]<row[c])order=-1;if(input[c]>row[c])order=1;}
            if(order<0)high=middle;
            else if(order>0)low=middle+1;
            else{for(unsigned c=0;c<3;++c)output[c]=row[3+c];return AF_OK;}
        }
        return AF_JOINT_SKIP;
    }
    unsigned low[3],n=m->dimension;float fraction[3],result[3]={0};
    for(unsigned c=0;c<3;++c){
        if(!finite(input[c]))return AF_INVALID;
        if(input[c]<m->minimum[c]||input[c]>m->maximum[c])return AF_JOINT_SKIP;
        float at=(input[c]-m->minimum[c])/(m->maximum[c]-m->minimum[c])*(float)(n-1);
        low[c]=(unsigned)at;if(low[c]>=n-1)low[c]=n-2;
        fraction[c]=at-(float)low[c];
    }
    for(unsigned z=0;z<2;++z)for(unsigned y=0;y<2;++y)for(unsigned x=0;x<2;++x){
        float weight=(x?fraction[0]:1-fraction[0])*(y?fraction[1]:1-fraction[1])*(z?fraction[2]:1-fraction[2]);
        size_t at=(((size_t)(low[2]+z)*n+low[1]+y)*n+low[0]+x)*3u;
        for(unsigned c=0;c<3;++c)result[c]+=weight*m->values[at+c];
    }
    for(unsigned c=0;c<3;++c)output[c]=result[c];return AF_OK;
}
int af_reference_map_eval(const AfReferenceMap *m,const float *input,float *output){
    if(!map_valid(m)||!apart(input,12,output,12)||!apart(m,sizeof(*m),output,12)||
       !apart(m->values,m->count*sizeof(float),output,12))return AF_INVALID;
    return lookup(m,input,output);
}
static void word(uint8_t *data,unsigned *at,uint32_t value){
    for(unsigned i=0;i<4;++i)data[(*at)++]=(uint8_t)(value>>(8*i));
}
static void half(uint8_t *data,unsigned *at,uint16_t value){
    data[(*at)++]=(uint8_t)value;data[(*at)++]=(uint8_t)(value>>8);
}
static int recipe_hash(const AfJointRecipe *r,uint8_t hash[32]){
    uint8_t data[1815];unsigned at=0;
    for(unsigned i=0;i<129;++i)word(data,&at,r->gamma[i]);
    for(unsigned i=0;i<18;++i)half(data,&at,(uint16_t)r->matrix[i]);
    for(unsigned i=0;i<24;++i)half(data,&at,(uint16_t)r->cc1[i]);
    for(unsigned i=0;i<AF_GRID_BYTES;++i)data[at++]=(uint8_t)r->grid[i];
    return af_sha256(data,at,hash);
}
static int same_recipe(const AfJointRecipe *a,const AfJointRecipe *b){
    for(unsigned i=0;i<129;++i)if(a->gamma[i]!=b->gamma[i])return 0;
    for(unsigned i=0;i<18;++i)if(a->matrix[i]!=b->matrix[i])return 0;
    for(unsigned i=0;i<24;++i)if(a->cc1[i]!=b->cc1[i])return 0;
    for(unsigned i=0;i<AF_GRID_BYTES;++i)if(a->grid[i]!=b->grid[i])return 0;
    return 1;
}
static int source_valid(const AfReferenceJointConfig *c){
    if(!c||c->schema!=1||(c->flags&7u)!=7u||(c->flags&~15u)||!base_valid(c->base)||
       !base_valid(c->grid_base)||!c->edit||!c->seed||!c->baseline||!c->input_map||!c->output_map||!c->grid||
       !equal(c->target_cp_sha256,af_joint_cp_sha256,32)||!nonzero(c->grid_source_sha256)||
       c->baseline->valid!=1||!equal(c->edit_source_sha256,c->baseline->source_sha256,32)||
       af_joint_valid(c->seed)!=AF_OK||!grid_valid(c)||
       (c->base!=c->grid_base&&!(c->flags&AF_REFERENCE_CROSS_BASE_GRID)))return 0;
    AfPreset preset={0};preset.base=(uint8_t)c->base;
    for(unsigned i=0;i<8;++i)preset.params[i]=c->reference_params[i];
    if(af_validate(&preset)!=AF_OK)return 0;
    for(unsigned i=0;i<AF_GRID_BYTES;++i)if(c->seed->grid[i])return 0;
    if(!map_valid(c->input_map)||!map_valid(c->output_map)||
       c->input_map->input_domain!=AF_REFERENCE_SRGB||c->output_map->input_domain!=AF_REFERENCE_EDIT_OUTPUT||
       c->input_map->base!=c->base||c->output_map->base!=c->base||
       !equal(c->input_map->context_sha256,c->edit_source_sha256,32)||
       !equal(c->output_map->context_sha256,c->edit_source_sha256,32))return 0;
    uint8_t hash[32];return !recipe_hash(c->seed,hash)&&equal(hash,c->baseline->recipe_sha256,32);
}
static int source_apart(const AfEditJointInput *i,const void *output,size_t bytes){
    if(!i||!i->edit||!i->edit->baseline)return 0;
    const AfEditContextInput *e=i->edit;const AfEditRefChain *b=e->baseline;
    if(b->main_entries!=65536||b->y_entries!=32768||b->matrix.table_entries!=18432||
       b->matrix.angle_entries!=512||e->secondary_inverse_entries!=16384||e->secondary_entries!=65536)return 0;
    const Span spans[]={{i,sizeof(*i)},{e,sizeof(*e)},{b,sizeof(*b)},
        {i->cp_gamma_record,576},{i->matrix_raw,576},{i->cc1_raw,48},
        {e->axis,512},{e->gamma_y,512},{e->contrast,4100},{e->matrix_payload,276},{e->cc1,16},
        {e->matrix_domain,sizeof(*e->matrix_domain)},{e->chroma_source,sizeof(*e->chroma_source)},
        {e->secondary_inverse,32768},{e->secondary_gamma,131072},
        {b->matrix.table,73728},{b->matrix.angles,2048},{b->main_gamma,131072},{b->y_gamma,65536}};
    for(unsigned j=0;j<sizeof(spans)/sizeof(spans[0]);++j)
        if(!apart(spans[j].p,spans[j].n,output,bytes))return 0;
    return 1;
}
static void copy32(uint8_t *out,const uint8_t *in){for(unsigned i=0;i<32;++i)out[i]=in[i];}
static int identity(const AfReferenceJointConfig *c,AfReferenceJointInfo *info){
    uint8_t data[1024],hash[32];unsigned at=0;
    word(data,&at,0x31524a41u);word(data,&at,c->flags);word(data,&at,c->base);word(data,&at,c->grid_base);
    for(unsigned i=0;i<8;++i)data[at++]=(uint8_t)c->reference_params[i];
    const uint8_t *parts[]={c->target_cp_sha256,c->edit_source_sha256,c->grid_source_sha256,
        c->input_map->source_sha256,c->input_map->data_sha256,
        c->output_map->source_sha256,c->output_map->data_sha256,c->grid->sha256};
    for(unsigned j=0;j<8;++j)for(unsigned i=0;i<32;++i)data[at++]=parts[j][i];
    const AfReferenceMap *maps[]={c->input_map,c->output_map};
    for(unsigned j=0;j<2;++j){
        word(data,&at,maps[j]->schema);word(data,&at,(uint32_t)maps[j]->count);
        word(data,&at,maps[j]->dimension);word(data,&at,maps[j]->input_domain);word(data,&at,maps[j]->output_domain);
        for(unsigned i=0;i<3;++i){
            union{float f;uint32_t u;} low={.f=maps[j]->minimum[i]},high={.f=maps[j]->maximum[i]};
            word(data,&at,low.u);word(data,&at,high.u);
        }
    }
    word(data,&at,c->grid->schema);word(data,&at,c->grid->base_mask);word(data,&at,c->grid->smooth);
    for(unsigned i=0;i<48;++i){
        union{float f;uint32_t u;} value={.f=i<12?c->grid->coordinates[i]:c->grid->response[i-12]};
        word(data,&at,value.u);
    }
    if(recipe_hash(c->seed,hash))return AF_INVALID;
    for(unsigned i=0;i<32;++i)data[at++]=hash[i];
    *info=(AfReferenceJointInfo){.schema=1,.flags=c->flags,.base=c->base,.grid_base=c->grid_base,.research_only=1};
    for(unsigned i=0;i<8;++i)info->reference_params[i]=c->reference_params[i];
    copy32(info->target_cp_sha256,c->target_cp_sha256);copy32(info->edit_source_sha256,c->edit_source_sha256);
    copy32(info->grid_source_sha256,c->grid_source_sha256);copy32(info->input_map_sha256,c->input_map->data_sha256);
    copy32(info->output_map_sha256,c->output_map->data_sha256);
    return af_sha256(data,at,info->model_sha256)?AF_INVALID:AF_OK;
}
size_t af_reference_joint_state_bytes(void){return sizeof(AfReferenceJoint);}
size_t af_reference_joint_work_bytes(void){return sizeof(ReferenceWork);}
int af_reference_joint_init(AfReferenceJoint *s,const AfReferenceJointConfig *c,void *work,
                           AfEditJointCache *candidate,AfGridProgress callback,void *context){
    if(!s||((uintptr_t)s%_Alignof(AfReferenceJoint))||!work||
       ((uintptr_t)work%_Alignof(ReferenceWork))||!candidate)return AF_INVALID;
    if(s->magic==REFERENCE_MAGIC)return AF_BUSY;
    if(s->magic||!source_valid(c))return AF_INVALID;
    const Span spans[]={{s,sizeof(*s)},{c,sizeof(*c)},{work,sizeof(ReferenceWork)},
        {candidate,sizeof(*candidate)},{c->baseline,sizeof(*c->baseline)},
        {c->edit,sizeof(*c->edit)},{c->seed,sizeof(*c->seed)},
        {c->input_map,sizeof(*c->input_map)},{c->output_map,sizeof(*c->output_map)},
        {c->grid,sizeof(*c->grid)},{c->input_map->values,c->input_map->count*sizeof(float)},
        {c->output_map->values,c->output_map->count*sizeof(float)}};
    if(!separate(spans,sizeof(spans)/sizeof(spans[0])))return AF_INVALID;
    if(!source_apart(c->edit,s,sizeof(*s))||!source_apart(c->edit,work,sizeof(ReferenceWork))||
       !source_apart(c->edit,candidate,sizeof(*candidate)))return AF_INVALID;
    AfReferenceJointInfo info;
    if(identity(c,&info)!=AF_OK)return AF_INVALID;
    ReferenceWork *w=work;
    int result=af_edit_joint_prepare(c->edit,c->seed,&w->build,candidate,callback,context);
    if(result!=AF_OK)return result;
    if(!equal(candidate->source_sha256,c->edit_source_sha256,32))return AF_STALE;
    /* 全部可能失败的操作先完成，再原地发布，避免在原UI栈复制两份配方。 */
    s->info=info;s->input_map=*c->input_map;s->output_map=*c->output_map;s->grid=*c->grid;
    s->edit=c->edit;s->baseline=c->baseline;s->candidate=candidate;s->work=w;
    s->seed=*c->seed;s->current=*c->seed;s->matrix_mode=0;
    for(unsigned i=0;i<288;++i)s->current_sector[i]=0;
    s->busy=0;s->magic=REFERENCE_MAGIC;return AF_OK;
}
static int active(const AfReferenceJoint *s){
    return s&&s->magic==REFERENCE_MAGIC&&s->info.research_only==1&&!s->info.camera_apply_allowed&&
        s->baseline&&s->baseline->valid==1&&s->candidate&&s->candidate->valid==1&&s->work&&
        equal(s->baseline->source_sha256,s->info.edit_source_sha256,32)&&
        equal(s->candidate->source_sha256,s->info.edit_source_sha256,32);
}
static int output_apart(const AfReferenceJoint *s,const void *output,size_t bytes){
    return apart(output,bytes,s,sizeof(*s))&&apart(output,bytes,s->work,sizeof(*s->work))&&
        apart(output,bytes,s->baseline,sizeof(*s->baseline))&&
        apart(output,bytes,s->candidate,sizeof(*s->candidate))&&
        apart(output,bytes,s->input_map.values,s->input_map.count*sizeof(float))&&
        apart(output,bytes,s->output_map.values,s->output_map.count*sizeof(float))&&
        source_apart(s->edit,output,bytes);
}
static int sector_apart(const AfReferenceJoint *s,const int16_t *sector_matrix){
    return !sector_matrix||(apart(sector_matrix,576,s,sizeof(*s))&&
        apart(sector_matrix,576,s->work,sizeof(*s->work))&&
        apart(sector_matrix,576,s->candidate,sizeof(*s->candidate))&&
        apart(sector_matrix,576,s->baseline,sizeof(*s->baseline)));
}
static int same_sector(const int16_t *a,const int16_t *b){
    for(unsigned i=0;i<288;++i)if(a[i]!=b[i])return 0;
    return 1;
}
static int prepare(AfReferenceJoint *s,const AfJointRecipe *r,const int16_t *sector_matrix,
                    AfGridProgress callback,void *context){
    if(!active(s)||af_joint_valid(r)!=AF_OK||!apart(r,sizeof(*r),s,sizeof(*s))||
       !apart(r,sizeof(*r),s->work,sizeof(*s->work))||
       !apart(r,sizeof(*r),s->candidate,sizeof(*s->candidate))||!sector_apart(s,sector_matrix))return AF_INVALID;
    s->work->native=*r;
    for(unsigned i=0;i<AF_GRID_BYTES;++i)s->work->native.grid[i]=0;
    int result=sector_matrix?af_edit_joint_prepare_sector(s->edit,&s->work->native,sector_matrix,
        &s->work->build,s->candidate,callback,context):
        af_edit_joint_prepare(s->edit,&s->work->native,&s->work->build,s->candidate,callback,context);
    if(result!=AF_OK)return result;
    s->current=*r;s->matrix_mode=sector_matrix?1u:0u;
    for(unsigned i=0;i<288;++i)s->current_sector[i]=sector_matrix?sector_matrix[i]:0;
    return AF_OK;
}
int af_reference_joint_prepare(AfReferenceJoint *s,const AfJointRecipe *r,AfGridProgress callback,void *context){
    if(!active(s))return AF_INVALID;
    if(s->busy)return AF_BUSY;
    s->busy=1;int result=prepare(s,r,0,callback,context);s->busy=0;return result;
}
int af_reference_joint_prepare_sector(AfReferenceJoint *s,const AfJointRecipe *r,
    const int16_t *sector_matrix,AfGridProgress callback,void *context){
    if(!active(s)||!sector_matrix)return AF_INVALID;
    if(s->busy)return AF_BUSY;
    s->busy=1;int result=prepare(s,r,sector_matrix,callback,context);s->busy=0;return result;
}
static int predict(AfReferenceJoint *s,const AfJointRecipe *r,const int16_t *sector_matrix,
                   const float *input,float *output){
    if(!active(s)||!r||!apart(input,12,output,12)||!apart(output,12,r,sizeof(*r))||
       !output_apart(s,output,12)||!sector_apart(s,sector_matrix)||
       (sector_matrix&&!apart(sector_matrix,576,output,12)))return AF_INVALID;
    for(unsigned c=0;c<3;++c)if(!finite(input[c])||input[c]<0||input[c]>1)return AF_INVALID;
    if(s->busy)return AF_BUSY;
    s->busy=1;int result=AF_OK;
    if(s->matrix_mode!=(sector_matrix?1u:0u)||!same_recipe(r,&s->current)||
       (sector_matrix&&!same_sector(sector_matrix,s->current_sector))){
        result=prepare(s,r,sector_matrix,0,0);if(result!=AF_OK)goto done;
    }
    float native[3],old_rgb[3],new_rgb[3],anchored[3],predicted[3];
    uint16_t pixel[3],old_code[3],new_code[3];
    result=lookup(&s->input_map,input,native);if(result!=AF_OK)goto done;
    for(unsigned c=0;c<3;++c)pixel[c]=(uint16_t)(native[c]+.5f);
    result=af_edit_joint_eval(s->baseline,pixel,&s->work->pixels,old_code);if(result!=AF_OK)goto done;
    result=af_edit_joint_eval(s->candidate,pixel,&s->work->pixels,new_code);if(result!=AF_OK)goto done;
    for(unsigned c=0;c<3;++c)native[c]=(float)old_code[c];
    result=lookup(&s->output_map,native,old_rgb);if(result!=AF_OK)goto done;
    for(unsigned c=0;c<3;++c)native[c]=(float)new_code[c];
    result=lookup(&s->output_map,native,new_rgb);if(result!=AF_OK)goto done;
    for(unsigned c=0;c<3;++c){float value=input[c]+new_rgb[c]-old_rgb[c];anchored[c]=value<0?0:value>1?1:value;}
    result=grid_predict(&s->grid,r->grid,anchored,predicted);if(result!=AF_OK)goto done;
    for(unsigned c=0;c<3;++c)output[c]=predicted[c];
done:
    s->busy=0;return result;
}
int af_reference_joint_predict(void *opaque,const AfJointRecipe *r,const float *input,float *output){
    return predict(opaque,r,0,input,output);
}
int af_reference_joint_predict_sector(AfReferenceJoint *s,const AfJointRecipe *r,
    const int16_t *sector_matrix,const float *input,float *output){
    return sector_matrix?predict(s,r,sector_matrix,input,output):AF_INVALID;
}
int af_reference_joint_info(const AfReferenceJoint *s,AfReferenceJointInfo *output){
    if(!active(s)||!output_apart(s,output,sizeof(*output)))return AF_INVALID;
    *output=s->info;return AF_OK;
}
int af_reference_joint_info_sector(const AfReferenceJoint *s,AfReferenceJointInfo *output){
    if(!active(s)||!output_apart(s,output,sizeof(*output)))return AF_INVALID;
    static const char tag[]="A7R5_REFERENCE_SECTOR_MATRIX406_V1";
    uint8_t data[sizeof(tag)+32];
    for(unsigned i=0;i<sizeof(tag);++i)data[i]=(uint8_t)tag[i];
    for(unsigned i=0;i<32;++i)data[sizeof(tag)+i]=s->info.model_sha256[i];
    AfReferenceJointInfo next=s->info;
    if(af_sha256(data,sizeof(data),next.model_sha256))return AF_INVALID;
    *output=next;return AF_OK;
}
int af_reference_joint_model(AfReferenceJoint *s,const AfPreset *preset,AfJointModel *output){
    if(!active(s)||!preset||af_validate(preset)!=AF_OK||preset->kind||preset->base!=s->info.base||
       !apart(preset,sizeof(*preset),output,sizeof(*output))||!output_apart(s,output,sizeof(*output)))return AF_INVALID;
    if(s->busy)return AF_BUSY;
    for(unsigned i=0;i<8;++i)if(preset->params[i]!=s->info.reference_params[i])return AF_STALE;
    AfJointModel model={.schema=1,.base_mask=1u<<s->info.base,.components=AF_JOINT_COMPONENTS,
        .domain=1,.predict=af_reference_joint_predict,.context=s};
    copy32(model.cp_sha256,s->info.target_cp_sha256);copy32(model.model_sha256,s->info.model_sha256);
    *output=model;return AF_OK;
}
