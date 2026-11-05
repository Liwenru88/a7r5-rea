#include "af_versions.h"

size_t af_versions_bytes(void) { return sizeof(AfVersions); }
static int separate(const void *a,const void *b,size_t n) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && (x>y?x-y:y-x)>=n;
}
static int valid(const AfVersions *v) { return v && v->initialized==0x41375631u; }
int af_versions_init(AfVersions *v,void *a,void *b,void *c,size_t capacity,uint32_t schema) {
    AfVersions next={0};
    if (!v || capacity<AF_DOCUMENT_HEADER || capacity>AF_DOCUMENT_MAX ||
        !separate(a,b,capacity) || !separate(a,c,capacity) || !separate(b,c,capacity)) return AF_INVALID;
    next.banks[0].raw=a;next.banks[1].raw=b;next.banks[2].raw=c;
    next.capacity=capacity;next.schema=schema;next.active=AF_VERSION_BANKS;
    next.initialized=0x41375631u;
    *v=next;
    return AF_OK;
}
int af_versions_stage(AfVersions *v,const void *raw,size_t bytes,AfVersionToken *output) {
    AfDocument d;
    uint32_t bank=AF_VERSION_BANKS;
    if (!valid(v) || !raw || !output || bytes>v->capacity) return AF_INVALID;
    if (v->pending.version) return AF_BUSY;
    if (v->next_version==UINT64_MAX) return AF_EXHAUSTED;
    if (af_document_decode(raw,bytes,v->schema,&d) || !d.present) return AF_INVALID;
    for (uint32_t i=0;i<AF_VERSION_BANKS;++i)
        if (i!=v->active && !v->banks[i].references) { bank=i;break; }
    if (bank==AF_VERSION_BANKS) return AF_BUSY;
    /* 原始数据不得与目标缓冲重叠，避免调用者借用旧版时发生部分覆盖。 */
    if (!separate(raw,v->banks[bank].raw,bytes)) return AF_INVALID;
    for (size_t i=0;i<bytes;++i) v->banks[bank].raw[i]=((const uint8_t *)raw)[i];
    v->banks[bank].used=bytes;v->banks[bank].version=++v->next_version;
    v->pending.version=v->next_version;v->pending.bank=bank;
    *output=v->pending;
    return AF_OK;
}
int af_versions_finish(AfVersions *v,const AfVersionToken *t,int succeeded) {
    if (!valid(v) || !t || (succeeded!=0 && succeeded!=1)) return AF_INVALID;
    if (!t->version || v->pending.version!=t->version || v->pending.bank!=t->bank) return AF_STALE;
    if (succeeded) v->active=t->bank;
    else v->banks[t->bank].used=0;
    v->pending.version=0;
    return succeeded?AF_OK:AF_IO;
}
int af_versions_acquire(AfVersions *v,AfVersionLease *output) {
    AfVersionLease lease;
    if (!valid(v) || !output) return AF_INVALID;
    if (v->active>=AF_VERSION_BANKS) return AF_EMPTY;
    if (v->next_lease==UINT64_MAX) return AF_EXHAUSTED;
    for (unsigned i=0;i<AF_VERSION_LEASES;++i) if (!v->leases[i].lease) {
        lease.version=v->banks[v->active].version;lease.bank=v->active;lease.lease=++v->next_lease;
        v->leases[i]=lease;++v->banks[v->active].references;
        *output=lease;
        return AF_OK;
    }
    return AF_BUSY;
}
static int find(const AfVersions *v,const AfVersionLease *ref) {
    if (!ref || !ref->lease || ref->bank>=AF_VERSION_BANKS) return -1;
    for (unsigned i=0;i<AF_VERSION_LEASES;++i) {
        const AfVersionLease *r=&v->leases[i];
        if (r->lease==ref->lease && r->bank==ref->bank && r->version==ref->version &&
            v->banks[r->bank].version==r->version) return (int)i;
    }
    return -1;
}
int af_versions_view(const AfVersions *v,const AfVersionLease *ref,const void **raw,size_t *bytes) {
    if (!valid(v) || !raw || !bytes) return AF_INVALID;
    if (find(v,ref)<0) return AF_STALE;
    *raw=v->banks[ref->bank].raw;*bytes=v->banks[ref->bank].used;
    return AF_OK;
}
int af_versions_release(AfVersions *v,const AfVersionLease *ref) {
    int at;
    if (!valid(v)) return AF_INVALID;
    at=find(v,ref);
    if (at<0) return AF_STALE;
    --v->banks[ref->bank].references;v->leases[at].lease=0;
    return AF_OK;
}
