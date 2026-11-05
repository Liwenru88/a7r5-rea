#include "af_document.h"
#include "af_sha256.h"
#include "af_text.h"

static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static void put32(uint8_t *p,uint32_t v) {
    for (unsigned i=0;i<4;++i) p[i]=(uint8_t)(v>>(8*i));
}
static int equal(const uint8_t *a,const uint8_t *b,size_t n) {
    for (size_t i=0;i<n;++i) if (a[i]!=b[i]) return 0;
    return 1;
}
static int zero(const uint8_t *p,size_t n) {
    for (size_t i=0;i<n;++i) if (p[i]) return 0;
    return 1;
}
static int name_valid(const char *name,size_t n) {
    return af_text_name_valid(name,n);
}
static void write_preset(uint8_t *p,const AfPreset *v) {
    p[0]=v->base;p[1]=v->kind;
    for (unsigned i=0;i<8;++i) p[2+i]=(uint8_t)v->params[i];
    for (unsigned i=0;i<32;++i) { p[10+i]=v->payload_sha256[i];p[42+i]=v->lut_sha256[i]; }
}
static void read_preset(const uint8_t *p,AfPreset *v) {
    v->base=p[0];v->kind=p[1];
    for (unsigned i=0;i<8;++i) v->params[i]=(int8_t)(p[2+i]<=127?p[2+i]:(int)p[2+i]-256);
    for (unsigned i=0;i<32;++i) { v->payload_sha256[i]=p[10+i];v->lut_sha256[i]=p[42+i]; }
}
static int validate(const AfDocument *d,uint32_t schema) {
    uint8_t hash[32];
    const AfFitReport *r;
    if (!d || d->present>1) return AF_DOCUMENT_INVALID;
    if (!d->present) {
        /* 墓碑无业务字段；不因调用者结构填充字节不同拒绝。 */
        uint8_t initial[74],saved[74];
        write_preset(initial,&d->initial);write_preset(saved,&d->saved);
        if (!zero(initial,74) || !zero(saved,74) || d->schema || d->converter ||
            d->name_bytes || d->image_bytes || d->report.samples || d->report.clipped ||
            d->report.scope || !zero(d->report.model_sha256,32)) return AF_DOCUMENT_INVALID;
        for (unsigned i=0;i<5;++i) if (d->report.delta_e[i]) return AF_DOCUMENT_INVALID;
        return AF_DOCUMENT_OK;
    }
    if (!name_valid(d->name,d->name_bytes) || af_validate(&d->initial)!=AF_OK ||
        af_validate(&d->saved)!=AF_OK ||
        (d->initial.kind && d->initial.base!=d->saved.base) ||
        d->initial.kind!=d->saved.kind ||
        !equal(d->initial.payload_sha256,d->saved.payload_sha256,32) ||
        !equal(d->initial.lut_sha256,d->saved.lut_sha256,32)) return AF_DOCUMENT_INVALID;
    r=&d->report;
    if (!d->initial.kind) {
        if (d->schema || d->converter || d->image_bytes || r->samples || r->clipped ||
            r->scope || !zero(r->model_sha256,32)) return AF_DOCUMENT_INVALID;
        for (unsigned i=0;i<5;++i) if (r->delta_e[i]) return AF_DOCUMENT_INVALID;
    } else {
        if (!schema || d->schema!=schema) return AF_DOCUMENT_UNSUPPORTED;
        if (!d->converter || !d->image || !d->image_bytes || d->image_bytes>AF_DOCUMENT_IMAGE_MAX ||
            !r->samples || r->clipped>r->samples || r->scope!=1 || zero(r->model_sha256,32) ||
            r->delta_e[0]>r->delta_e[2] || r->delta_e[1]>r->delta_e[2] ||
            r->delta_e[3]>r->delta_e[2] || r->delta_e[4]>r->delta_e[2]) return AF_DOCUMENT_INVALID;
        if (af_sha256(d->image,d->image_bytes,hash) || !equal(hash,d->initial.payload_sha256,32))
            return AF_DOCUMENT_INVALID;
    }
    return AF_DOCUMENT_OK;
}
int af_document_encode(const AfDocument *d,uint32_t schema,void *output,size_t cap,size_t *written) {
    uint8_t *p=output;
    size_t bytes;
    int status;
    if (!output || !written) return AF_DOCUMENT_INVALID;
    status=validate(d,schema);
    if (status) return status;
    bytes=AF_DOCUMENT_HEADER+d->name_bytes+d->image_bytes;
    if (bytes>cap) return AF_DOCUMENT_CAPACITY;
    for (size_t i=0;i<AF_DOCUMENT_HEADER;++i) p[i]=0;
    p[0]='A';p[1]='F';p[2]='D';p[3]='1';p[4]=1;p[7]=1;
    put32(p+8,d->schema);put32(p+12,d->converter);
    put32(p+16,(uint32_t)d->name_bytes);put32(p+20,(uint32_t)d->image_bytes);
    put32(p+24,d->report.samples);put32(p+28,d->report.clipped);
    for (unsigned i=0;i<5;++i) put32(p+32+4*i,d->report.delta_e[i]);
    put32(p+52,d->report.scope);
    for (unsigned i=0;i<32;++i) p[56+i]=d->report.model_sha256[i];
    write_preset(p+88,&d->initial);write_preset(p+162,&d->saved);put32(p+236,d->present);
    for (size_t i=0;i<d->name_bytes;++i) p[AF_DOCUMENT_HEADER+i]=(uint8_t)d->name[i];
    for (size_t i=0;i<d->image_bytes;++i) p[AF_DOCUMENT_HEADER+d->name_bytes+i]=d->image[i];
    *written=bytes;
    return AF_DOCUMENT_OK;
}
int af_document_decode(const void *raw,size_t bytes,uint32_t schema,AfDocument *output) {
    const uint8_t *p=raw;
    AfDocument d={0};
    int status;
    if (!p || !output || bytes<AF_DOCUMENT_HEADER || bytes>AF_DOCUMENT_MAX ||
        p[0]!='A' || p[1]!='F' || p[2]!='D' || p[3]!='1') return AF_DOCUMENT_INVALID;
    if (p[4]!=1 || p[5] || p[6] || p[7]!=1) return AF_DOCUMENT_UNSUPPORTED;
    if (!zero(p+240,16)) return AF_DOCUMENT_INVALID;
    d.schema=get32(p+8);d.converter=get32(p+12);
    d.name_bytes=get32(p+16);d.image_bytes=get32(p+20);
    if (d.name_bytes>AF_DOCUMENT_NAME_MAX || d.image_bytes>AF_DOCUMENT_IMAGE_MAX ||
        d.name_bytes+d.image_bytes!=bytes-AF_DOCUMENT_HEADER) return AF_DOCUMENT_INVALID;
    d.name=(const char *)p+AF_DOCUMENT_HEADER;d.image=p+AF_DOCUMENT_HEADER+d.name_bytes;
    d.report.samples=get32(p+24);d.report.clipped=get32(p+28);
    for (unsigned i=0;i<5;++i) d.report.delta_e[i]=get32(p+32+4*i);
    d.report.scope=get32(p+52);
    for (unsigned i=0;i<32;++i) d.report.model_sha256[i]=p[56+i];
    read_preset(p+88,&d.initial);read_preset(p+162,&d.saved);d.present=get32(p+236);
    status=validate(&d,schema);
    if (status) return status;
    *output=d;
    return AF_DOCUMENT_OK;
}

int af_document_report_applies(const AfDocument *d,const AfPreset *current) {
    if (!d || !current || d->present!=1 || d->initial.kind!=1 || d->report.scope!=1 ||
        current->base!=d->initial.base || current->kind!=d->initial.kind ||
        !equal(current->payload_sha256,d->initial.payload_sha256,32) ||
        !equal(current->lut_sha256,d->initial.lut_sha256,32)) return 0;
    for (unsigned i=0;i<8;++i) if (current->params[i]!=d->initial.params[i]) return 0;
    return 1;
}
