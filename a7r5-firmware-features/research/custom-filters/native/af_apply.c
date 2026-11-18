#include "af_apply.h"

#define MAGIC 0x41374131u
static int valid(const AfApply *a) { return a && a->magic==MAGIC; }
size_t af_apply_bytes(void) { return sizeof(AfApply); }
int af_apply_init(AfApply *a,uint64_t session,uint32_t required) {
    AfApply next={0};
    if (!a || !session || !required || (required&~AF_APPLY_ALL)) return AF_INVALID;
    if (valid(a)) {
        if (a->pending<AF_APPLY_BANKS) return AF_BUSY;
        for (unsigned i=0;i<AF_APPLY_BANKS;++i) if (a->groups[i].references) return AF_BUSY;
        if (session==a->session) return AF_STALE;
    }
    next.session=session;next.required=required;
    next.active=next.pending=AF_APPLY_BANKS;next.magic=MAGIC;*a=next;
    return AF_OK;
}
int af_apply_negotiate(AfApply *a,const AfApplyPacket *p) {
    if (!valid(a) || !p || p->operation!=AF_APPLY_HELLO || p->version || p->slot ||
        p->required!=a->required) return AF_INVALID;
    for (size_t i=0;i<sizeof(p->preset);++i)
        if (((const uint8_t *)&p->preset)[i]) return AF_INVALID;
    if (p->session!=a->session) return AF_STALE;
    a->negotiated=1;
    return AF_OK;
}
int af_apply_stage(AfApply *a,const AfApplyPacket *p,AfApplyToken *output) {
    AfApplyGroup group={0};
    if (!valid(a) || !p || !output || p->operation!=AF_APPLY_PRESET ||
        p->required!=a->required || !p->version || !p->slot || p->slot>AF_USERS ||
        af_validate(&p->preset)!=AF_OK || p->preset.kind) return AF_INVALID;
    if (p->session!=a->session) return AF_STALE;
    if (!a->negotiated || a->pending<AF_APPLY_BANKS) return AF_BUSY;
    if (a->last_version==UINT64_MAX) return AF_EXHAUSTED;
    if (p->version<=a->last_version) return AF_STALE;
    for (uint32_t i=0;i<AF_APPLY_BANKS;++i) if (i!=a->active && !a->groups[i].references) {
        group.preset=p->preset;group.version=p->version;group.slot=p->slot;
        a->groups[i]=group;a->pending=i;a->last_version=p->version;
        output->session=a->session;output->version=p->version;output->bank=i;
        return AF_OK;
    }
    return AF_BUSY;
}
static int pending(const AfApply *a,const AfApplyToken *t) {
    return valid(a) && t && t->session==a->session && t->bank<AF_APPLY_BANKS &&
        a->pending==t->bank && t->version && a->groups[t->bank].version==t->version;
}
static int overlap(const AfOutputBank *a,const AfOutputBank *b) {
    return a->address<b->address+b->bytes && b->address<a->address+a->bytes;
}
int af_apply_reserve(AfApply *a,const AfApplyToken *t,uint32_t consumer,const AfOutputBank *bank) {
    AfApplyGroup *g;
    uint32_t bit;
    if (!valid(a) || consumer>=AF_APPLY_CONSUMERS) return AF_INVALID;
    bit=1u<<consumer;
    if (!(a->required&bit)) return AF_INVALID;
    if (!pending(a,t)) return AF_STALE;
    g=&a->groups[t->bank];
    if (g->started) return AF_BUSY;
    if (g->reserved&bit) return AF_STALE;
    if (!bank || !bank->address || (bank->address&3u) || !bank->bytes || bank->bytes>0x20000u ||
        bank->address>UINT32_MAX-bank->bytes) return AF_INVALID;
    for (uint32_t i=0;i<AF_APPLY_BANKS;++i) {
        const AfApplyGroup *other=&a->groups[i];
        if (i!=t->bank && i!=a->active && !other->references) continue;
        for (unsigned j=0;j<AF_APPLY_CONSUMERS;++j)
            if ((other->reserved&(1u<<j)) && overlap(bank,&other->outputs[j])) return AF_BUSY;
    }
    g->outputs[consumer]=*bank;g->reserved|=bit;
    return AF_OK;
}
int af_apply_start(AfApply *a,const AfApplyToken *t) {
    AfApplyGroup *g;
    if (!valid(a)) return AF_INVALID;
    if (!pending(a,t)) return AF_STALE;
    g=&a->groups[t->bank];
    if (g->started) return AF_STALE;
    if (g->reserved!=a->required) return AF_BUSY;
    g->started=1;return AF_OK;
}
int af_apply_bank(AfApply *a,const AfApplyToken *t,uint32_t consumer,
                  const AfOutputBank *bank,int succeeded) {
    AfApplyGroup *g;
    uint32_t bit;
    if (!valid(a) || consumer>=AF_APPLY_CONSUMERS || (succeeded!=0 && succeeded!=1)) return AF_INVALID;
    bit=1u<<consumer;
    if (!(a->required&bit)) return AF_INVALID;
    if (!pending(a,t)) return AF_STALE;
    g=&a->groups[t->bank];
    if (!g->started) return AF_BUSY;
    if ((g->ready|g->failed)&bit) return AF_STALE;
    if (!succeeded) { g->failed|=bit;return AF_OK; }
    if (!bank || bank->address!=g->outputs[consumer].address ||
        bank->bytes!=g->outputs[consumer].bytes) return AF_INVALID;
    g->ready|=bit;
    return AF_OK;
}
int af_apply_publish(AfApply *a,const AfApplyToken *t) {
    AfApplyGroup *g;
    if (!valid(a)) return AF_INVALID;
    if (!pending(a,t)) return AF_STALE;
    g=&a->groups[t->bank];
    if (g->failed) return AF_IO;
    if (g->ready!=a->required) return AF_BUSY;
    /* 仅单一事件拥有者执行；帧读取整个集合，不逐个读取外部当前银行指针。 */
    a->active=t->bank;a->pending=AF_APPLY_BANKS;
    return AF_OK;
}
int af_apply_abort(AfApply *a,const AfApplyToken *t) {
    AfApplyGroup *g;
    if (!valid(a)) return AF_INVALID;
    if (!pending(a,t)) return AF_STALE;
    g=&a->groups[t->bank];
    if (g->started && (g->ready|g->failed)!=a->required) return AF_BUSY;
    g->reserved=g->started=g->ready=g->failed=0;a->pending=AF_APPLY_BANKS;
    return AF_OK;
}
int af_apply_frame(AfApply *a,uint32_t outputs,AfApplyLease *output) {
    if (!valid(a) || !output || !outputs || (outputs&AF_APPLY_OWNER)) return AF_INVALID;
    if (a->active>=AF_APPLY_BANKS) return AF_EMPTY;
    if (a->next_lease==UINT64_MAX) return AF_EXHAUSTED;
    for (unsigned i=0;i<AF_APPLY_LEASES;++i) if (!a->frames[i].token.lease) {
        AfApplyFrame frame={0};
        frame.token.session=a->session;frame.token.version=a->groups[a->active].version;
        frame.token.lease=++a->next_lease;frame.token.bank=a->active;
        frame.remaining=outputs|AF_APPLY_OWNER;a->frames[i]=frame;
        ++a->groups[a->active].references;*output=frame.token;
        return AF_OK;
    }
    return AF_BUSY;
}
static int find(const AfApply *a,const AfApplyLease *t) {
    if (!t || t->session!=a->session || !t->lease || t->bank>=AF_APPLY_BANKS ||
        a->groups[t->bank].version!=t->version) return -1;
    for (unsigned i=0;i<AF_APPLY_LEASES;++i) {
        const AfApplyLease *r=&a->frames[i].token;
        if (r->lease==t->lease && r->version==t->version && r->bank==t->bank && r->session==t->session)
            return (int)i;
    }
    return -1;
}
int af_apply_view(const AfApply *a,const AfApplyLease *t,const AfApplyGroup **output) {
    if (!valid(a) || !output) return AF_INVALID;
    if (find(a,t)<0) return AF_STALE;
    *output=&a->groups[t->bank];return AF_OK;
}
static int retire(AfApply *a,const AfApplyLease *t,uint32_t bits) {
    int index;
    AfApplyFrame *f;
    if (!valid(a)) return AF_INVALID;
    index=find(a,t);
    if (index<0) return AF_STALE;
    f=&a->frames[index];
    if ((f->remaining&bits)!=bits) return AF_STALE;
    f->remaining&=~bits;
    if (!f->remaining) { --a->groups[t->bank].references;f->token.lease=0; }
    return AF_OK;
}
int af_apply_retire(AfApply *a,const AfApplyLease *t,uint32_t bits) {
    if (!bits || (bits&AF_APPLY_OWNER)) return AF_INVALID;
    return retire(a,t,bits);
}
int af_apply_owner_end(AfApply *a,const AfApplyLease *t) { return retire(a,t,AF_APPLY_OWNER); }
