#include "af_labels.h"
#include "af_text.h"
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
void af_labels_init(AfLabels *labels) {
    if (labels) for (size_t i=0;i<sizeof(*labels);++i) ((uint8_t *)labels)[i]=0;
}
int af_labels_publish(AfLabels *labels,uint32_t slot,uint64_t generation,const char *name,size_t bytes) {
    if (!labels || !slot || slot>AF_USERS || !generation ||
        (bytes ? (!af_text_name_valid(name,bytes) || !apart(labels,sizeof(*labels),name,bytes)) : name!=NULL))
        return AF_INVALID;
    AfLabel *entry=&labels->slots[slot-1];
    if (generation<entry->generation) return AF_STALE;
    if (generation==entry->generation) {
        if (entry->bytes!=bytes) return AF_STALE;
        for (size_t i=0;i<bytes;++i) if (entry->text[i]!=name[i]) return AF_STALE;
        return AF_OK;
    }
    for (size_t i=0;i<bytes;++i) entry->text[i]=name[i];
    for (size_t i=bytes;i<AF_LABEL_BYTES;++i) entry->text[i]=0;
    entry->bytes=(uint32_t)bytes;entry->generation=generation;
    return AF_OK;
}
int af_labels_read(const AfLabels *labels,uint32_t slot,const char **name,size_t *bytes) {
    if (!labels || !slot || slot>AF_USERS || !apart(labels,sizeof(*labels),name,sizeof(*name)) ||
        !apart(labels,sizeof(*labels),bytes,sizeof(*bytes)) || !apart(name,sizeof(*name),bytes,sizeof(*bytes)))
        return AF_INVALID;
    const AfLabel *entry=&labels->slots[slot-1];
    if (!entry->generation || !entry->bytes) return AF_EMPTY;
    *name=entry->text;*bytes=entry->bytes;return AF_OK;
}
