#include "af_edit_context.h"
#ifdef __FAST_MATH__
#error "Edit context construction requires finite baseline validation"
#endif
_Static_assert(sizeof(AfEditContext)<=AF_EDIT_CONTEXT_OUTPUT_BUDGET,"Edit output exceeds budget");
_Static_assert(sizeof(AfEditContextWork)<=AF_EDIT_CONTEXT_WORK_BUDGET,"Edit work exceeds budget");
typedef struct {const void *p;size_t bytes;} Span;
typedef struct {AfGridProgress callback;void *context;uint32_t offset,total;} Progress;
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static uint16_t half(const uint8_t *p) {return (uint16_t)((uint16_t)p[0]|(uint16_t)p[1]<<8);}
static float real(const uint8_t *p) {
    union {float f;uint32_t u;} v;
    v.u=(uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;return v.f;
}
static int progress(void *context,uint32_t completed,uint32_t total) {
    Progress *p=context;
    if (total!=p->total || completed>total) return 1;
    return p->callback && p->callback(p->context,p->offset+completed,AF_EDIT_CONTEXT_PROGRESS_TOTAL);
}
static int valid(const AfEditContextInput *input,AfEditContextWork *work,AfEditContext *output) {
    if (!apart(input,sizeof(*input),work,sizeof(*work)) ||
        !apart(input,sizeof(*input),output,sizeof(*output)) || !apart(work,sizeof(*work),output,sizeof(*output))) return 0;
    const AfEditRefChain *b=input->baseline;
    if (!b || b->main_entries!=65536 || b->y_entries!=32768 ||
        b->matrix.table_entries!=18432 || b->matrix.angle_entries!=512 ||
        input->secondary_inverse_entries!=16384 || input->secondary_entries!=65536 ||
        b->keep_unclipped>1 || b->area.selector>1 || !__builtin_isfinite(b->levels.gain) ||
        512-(int)b->levels.white_level+b->levels.black_level/4==0) return 0;
    const Span spans[]={{b,sizeof(*b)},{input->axis,512},{input->gamma_y,512},{input->contrast,4100},
        {input->matrix_payload,276},{input->cc1,16},{input->matrix_domain,sizeof(*input->matrix_domain)},
        {input->chroma_source,sizeof(*input->chroma_source)},
        {input->secondary_inverse,32768},{input->secondary_gamma,131072},
        {b->matrix.table,73728},{b->matrix.angles,2048},{b->main_gamma,131072},{b->y_gamma,65536}};
    for (unsigned i=0;i<sizeof(spans)/sizeof(spans[0]);++i)
        if (!apart(spans[i].p,spans[i].bytes,work,sizeof(*work)) ||
            !apart(spans[i].p,spans[i].bytes,output,sizeof(*output))) return 0;
    for (unsigned i=0;i<8;++i)
        if (i<4?(input->cc1[i]<-1024 || input->cc1[i]>1023):(input->cc1[i]<0 || input->cc1[i]>2047)) return 0;
    for (unsigned i=0;i<16;++i) if (!__builtin_isfinite(b->area.coefficients[i])) return 0;
    for (unsigned i=0;i<512;++i)
        if (!__builtin_isfinite(b->matrix.angles[i]) || b->matrix.angles[i]<0 || b->matrix.angles[i]>1023) return 0;
    for (unsigned i=0;i<32768;++i)
        if (b->y_gamma[i]!=(uint16_t)input->secondary_gamma[32768+i]) return 0;
    return 1;
}
static void bind(AfEditContext *c) {
    c->chain.matrix.table=c->matrix_table;c->chain.matrix.angles=c->angles;
    c->chain.main_gamma=c->main_gamma;c->chain.y_gamma=(const uint16_t *)c->secondary_gamma+32768;
}
int af_edit_context_build(const AfEditContextInput *input,AfEditContextWork *work,
                          AfEditContext *output,AfGridProgress callback,void *context) {
    if (!valid(input,work,output)) return AF_INVALID;
    AfEditContext *c=&work->candidate;const AfEditRefChain *b=input->baseline;
    /* 只清理小型元数据区；各完整表随后全部填充，不泄漏结构填充字节。 */
    volatile uint8_t *metadata=(volatile uint8_t *)c;
    for (size_t i=0;i<offsetof(AfEditContext,matrix_config);++i) metadata[i]=0;
    for (unsigned i=0;i<3;++i) {
        c->chroma_source.slopes[i]=input->chroma_source->slopes[i];
        c->chroma_source.thresholds[i]=input->chroma_source->thresholds[i];
        c->chain.luma[i]=b->luma[i];
    }
    c->chroma_source.low_slope=input->chroma_source->low_slope;
    c->chroma_source.low_threshold=input->chroma_source->low_threshold;
    c->chroma_source.gain_raw=input->chroma_source->gain_raw;
    c->chroma_source.exposure_300=input->chroma_source->exposure_300;
    for (unsigned i=0;i<8;++i) c->chain.cc1[i]=input->cc1[i];
    for (unsigned i=0;i<16;++i) c->chain.area.coefficients[i]=b->area.coefficients[i];
    c->chain.area.selector=b->area.selector;c->chain.keep_unclipped=b->keep_unclipped;
    c->chain.levels.black_level=b->levels.black_level;c->chain.levels.white_level=b->levels.white_level;
    c->chain.levels.pivot=b->levels.pivot;c->chain.levels.gain=b->levels.gain;
    for (unsigned i=0;i<512;++i) c->angles[i]=b->matrix.angles[i];
    for (unsigned i=0;i<65536;++i) c->secondary_gamma[i]=input->secondary_gamma[i];

    Progress phase={callback,context,0,65536};
    int result=af_edit_gamma_table(input->axis,input->gamma_y,input->contrast,&work->gamma,
                                   c->main_gamma,progress,&phase);
    if (result!=AF_OK) return result;
    phase.offset=65536;
    result=af_edit_gamma_main_inverse((const int16_t *)c->main_gamma,input->main_inverse_initial_zero,
                                      &work->gamma,(uint16_t *)c->main_inverse,progress,&phase);
    if (result!=AF_OK) return result;
    phase.offset=131072;phase.total=1024;
    result=af_edit_matrix_table(input->matrix_payload,input->matrix_domain,&work->matrix,
                                c->matrix_config,c->matrix_table,progress,&phase);
    if (result!=AF_OK) return result;
    phase.offset=132096;phase.total=16384;
    result=af_edit_gamma_secondary_inverse(c->secondary_gamma,&work->gamma,
                                           (uint16_t *)c->secondary_inverse,progress,&phase);
    if (result!=AF_OK) return result;
    for (unsigned i=0;i<16384;++i)
        if (c->secondary_inverse[i]!=input->secondary_inverse[i]) return AF_INVALID;
    AfEditRefChromaTables tables={c->secondary_inverse,c->main_inverse,(const int16_t *)c->main_gamma,
                                 c->secondary_gamma,16384,65536,65536,65536};
    result=af_edit_ref_chroma_controls(&c->chroma_source,&tables,&c->chain.chroma);
    if (result!=AF_OK) return result;

    c->chain.main_entries=65536;c->chain.y_entries=32768;
    c->chain.matrix.table_entries=18432;c->chain.matrix.angle_entries=512;
    c->chain.matrix.enabled=half(c->matrix_config+0x220);
    c->chain.matrix.luma_smooth=half(c->matrix_config);
    c->chain.matrix.chroma_smooth=half(c->matrix_config+2);
    c->chain.matrix.scale_chroma=half(c->matrix_config+4);
    c->chain.matrix.quadratic=half(c->matrix_config+0x222);
    for (unsigned i=0;i<3;++i) c->chain.matrix.thresholds[i]=real(c->matrix_config+0x214+4*i);
    bind(c);
    if (callback && callback(context,AF_EDIT_CONTEXT_PROGRESS_TOTAL,AF_EDIT_CONTEXT_PROGRESS_TOTAL)) return AF_GRID_CANCELLED;
    const uint8_t *source=(const uint8_t *)c;uint8_t *destination=(uint8_t *)output;
    for (size_t i=0;i<sizeof(*output);++i) destination[i]=source[i];
    bind(output);
    return AF_OK;
}
