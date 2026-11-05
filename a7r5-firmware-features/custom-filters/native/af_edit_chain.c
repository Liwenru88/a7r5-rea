#include "af_edit_chain.h"
typedef struct { const void *p; size_t bytes; } Span;
static int apart(const void *a, size_t n, const void *b, size_t m) {
    uintptr_t x=(uintptr_t)a, y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m &&
           (x+n<=y || y+m<=x);
}
int af_edit_ref_color(const AfEditRefChain *p, const uint16_t *rgb,
                      size_t width, size_t height, AfEditRefChainWork *work, uint16_t *output) {
    if (!p || !width || !height || width>AF_EDIT_REF_MAX_PIXELS ||
        height>AF_EDIT_REF_MAX_PIXELS/width || p->main_entries!=65536 ||
        p->y_entries!=32768 || p->matrix.table_entries!=18432 ||
        p->matrix.angle_entries!=512) return AF_INVALID;
    size_t pixels=width*height, bytes=pixels*6;
    const Span inputs[]={{p,sizeof(*p)},{rgb,bytes},
        {p->main_gamma,131072},{p->y_gamma,65536},
        {p->matrix.table,18432*4},{p->matrix.angles,512*4}};
    if (!apart(work,sizeof(*work),output,bytes)) return AF_INVALID;
    for (unsigned i=0;i<sizeof(inputs)/sizeof(inputs[0]);++i)
        if (!apart(work,sizeof(*work),inputs[i].p,inputs[i].bytes) ||
            !apart(output,bytes,inputs[i].p,inputs[i].bytes)) return AF_INVALID;
    int result=af_edit_ref_matrix16(&p->matrix,rgb,width,height,work->a);
    if (result!=AF_OK) return result;
    result=af_edit_ref_main_gamma(p->main_gamma,p->main_entries,work->a,pixels,work->b);
    if (result!=AF_OK) return result;
    result=af_edit_ref_rgb_ycc((const int16_t *)work->b,pixels,p->cc1,p->luma,
                              p->keep_unclipped,work->a);
    if (result!=AF_OK) return result;
    result=af_edit_ref_area(&p->area,work->a,pixels,work->b);
    if (result!=AF_OK) return result;
    result=af_edit_ref_chroma(&p->chroma,work->b,pixels,work->a);
    if (result!=AF_OK) return result;
    result=af_edit_ref_y_gamma(p->y_gamma,p->y_entries,&p->levels,work->a,pixels,work->b);
    if (result!=AF_OK) return result;
    result=af_edit_ref_ycc_rgb(work->b,pixels,work->a);
    if (result!=AF_OK) return result;
    for (size_t i=0;i<pixels*3;++i) output[i]=work->a[i];
    return AF_OK;
}
