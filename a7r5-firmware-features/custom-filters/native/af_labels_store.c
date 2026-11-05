#include "af_labels_store.h"
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static int same(const AfPreset *a,const AfPreset *b) {
    if (a->base!=b->base || a->kind!=b->kind) return 0;
    for (unsigned i=0;i<8;++i) if (a->params[i]!=b->params[i]) return 0;
    for (unsigned i=0;i<32;++i)
        if (a->payload_sha256[i]!=b->payload_sha256[i] || a->lut_sha256[i]!=b->lut_sha256[i]) return 0;
    return 1;
}
int af_labels_from_store(AfLabels *labels,const AfCatalog *catalog,const AfStore *s,
                          const AfStoreBuffers *buffers,int recovering) {
    if (!catalog || !s || !buffers || !s->slot || s->slot>AF_USERS ||
        (recovering!=0 && recovering!=1) || !apart(labels,sizeof(*labels),catalog,sizeof(*catalog)) ||
        !apart(labels,sizeof(*labels),s,sizeof(*s)) || !apart(labels,sizeof(*labels),buffers,sizeof(*buffers)) ||
        !apart(labels,sizeof(*labels),buffers->a,buffers->capacity) ||
        !apart(labels,sizeof(*labels),buffers->b,buffers->capacity) ||
        !apart(labels,sizeof(*labels),buffers->next,buffers->capacity)) return AF_STORE_INVALID;
    const AfSlot *slot=&catalog->slots[s->slot-1];
    if (slot->pending.request || slot->saved_revision!=s->generation) return AF_STORE_STALE;
    AfDocument d;int status=af_store_snapshot(s,buffers,&d);
    if (status) return status;
    if (d.present!=(uint32_t)slot->present || (d.present &&
        (!same(&d.initial,&slot->initial) || !same(&d.saved,&slot->saved)))) return AF_STORE_STALE;
    AfLabels candidate=*labels;
    if (recovering) {
        AfLabel empty={0};candidate.slots[s->slot-1]=empty;
    }
    status=af_labels_publish(&candidate,s->slot,s->generation,d.present?d.name:NULL,d.present?d.name_bytes:0);
    if (status) return status==AF_STALE?AF_STORE_STALE:AF_STORE_INVALID;
    labels->slots[s->slot-1]=candidate.slots[s->slot-1];return AF_STORE_OK;
}
