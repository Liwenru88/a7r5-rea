#include "af_store.h"
#include "af_sha256.h"

size_t af_store_bytes(void) { return sizeof(AfStore); }
static int equal(const uint8_t *a,const uint8_t *b,size_t n) {
    for (size_t i=0;i<n;++i) if (a[i]!=b[i]) return 0;
    return 1;
}
static int separate(const void *a,const void *b,size_t n) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && (x>y?x-y:y-x)>=n;
}
static int valid(const AfStore *s,const AfStoreIo *io,const AfStoreBuffers *b) {
    return s && s->slot>=1 && s->slot<=AF_USERS &&
        s->max_payload>=AF_DOCUMENT_HEADER && s->max_payload<=AF_DOCUMENT_MAX &&
        io && io->read && io->stage && io->sync_data && io->publish &&
        io->sync_directory && io->discard && b &&
        b->capacity>=s->max_payload+AF_RECORD_HEADER &&
        separate(b->a,b->b,b->capacity) && separate(b->a,b->next,b->capacity) &&
        separate(b->b,b->next,b->capacity);
}
int af_store_init(AfStore *s,uint32_t slot,uint32_t schema,size_t max_payload) {
    AfStore next={0};
    if (!s || !slot || slot>AF_USERS || max_payload<AF_DOCUMENT_HEADER || max_payload>AF_DOCUMENT_MAX)
        return AF_STORE_INVALID;
    next.slot=slot;next.schema=schema;next.max_payload=max_payload;
    *s=next;
    return AF_STORE_OK;
}
uint64_t af_store_generation(const AfStore *s) { return s?s->generation:0; }

int af_store_recover(AfStore *s,const AfStoreIo *io,const AfStoreBuffers *b,
                     int allow_empty,AfDocument *output) {
    AfStore next;
    AfRecordView views[2]={{0},{0}};
    AfDocument docs[2]={{0},{0}};
    uint8_t *raw[2];
    size_t sizes[2]={0,0};
    int results[2];
    uint32_t chosen;
    if (!valid(s,io,b) || !output || (allow_empty!=0 && allow_empty!=1)) return AF_STORE_INVALID;
    next=*s;s->ready=0;
    raw[0]=b->a;raw[1]=b->b;
    for (unsigned i=0;i<2;++i) {
        int r=io->read(io->context,s->slot,i,raw[i],s->max_payload+AF_RECORD_HEADER,&sizes[i]);
        if (r==2 || sizes[i]>s->max_payload+AF_RECORD_HEADER) return AF_STORE_CAPACITY;
        if (r!=0 && r!=1) return AF_STORE_IO;
        if (r==1) { results[i]=1;continue; }
        r=af_record_decode(raw[i],sizes[i],s->slot,s->max_payload,&views[i]);
        if (r==AF_RECORD_UNSUPPORTED) return AF_STORE_UNSUPPORTED;
        if (r) { results[i]=-1;continue; }
        r=af_document_decode(views[i].payload,views[i].bytes,s->schema,&docs[i]);
        if (r==AF_DOCUMENT_UNSUPPORTED) return AF_STORE_UNSUPPORTED;
        results[i]=r? -1:0;
    }
    if (results[0] && results[1]) {
        if (results[0]!=1 || results[1]!=1) return AF_STORE_CORRUPT;
        if (allow_empty) {
            next.ready=1;next.uncertain=0;next.generation=0;next.bank=1;
            for (unsigned i=0;i<32;++i) next.digest[i]=0;
            *s=next;
        }
        return AF_STORE_MISSING;
    }
    if (!results[0] && !results[1] && views[0].generation==views[1].generation &&
        (sizes[0]!=sizes[1] || !equal(raw[0],raw[1],sizes[0]))) return AF_STORE_CONFLICT;
    chosen=(!results[0] && (results[1] || views[0].generation>=views[1].generation))?0:1;
    next.bank=chosen;next.generation=views[chosen].generation;next.ready=1;next.uncertain=0;
    (void)af_sha256(raw[chosen],sizes[chosen],next.digest);
    *output=docs[chosen];*s=next;
    return AF_STORE_OK;
}

int af_store_commit(AfStore *s,const AfStoreIo *io,const AfStoreBuffers *b,const AfDocument *d) {
    size_t payload_bytes=0,written=0,read_bytes=0;
    AfStore check;
    AfDocument verified={0};
    uint8_t *raw;
    uint32_t bank;
    int status;
    if (!valid(s,io,b) || !d) return AF_STORE_INVALID;
    if (s->uncertain) return AF_STORE_UNCERTAIN;
    if (!s->ready) return AF_STORE_INVALID;
    if (s->generation==UINT64_MAX) return AF_STORE_EXHAUSTED;
    status=af_document_encode(d,s->schema,b->next,s->max_payload,&payload_bytes);
    if (status) return status==AF_DOCUMENT_UNSUPPORTED?AF_STORE_UNSUPPORTED:
                       status==AF_DOCUMENT_CAPACITY?AF_STORE_CAPACITY:AF_STORE_INVALID;
    check=*s;
    status=af_store_recover(&check,io,b,s->generation==0,&verified);
    if (status!=AF_STORE_OK && status!=AF_STORE_MISSING) { s->ready=0;return status; }
    if (check.generation!=s->generation || check.bank!=s->bank || !equal(check.digest,s->digest,32)) {
        s->ready=0;return AF_STORE_STALE;
    }
    bank=s->bank^1u;raw=bank?b->b:b->a;
    if (af_record_encode(s->slot,s->generation+1,b->next,payload_bytes,s->max_payload,
                         raw,b->capacity,&written)) return AF_STORE_INVALID;
    if (io->stage(io->context,s->slot,bank,raw,written) ||
        io->sync_data(io->context,s->slot,bank)) {
        (void)io->discard(io->context,s->slot,bank);
        return AF_STORE_IO;
    }
    /* publish的错误也可能来自成功改名之后，先冻结，再等待全部证据。 */
    s->uncertain=1;s->ready=0;
    if (io->publish(io->context,s->slot,bank) || io->sync_directory(io->context,s->slot,bank) ||
        io->read(io->context,s->slot,bank,b->next,s->max_payload+AF_RECORD_HEADER,&read_bytes) ||
        read_bytes!=written || !equal(raw,b->next,written)) {
        (void)io->discard(io->context,s->slot,bank);
        return AF_STORE_UNCERTAIN;
    }
    /* 逐字节相等后仍按完整格式验证，成功才发布下一代。 */
    {
        AfRecordView view;
        if (af_record_decode(b->next,read_bytes,s->slot,s->max_payload,&view) ||
            af_document_decode(view.payload,view.bytes,s->schema,&verified)) return AF_STORE_UNCERTAIN;
    }
    ++s->generation;s->bank=bank;s->ready=1;s->uncertain=0;
    (void)af_sha256(b->next,read_bytes,s->digest);
    return AF_STORE_OK;
}

static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
int af_store_snapshot(const AfStore *s,const AfStoreBuffers *b,AfDocument *output) {
    if (!s || !b || !s->slot || s->slot>AF_USERS ||
        s->max_payload<AF_DOCUMENT_HEADER || s->max_payload>AF_DOCUMENT_MAX ||
        b->capacity<s->max_payload+AF_RECORD_HEADER ||
        !apart(s,sizeof(*s),output,sizeof(*output)) || !apart(b,sizeof(*b),output,sizeof(*output)) ||
        !apart(b->a,b->capacity,b->b,b->capacity) ||
        !apart(b->a,b->capacity,b->next,b->capacity) ||
        !apart(b->b,b->capacity,b->next,b->capacity)) return AF_STORE_INVALID;
    const uint8_t *raw[3]={b->a,b->b,b->next};
    for (unsigned i=0;i<3;++i)
        if (!apart(raw[i],b->capacity,output,sizeof(*output))) return AF_STORE_INVALID;
    if (s->uncertain) return AF_STORE_UNCERTAIN;
    if (!s->ready) return AF_STORE_INVALID;
    if (!s->generation) return AF_STORE_MISSING;
    for (unsigned i=0;i<3;++i) {
        const uint8_t *p=raw[i];
        size_t count=(uint32_t)p[16]|(uint32_t)p[17]<<8|(uint32_t)p[18]<<16|(uint32_t)p[19]<<24;
        if (count<AF_DOCUMENT_HEADER || count>s->max_payload || count>b->capacity-AF_RECORD_HEADER) continue;
        count+=AF_RECORD_HEADER;
        uint8_t hash[32];AfRecordView view;AfDocument document;
        if (af_sha256(p,count,hash) || !equal(hash,s->digest,32)) continue;
        if (af_record_decode(p,count,s->slot,s->max_payload,&view) || view.generation!=s->generation)
            return AF_STORE_STALE;
        if (af_document_decode(view.payload,view.bytes,s->schema,&document)) return AF_STORE_CORRUPT;
        *output=document;return AF_STORE_OK;
    }
    return AF_STORE_STALE;
}
