#include "af_edit_joint.h"
#include "af_color406.h"
#include "af_sha256.h"
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "Fixed Edit reference inputs require a little-endian target"
#endif
_Static_assert(sizeof(AfEditJointCache)<=512u*1024u,"Edit joint cache budget");
_Static_assert(sizeof(AfEditJointWork)<=768u*1024u,"Edit joint work budget");
_Static_assert(sizeof(AfEditJointEvalWork)<=64u*1024u,"Edit joint pixel work budget");
typedef struct {const void *p;size_t n;} Span;
typedef struct {AfGridProgress callback;void *context;} Progress;
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static int equal(const uint8_t *a,const uint8_t *b,size_t n) {
    unsigned delta=0;for (size_t j=0;j<n;++j) delta|=a[j]^b[j];return !delta;
}
static void put16(uint8_t *p,uint16_t value) {p[0]=(uint8_t)value;p[1]=(uint8_t)(value>>8);}
static void word(uint8_t *p,unsigned *n,uint32_t value) {
    for (unsigned j=0;j<4;++j) p[(*n)++]=(uint8_t)(value>>(8*j));
}
static void real(uint8_t *p,unsigned *n,float value) {
    union {float f;uint32_t u;} bits;bits.f=value;word(p,n,bits.u);
}
static int fixed(const void *p,size_t bytes,const char *hex) {
    uint8_t digest[32];if (!p || af_sha256(p,bytes,digest)) return 0;
    for (unsigned j=0;j<32;++j) {
        unsigned a=(unsigned)(hex[2*j]<='9'?hex[2*j]-'0':hex[2*j]-'a'+10);
        unsigned b=(unsigned)(hex[2*j+1]<='9'?hex[2*j+1]-'0':hex[2*j+1]-'a'+10);
        if (digest[j]!=(uint8_t)(a*16+b)) return 0;
    }
    return 1;
}
static int recipe_valid(const AfJointRecipe *r) {
    if (af_joint_valid(r)!=AF_OK) return AF_INVALID;
    for (unsigned j=0;j<AF_GRID_BYTES;++j) if (r->grid[j]) return AF_JOINT_SKIP;
    return AF_OK;
}
static int sector_valid(const AfJointRecipe *r,const int16_t *sector_matrix){
    if(!sector_matrix)return AF_OK;
    for(unsigned j=0;j<18;++j)if(r->matrix[j])return AF_INVALID;
    for(unsigned j=0;j<288;++j)if(sector_matrix[j]<-1024||sector_matrix[j]>1024)return AF_INVALID;
    return AF_OK;
}
static int parameters(const AfEditJointInput *i,const AfJointRecipe *r,
                      const int16_t *sector_matrix,AfEditJointParameters *out) {
    if (!apart(i,sizeof(*i),out,sizeof(*out)) || !apart(r,sizeof(*r),out,sizeof(*out)) || !i->edit ||
        !apart(i->edit,sizeof(*i->edit),out,sizeof(*out))) return AF_INVALID;
    if(sector_matrix&&!apart(sector_matrix,576,out,sizeof(*out)))return AF_INVALID;
    const Span sources[]={{i->cp_gamma_record,576},{i->matrix_raw,576},{i->cc1_raw,48},
                          {i->edit->matrix_payload,276}};
    for (unsigned j=0;j<4;++j) if (!apart(sources[j].p,sources[j].n,out,sizeof(*out))) return AF_INVALID;
    int result=recipe_valid(r);if (result!=AF_OK) return result;
    if(sector_valid(r,sector_matrix)!=AF_OK)return AF_INVALID;
    if (!fixed(i->matrix_raw,576,"8e1389747320727fa862211de0864b8bf2d919beba30067c0fc35570440273bf") ||
        !fixed(i->cc1_raw,48,"17948b0016048d0405910e86f78696b0dc6ba4466c0b6d119b0903873709fa30") ||
        !fixed(i->edit->matrix_payload,276,"9a3811fea413b06b23d0dbd25cdd99b8901b869a475464a124fdcdd48d23f5ab")) return AF_INVALID;
    AfEditJointParameters next;
    result=af_edit_cp_gamma(i->cp_gamma_record,576,r->gamma,129,&next.gamma,0,0);
    if (result!=AF_OK) return result;
    int16_t cc_base[24],cc_added[24],selected[8],zero[8]={0};
    if (af_color406_primary(i->cc1_raw,zero,cc_base)!=AF_OK ||
        af_color406_add(cc_base,r->cc1,24,cc_added)!=AF_OK ||
        af_color406_blend(cc_added,i->cc1_weights,selected)!=AF_OK) return AF_INVALID;
    static const uint8_t order[8]={3,0,1,2,7,4,5,6};
    for (unsigned j=0;j<8;++j) {
        int32_t value=selected[order[j]]*(j<4?1:2);
        if (j<4?(value< -1024 || value>1023):(value<0 || value>2047)) return AF_JOINT_SKIP;
        next.cc1[j]=(int16_t)value;
    }
    for (unsigned j=0;j<276;++j) next.matrix_payload[j]=i->edit->matrix_payload[j];
    int16_t matrix_delta[27];uint16_t diagonal[3]={1024,1024,1024};
    if (af_joint_expand_matrix(r->matrix,matrix_delta)!=AF_OK) return AF_INVALID;
    next.matrix_quantized=0;
    static const uint8_t off_diagonal[6]={1,2,3,5,6,7};
    for (unsigned sector=0;sector<16;++sector) {
        uint16_t raw[18];int16_t base[27],added[27],mixed[9];
        if(sector_matrix){
            int16_t selected_matrix[18];
            for(unsigned e=0;e<3;++e)for(unsigned j=0;j<6;++j)
                selected_matrix[e*6+j]=sector_matrix[(e*16+sector)*6+j];
            if(af_joint_expand_matrix(selected_matrix,matrix_delta)!=AF_OK)return AF_INVALID;
        }
        for (unsigned e=0;e<3;++e) for (unsigned j=0;j<6;++j)
            raw[e*6+j]=i->matrix_raw[(e*16+sector)*6+j];
        if (af_color406_matrix(raw,diagonal,base)!=AF_OK ||
            af_color406_add(base,matrix_delta,27,added)!=AF_OK ||
            af_color406_matrix_blend(added,i->matrix_weights,mixed)!=AF_OK) return AF_INVALID;
        /* 独立九项整数舍入可能破坏精确行和；六项Edit表示不能静默丢弃此残差。 */
        for (unsigned row=0;row<3;++row) {
            int32_t sum=(int32_t)mixed[3*row]+mixed[3*row+1]+mixed[3*row+2];
            if (sum!=1024) return AF_JOINT_SKIP;
        }
        for (unsigned row=0;row<6;++row) {
            int32_t value=-(int32_t)mixed[off_diagonal[row]];
            if (value< -8192 || value>8191) return AF_JOINT_SKIP;
            unsigned offset=24+2*((row*16+sector)^1u);
            uint16_t low=(uint16_t)(next.matrix_payload[offset]&3u);
            uint16_t packed=(uint16_t)(((uint32_t)value&16383u)*4u|low);
            put16(next.matrix_payload+offset,packed);
            if (value<0 && value%2==0) ++next.matrix_quantized;
        }
    }
    *out=next;return AF_OK;
}
int af_edit_joint_parameters(const AfEditJointInput *i,const AfJointRecipe *r,AfEditJointParameters *out){
    return parameters(i,r,0,out);
}
int af_edit_joint_parameters_sector(const AfEditJointInput *i,const AfJointRecipe *r,
                                    const int16_t *sector_matrix,AfEditJointParameters *out){
    return sector_matrix?parameters(i,r,sector_matrix,out):AF_INVALID;
}
int af_edit_joint_init(AfEditJointCache *cache) {
    if (!cache) return AF_INVALID;
    cache->valid=cache->builds=cache->hits=0;
    for (unsigned j=0;j<32;++j) cache->recipe_sha256[j]=cache->source_sha256[j]=0;
    return AF_OK;
}
static int independent(const AfEditJointInput *i,const AfJointRecipe *r,
                        AfEditJointWork *work,AfEditJointCache *cache) {
    if (!apart(work,sizeof(*work),cache,sizeof(*cache)) ||
        !apart(i,sizeof(*i),work,sizeof(*work)) || !apart(i,sizeof(*i),cache,sizeof(*cache)) ||
        !apart(r,sizeof(*r),work,sizeof(*work)) || !apart(r,sizeof(*r),cache,sizeof(*cache)) || !i->edit ||
        !apart(i->edit,sizeof(*i->edit),work,sizeof(*work)) ||
        !apart(i->edit,sizeof(*i->edit),cache,sizeof(*cache))) return 0;
    const AfEditContextInput *e=i->edit;const AfEditRefChain *b=e->baseline;
    if (!b || b->main_entries!=65536 || b->y_entries!=32768 || b->matrix.table_entries!=18432 ||
        b->matrix.angle_entries!=512 || e->secondary_inverse_entries!=16384 || e->secondary_entries!=65536) return 0;
    const Span spans[]={{b,sizeof(*b)},{i->cp_gamma_record,576},{i->matrix_raw,576},{i->cc1_raw,48},
        {e->axis,512},{e->gamma_y,512},{e->contrast,4100},{e->matrix_payload,276},{e->cc1,16},
        {e->matrix_domain,sizeof(*e->matrix_domain)},{e->chroma_source,sizeof(*e->chroma_source)},
        {e->secondary_inverse,32768},{e->secondary_gamma,131072},{b->matrix.table,73728},
        {b->matrix.angles,2048},{b->main_gamma,131072},{b->y_gamma,65536}};
    for (unsigned j=0;j<sizeof(spans)/sizeof(spans[0]);++j)
        if (!apart(spans[j].p,spans[j].n,work,sizeof(*work)) ||
            !apart(spans[j].p,spans[j].n,cache,sizeof(*cache))) return 0;
    return 1;
}
static int recipe_hash(const AfJointRecipe *r,uint8_t hash[32]) {
    uint8_t bytes[1815];unsigned at=0;
    for (unsigned j=0;j<129;++j) word(bytes,&at,r->gamma[j]);
    for (unsigned j=0;j<18;++j) {put16(bytes+at,(uint16_t)r->matrix[j]);at+=2;}
    for (unsigned j=0;j<24;++j) {put16(bytes+at,(uint16_t)r->cc1[j]);at+=2;}
    for (unsigned j=0;j<AF_GRID_BYTES;++j) bytes[at++]=(uint8_t)r->grid[j];
    return af_sha256(bytes,at,hash);
}
static int candidate_hash(const AfJointRecipe *r,const int16_t *sector_matrix,uint8_t hash[32]){
    if(!sector_matrix)return recipe_hash(r,hash);
    static const char tag[]="A7R5_EDIT_SECTOR_MATRIX406_V1";
    uint8_t bytes[640],legacy[32];unsigned at=0;
    if(recipe_hash(r,legacy))return AF_INVALID;
    for(unsigned j=0;j<sizeof(tag);++j)bytes[at++]=(uint8_t)tag[j];
    for(unsigned j=0;j<32;++j)bytes[at++]=legacy[j];
    for(unsigned j=0;j<288;++j){put16(bytes+at,(uint16_t)sector_matrix[j]);at+=2;}
    return af_sha256(bytes,at,hash);
}
static int source_hash(const AfEditJointInput *i,uint8_t hash[32]) {
    const AfEditContextInput *e=i->edit;const AfEditRefChain *b=e->baseline;
    const Span blobs[]={{i->cp_gamma_record,576},{i->matrix_raw,576},{i->cc1_raw,48},
        {e->axis,512},{e->gamma_y,512},{e->contrast,4100},{e->matrix_payload,276},{e->cc1,16},
        {e->secondary_inverse,32768},{e->secondary_gamma,131072},{b->matrix.table,73728},
        {b->matrix.angles,2048},{b->main_gamma,131072},{b->y_gamma,65536}};
    uint8_t data[1024];unsigned at=0;
    for (unsigned j=0;j<sizeof(blobs)/sizeof(blobs[0]);++j) {
        if (af_sha256(blobs[j].p,blobs[j].n,data+at)) return AF_INVALID;
        at+=32;
    }
    word(data,&at,1);word(data,&at,e->main_inverse_initial_zero);
    word(data,&at,e->matrix_domain->schema);word(data,&at,e->matrix_domain->calibration_identity);
    word(data,&at,e->matrix_domain->output_gamut_mode);
    word(data,&at,e->matrix_domain->trailing_padding[0]);word(data,&at,e->matrix_domain->trailing_padding[1]);
    for (unsigned j=0;j<4;++j) {word(data,&at,i->matrix_weights[j]);word(data,&at,i->cc1_weights[j]);}
    word(data,&at,b->matrix.enabled);word(data,&at,b->matrix.luma_smooth);word(data,&at,b->matrix.chroma_smooth);
    word(data,&at,b->matrix.scale_chroma);word(data,&at,b->matrix.quadratic);
    for (unsigned j=0;j<3;++j) {real(data,&at,b->matrix.thresholds[j]);word(data,&at,(uint16_t)b->luma[j]);}
    for (unsigned j=0;j<8;++j) word(data,&at,(uint16_t)b->cc1[j]);
    word(data,&at,b->keep_unclipped);word(data,&at,b->area.selector);
    for (unsigned j=0;j<16;++j) real(data,&at,b->area.coefficients[j]);
    word(data,&at,(uint16_t)b->levels.black_level);word(data,&at,(uint16_t)b->levels.white_level);
    word(data,&at,(uint16_t)b->levels.pivot);real(data,&at,b->levels.gain);
    word(data,&at,(uint32_t)b->chroma.high_cutoff);word(data,&at,(uint32_t)b->chroma.low_cutoff);
    word(data,&at,(uint32_t)b->chroma.high_slope);word(data,&at,(uint32_t)b->chroma.low_slope);
    for (unsigned j=0;j<3;++j) {word(data,&at,(uint16_t)e->chroma_source->slopes[j]);
        word(data,&at,(uint16_t)e->chroma_source->thresholds[j]);}
    word(data,&at,(uint16_t)e->chroma_source->low_slope);word(data,&at,(uint16_t)e->chroma_source->low_threshold);
    word(data,&at,(uint16_t)e->chroma_source->gain_raw);word(data,&at,(uint32_t)e->chroma_source->exposure_300);
    return af_sha256(data,at,hash);
}
static int progress(void *opaque,uint32_t done,uint32_t total) {
    Progress *p=opaque;
    if (total!=AF_EDIT_CONTEXT_PROGRESS_TOTAL || done>total) return 1;
    return p->callback && p->callback(p->context,done+1,AF_EDIT_JOINT_PROGRESS_TOTAL);
}
static int prepare(const AfEditJointInput *i,const AfJointRecipe *r,const int16_t *sector_matrix,
                    AfEditJointWork *work,AfEditJointCache *cache,AfGridProgress callback,void *context) {
    if (!independent(i,r,work,cache) || cache->valid>1) return AF_INVALID;
    if(sector_matrix&&(!apart(sector_matrix,576,work,sizeof(*work))||
       !apart(sector_matrix,576,cache,sizeof(*cache))))return AF_INVALID;
    int result=recipe_valid(r);if (result!=AF_OK) return result;
    if(sector_valid(r,sector_matrix)!=AF_OK)return AF_INVALID;
    if (callback && callback(context,0,AF_EDIT_JOINT_PROGRESS_TOTAL)) return AF_GRID_CANCELLED;
    uint8_t rh[32],sh[32];
    if (candidate_hash(r,sector_matrix,rh) || source_hash(i,sh)) return AF_INVALID;
    if (cache->valid && equal(rh,cache->recipe_sha256,32) && equal(sh,cache->source_sha256,32)) {
        if (cache->hits==UINT32_MAX) return AF_EXHAUSTED;
        if (callback && callback(context,AF_EDIT_JOINT_PROGRESS_TOTAL,AF_EDIT_JOINT_PROGRESS_TOTAL)) return AF_GRID_CANCELLED;
        ++cache->hits;return AF_OK;
    }
    if (cache->builds==UINT32_MAX) return AF_EXHAUSTED;
    result=parameters(i,r,sector_matrix,&work->parameters);if (result!=AF_OK) return result;
    AfEditContextInput edit=*i->edit;
    edit.axis=work->parameters.gamma.axis;edit.gamma_y=work->parameters.gamma.gamma_y;
    edit.matrix_payload=work->parameters.matrix_payload;edit.cc1=work->parameters.cc1;
    Progress state={callback,context};
    result=af_edit_context_build(&edit,&work->build,&cache->context,progress,&state);
    if (result!=AF_OK) return result;
    for (unsigned j=0;j<32;++j) {cache->recipe_sha256[j]=rh[j];cache->source_sha256[j]=sh[j];}
    cache->valid=1;++cache->builds;return AF_OK;
}
int af_edit_joint_prepare(const AfEditJointInput *i,const AfJointRecipe *r,AfEditJointWork *work,
                          AfEditJointCache *cache,AfGridProgress callback,void *context){
    return prepare(i,r,0,work,cache,callback,context);
}
int af_edit_joint_prepare_sector(const AfEditJointInput *i,const AfJointRecipe *r,
    const int16_t *sector_matrix,AfEditJointWork *work,AfEditJointCache *cache,AfGridProgress callback,void *context){
    return sector_matrix?prepare(i,r,sector_matrix,work,cache,callback,context):AF_INVALID;
}
int af_edit_joint_eval(const AfEditJointCache *cache,const uint16_t *rgb,
                       AfEditJointEvalWork *work,uint16_t *output) {
    if (!apart(cache,sizeof(*cache),work,sizeof(*work)) ||
        !apart(cache,sizeof(*cache),output,6) || !apart(rgb,6,work,sizeof(*work)) ||
        !apart(rgb,6,output,6) || !apart(work,sizeof(*work),output,6) || cache->valid!=1) return AF_INVALID;
    for (unsigned x=0;x<5;++x) for (unsigned c=0;c<3;++c) work->patch[3*x+c]=rgb[c];
    int result=af_edit_ref_color(&cache->context.chain,work->patch,5,1,&work->pixels,work->rendered);
    if (result!=AF_OK) return result;
    for (unsigned c=0;c<3;++c) output[c]=work->rendered[6+c];
    return AF_OK;
}
