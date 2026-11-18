/* 重读只影响可复用文件缓冲；事务输出始终拥有自己的完整副本。 */
#include "af_repository_recipe.h"
#include "af_persist.h"
static int apart(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
static int same(const void *a,const void *b,size_t n){
    const uint8_t *x=a,*y=b;unsigned difference=0;
    for(size_t i=0;i<n;++i)difference|=x[i]^y[i];return !difference;
}
static int preset_same(const AfPreset *a,const AfPreset *b){
    return a->base==b->base&&a->kind==b->kind&&same(a->params,b->params,8)&&
        same(a->payload_sha256,b->payload_sha256,32)&&same(a->lut_sha256,b->lut_sha256,32);
}
static int content_same(const AfPreset *a,const AfPreset *b){
    return a->base==b->base&&a->kind==b->kind&&same(a->payload_sha256,b->payload_sha256,32)&&
        same(a->lut_sha256,b->lut_sha256,32);
}
static int store_same(const AfStore *a,const AfStore *b){
    return a->slot==b->slot&&a->schema==b->schema&&a->bank==b->bank&&a->ready==b->ready&&
        a->uncertain==b->uncertain&&a->max_payload==b->max_payload&&a->generation==b->generation&&
        same(a->digest,b->digest,32);
}
static int independent(const AfRepository *r,const AfRecipeTx *out){
    if(!r||!r->catalog||!r->labels||!r->buffers.capacity)return 0;
    const void *p[]={r,r->catalog,r->labels,r->buffers.a,r->buffers.b,r->buffers.next};
    const size_t n[]={sizeof(*r),sizeof(*r->catalog),sizeof(*r->labels),r->buffers.capacity,r->buffers.capacity,r->buffers.capacity};
    for(unsigned i=0;i<6;++i){
        if(!apart(out,sizeof(*out),p[i],n[i]))return 0;
        for(unsigned j=0;j<i;++j)if(!apart(p[i],n[i],p[j],n[j]))return 0;
    }
    return 1;
}
static int ready(const AfRepository *r,uint32_t slot,uint64_t revision){
    if(!r||!r->catalog||!r->labels||slot<1||slot>AF_USERS||!revision)return AF_STORE_INVALID;
    if(!r->opened)return AF_STORE_STALE;
    if(r->schema!=AF_JOINT_ASSET_SCHEMA)return AF_STORE_UNSUPPORTED;
    const AfSlot *s=&r->catalog->slots[slot-1];const AfStore *store=&r->stores[slot-1];
    uint32_t bit=1u<<(slot-1);
    if(store->uncertain)return AF_STORE_UNCERTAIN;
    if(!store->ready||!(r->ready_mask&bit)||(r->error_mask&bit)||r->status[slot-1]!=AF_STORE_OK||
       store->slot!=slot||store->schema!=r->schema||store->generation!=revision||
       s->saved_revision!=revision||!s->present)return AF_STORE_STALE;
    if(s->pending.request)return AF_PERSIST_BUSY;
    if(af_validate(&s->initial)!=AF_OK||af_validate(&s->saved)!=AF_OK||af_validate(&s->working)!=AF_OK)
        return AF_STORE_INVALID;
    if(s->initial.kind!=1||s->saved.kind!=1||s->working.kind!=1)return AF_STORE_UNSUPPORTED;
    if(!content_same(&s->initial,&s->saved)||!content_same(&s->saved,&s->working))return AF_STORE_STALE;
    return AF_STORE_OK;
}
static uint32_t u32(const uint8_t *p){
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static int document_matches(const AfDocument *d,const AfSlot *s){
    if(d->present!=1||d->schema!=AF_JOINT_ASSET_SCHEMA||(d->converter<1||d->converter>3)||!af_joint_asset_size_valid(d->image_bytes)||
       !d->image||!preset_same(&d->initial,&s->initial)||!preset_same(&d->saved,&s->saved))return AF_STORE_STALE;
    const uint8_t *p=d->image;
    /* AFD1已校验完整图像SHA；这里核强制头与模型身份，完整组件另在Rx验证。 */
    unsigned sector=p[3]=='3'&&p[4]==3,native=sector||(p[3]=='2'&&p[4]==2);
    if(p[0]!='A'||p[1]!='J'||p[2]!='R'||(!native&&(p[3]!='1'||p[4]!=1))||
       d->converter!=(sector?3u:native?2u:1u)||p[5]||p[6]!=128||p[7]||
       d->image_bytes!=(sector?AF_JOINT_SECTOR_BYTES:AF_JOINT_ASSET_BYTES)||
       u32(p+8)!=d->image_bytes-128u||u32(p+12)!=(sector?15u:native?7u:3u)||u32(p+16)!=s->saved.base||
       u32(p+20)!=1||u32(p+24)!=15||u32(p+28)||!same(p+32,af_joint_cp_sha256,32)||
       !same(p+64,d->report.model_sha256,32))return AF_STORE_CORRUPT;
    /* 旧格式仍可恢复/导出；应用前拒绝原单色9项矩阵无法表达的三端点。
     * payload可能未对齐，以字节比较避免把name后的原像强转为半字数组。 */
    if(native&&af_joint_matrix_native406_bytes_representable(s->saved.base,sector,
        p+AF_JOINT_ASSET_HEADER+516u,sector?576u:36u)!=AF_OK)return AF_STORE_UNSUPPORTED;
    return AF_STORE_OK;
}
int af_repository_recipe_capture(const AfRepository *r,uint32_t slot,uint64_t revision,
    uint64_t session,uint64_t version,AfRecipeTx *out){
    if(!session||!version||!independent(r,out))return AF_STORE_INVALID;
    int status=ready(r,slot,revision);if(status!=AF_STORE_OK)return status;
    AfSlot snapshot=r->catalog->slots[slot-1];AfStore expected=r->stores[slot-1],check=expected;AfDocument document;
    /* 不调用repository_recover：它会重置working并改目录。 */
    status=af_store_recover(&check,&r->io,&r->buffers,0,&document);
    if(status!=AF_STORE_OK)return status==AF_STORE_MISSING?AF_STORE_STALE:status;
    if(!store_same(&check,&expected))return AF_STORE_STALE;
    status=ready(r,slot,revision);if(status!=AF_STORE_OK)return status;
    const AfSlot *current=&r->catalog->slots[slot-1];
    if(!store_same(&r->stores[slot-1],&expected)||!preset_same(&current->initial,&snapshot.initial)||
       !preset_same(&current->saved,&snapshot.saved)||!preset_same(&current->working,&snapshot.working))return AF_STORE_STALE;
    status=document_matches(&document,&snapshot);if(status!=AF_STORE_OK)return status;
    /* 唯一输出发布点；tx_init再次核完整payload SHA，并复制所有图像字节。 */
    return af_recipe_tx_init(out,session,version,slot,&snapshot.working,document.image,document.image_bytes)==AF_OK?
        AF_STORE_OK:AF_STORE_INVALID;
}
int af_repository_recipe_current(const AfRepository *r,const AfRecipeTx *t,uint64_t revision){
    uint8_t frame[128];
    if(!independent(r,t)||af_recipe_tx_frame(t,0,frame,sizeof(frame))!=AF_OK)return AF_STORE_INVALID;
    int status=ready(r,t->message.slot,revision);
    if(status!=AF_STORE_OK)return status==AF_STORE_UNCERTAIN?status:AF_STORE_STALE;
    return preset_same(&r->catalog->slots[t->message.slot-1].working,&t->message.preset)?AF_STORE_OK:AF_STORE_STALE;
}
