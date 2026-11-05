#include "af_persist.h"

static int ready(const AfCatalog *c,const AfStore *s) {
    if (!c || !s || !s->slot || s->slot>AF_USERS) return AF_STORE_INVALID;
    if (s->uncertain) return AF_STORE_UNCERTAIN;
    if (!s->ready) return AF_STORE_INVALID;
    if (c->slots[s->slot-1].pending.request) return AF_PERSIST_BUSY;
    if (c->slots[s->slot-1].saved_revision!=s->generation) return AF_STORE_STALE;
    return AF_STORE_OK;
}
static int same(const AfPreset *a,const AfPreset *b) {
    if (a->base!=b->base || a->kind!=b->kind) return 0;
    for (unsigned i=0;i<8;++i) if (a->params[i]!=b->params[i]) return 0;
    for (unsigned i=0;i<32;++i)
        if (a->payload_sha256[i]!=b->payload_sha256[i] || a->lut_sha256[i]!=b->lut_sha256[i]) return 0;
    return 1;
}
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static int independent(const void *p,size_t n,const AfCatalog *c,const AfStore *s,
                        const AfStoreIo *io,const AfStoreBuffers *b) {
    return io && b && apart(p,n,c,sizeof(*c)) && apart(p,n,s,sizeof(*s)) &&
        apart(p,n,io,sizeof(*io)) && apart(p,n,b,sizeof(*b)) && apart(p,n,b->a,b->capacity) &&
        apart(p,n,b->b,b->capacity) && apart(p,n,b->next,b->capacity);
}
static int current_document(AfStore *s,const AfStoreIo *io,const AfStoreBuffers *b,AfDocument *d) {
    AfStore check=*s;
    int status=af_store_recover(&check,io,b,0,d);
    if (status) { s->ready=0;return status==AF_STORE_MISSING?AF_STORE_STALE:status; }
    if (check.bank!=s->bank || check.generation!=s->generation) { s->ready=0;return AF_STORE_STALE; }
    for (unsigned i=0;i<32;++i) if (check.digest[i]!=s->digest[i]) { s->ready=0;return AF_STORE_STALE; }
    return AF_STORE_OK;
}
static void drop(AfCatalog *c,uint32_t slot,uint64_t generation) {
    AfSlot empty={0};
    empty.saved_revision=generation;
    c->slots[slot-1]=empty;
}
int af_persist_load(AfCatalog *c,AfStore *s,const AfStoreIo *io,const AfStoreBuffers *b,int allow_empty) {
    AfDocument d;
    int status;
    if (!c || !s || !s->slot || s->slot>AF_USERS) return AF_STORE_INVALID;
    if (c->slots[s->slot-1].pending.request) return AF_PERSIST_BUSY;
    status=af_store_recover(s,io,b,allow_empty,&d);
    if (status) {
        if (status==AF_STORE_MISSING && c->slots[s->slot-1].saved_revision) {
            s->ready=0;return AF_STORE_STALE;
        }
        return status;
    }
    if (!d.present) { drop(c,s->slot,s->generation);return AF_STORE_OK; }
    return af_catalog_load(c,s->slot,&d.initial,&d.saved,s->generation)==AF_OK?AF_STORE_OK:AF_STORE_INVALID;
}
int af_persist_replace(AfCatalog *c,AfStore *s,const AfStoreIo *io,const AfStoreBuffers *b,
                       const AfDocument *d,int overwrite) {
    AfPreset initial,saved;
    int status=ready(c,s);
    if (status) return status;
    if (!d || d->present!=1 || (overwrite!=0 && overwrite!=1)) return AF_STORE_INVALID;
    if (c->slots[s->slot-1].present && !overwrite) return AF_PERSIST_EXISTS;
    initial=d->initial;saved=d->saved;
    status=af_store_commit(s,io,b,d);
    if (status) return status;
    /* 事务先校验相同预设，且回调禁止重入安装；此处不再执行文件操作。 */
    if (af_catalog_load(c,s->slot,&initial,&saved,s->generation)!=AF_OK) {
        s->uncertain=1;s->ready=0;return AF_STORE_UNCERTAIN;
    }
    return AF_STORE_OK;
}
int af_persist_save(AfCatalog *c,AfStore *s,const AfStoreIo *io,const AfStoreBuffers *b) {
    AfSave save;
    AfDocument d;
    int status=ready(c,s),finished;
    if (status) return status;
    if (!c->slots[s->slot-1].present) return AF_PERSIST_EMPTY;
    status=current_document(s,io,b,&d);
    if (status) return status;
    if (!d.present || !same(&d.initial,&c->slots[s->slot-1].initial) ||
        !same(&d.saved,&c->slots[s->slot-1].saved)) return AF_STORE_STALE;
    status=af_begin_save(c,s->slot,&save);
    if (status) return status==AF_BUSY?AF_PERSIST_BUSY:AF_STORE_INVALID;
    d.saved=save.snapshot;
    status=af_store_commit(s,io,b,&d);
    finished=af_finish_save(c,&save,status==AF_STORE_OK);
    if (status) return status;
    if (finished!=AF_OK) { s->uncertain=1;s->ready=0;return AF_STORE_UNCERTAIN; }
    return AF_STORE_OK;
}
int af_persist_clear(AfCatalog *c,AfStore *s,const AfStoreIo *io,const AfStoreBuffers *b) {
    AfDocument tombstone={0};
    int status=ready(c,s);
    if (status) return status;
    if (!c->slots[s->slot-1].present) return AF_PERSIST_EMPTY;
    status=af_store_commit(s,io,b,&tombstone);
    if (status) return status;
    drop(c,s->slot,s->generation);
    return AF_STORE_OK;
}
int af_persist_rename(AfCatalog *c,AfStore *s,const AfStoreIo *io,const AfStoreBuffers *b,const char *name,size_t bytes) {
    AfDocument d;int status=ready(c,s);
    if (status) return status;
    if (!bytes || bytes>AF_DOCUMENT_NAME_MAX || !independent(name,bytes,c,s,io,b)) return AF_STORE_INVALID;
    if (!c->slots[s->slot-1].present) return AF_PERSIST_EMPTY;
    status=current_document(s,io,b,&d);
    if (status) return status;
    if (!d.present || !same(&d.initial,&c->slots[s->slot-1].initial) ||
        !same(&d.saved,&c->slots[s->slot-1].saved)) return AF_STORE_STALE;
    d.name=name;d.name_bytes=bytes;
    status=af_store_commit(s,io,b,&d);
    if (status) return status;
    c->slots[s->slot-1].saved_revision=s->generation;
    return AF_STORE_OK;
}
int af_persist_export(AfCatalog *c,AfStore *s,const AfStoreIo *io,const AfStoreBuffers *b,
                       int working,void *output,size_t cap,size_t *written) {
    AfDocument d;int status=ready(c,s);
    if (status) return status;
    if ((working!=0 && working!=1) || !cap || !independent(output,cap,c,s,io,b) ||
        !independent(written,sizeof(*written),c,s,io,b) || !apart(output,cap,written,sizeof(*written))) return AF_STORE_INVALID;
    if (!c->slots[s->slot-1].present) return AF_PERSIST_EMPTY;
    status=current_document(s,io,b,&d);
    if (status) return status;
    if (!d.present || !same(&d.initial,&c->slots[s->slot-1].initial) ||
        !same(&d.saved,&c->slots[s->slot-1].saved)) return AF_STORE_STALE;
    if (working) d.saved=c->slots[s->slot-1].working;
    status=af_document_encode(&d,s->schema,output,cap,written);
    return status==AF_DOCUMENT_OK?AF_STORE_OK:status==AF_DOCUMENT_CAPACITY?AF_STORE_CAPACITY:
        status==AF_DOCUMENT_UNSUPPORTED?AF_STORE_UNSUPPORTED:AF_STORE_INVALID;
}
int af_persist_copy(AfCatalog *c,AfStore *source,AfStore *target,const AfStoreIo *source_io,
                    const AfStoreIo *target_io,const AfStoreBuffers *b,
                    const char *name,size_t name_bytes,int overwrite) {
    AfDocument d;
    int status=ready(c,source);
    if (status) return status;
    status=ready(c,target);
    if (status) return status;
    if (source->slot==target->slot) return AF_STORE_INVALID;
    if (!c->slots[source->slot-1].present) return AF_PERSIST_EMPTY;
    status=current_document(source,source_io,b,&d);
    if (status) return status;
    if (!d.present || !same(&d.initial,&c->slots[source->slot-1].initial) ||
        !same(&d.saved,&c->slots[source->slot-1].saved)) return AF_STORE_STALE;
    d.saved=c->slots[source->slot-1].working;d.name=name;d.name_bytes=name_bytes;
    return af_persist_replace(c,target,target_io,b,&d,overwrite);
}
