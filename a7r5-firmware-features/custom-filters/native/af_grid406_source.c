#include "af_grid406_source.h"
#include "af_sha256.h"
static int apart(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
static int same(const uint8_t *a,const uint8_t *b){
    unsigned d=0;for(unsigned i=0;i<32;++i)d|=a[i]^b[i];return !d;
}
static uint32_t read32(const uint8_t *p){
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static void write32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(v>>(8*i));}
static int key_valid(const AfGrid406Key *k){
    return k&&k->snapshot&&k->root&&k->c4&&k->source&&
        !(k->root&3u)&&!(k->c4&3u)&&!(k->source&3u)&&
        k->root<=UINT32_MAX-32u&&k->c4<=UINT32_MAX-0xc4u&&k->source<=UINT32_MAX-0xe70u;
}
static int key_same(const AfGrid406Key *a,const AfGrid406Key *b){
    return key_valid(a)&&key_valid(b)&&a->snapshot==b->snapshot&&
           a->root==b->root&&a->c4==b->c4&&a->source==b->source;
}
static int table_valid(const AfGrid406Table *t){
    if(!(t&&t->slot>=7&&t->slot<=20&&t->level>=1&&t->level<=8&&
        t->grid_address&&!(t->grid_address&3u)&&t->grid_address<=UINT32_MAX-AF_GRID_BYTES&&
        af_joint_valid(&t->asset.recipe)==AF_OK))return 0;
    /* 不把可变结构旁的旧摘要字段当作内容证明。 */
    uint8_t encoded[AF_JOINT_ASSET_BYTES],digest[32];size_t written=0;
    return af_joint_asset_encode(&t->asset,encoded,sizeof(encoded),&written)==AF_OK&&
        written==sizeof(encoded)&&af_sha256(encoded,written,digest)==AF_OK&&same(digest,t->payload_sha256);
}
int af_grid406_prepare(const AfPreset *p,const void *raw,size_t bytes,
    const uint8_t model[32],uint32_t slot,uint32_t level,uint32_t address,AfGrid406Table *out){
    if(!apart(p,sizeof(*p),out,sizeof(*out))||!apart(raw,bytes,out,sizeof(*out))||
       !apart(model,32,out,sizeof(*out))||af_validate(p)!=AF_OK||p->kind!=1||
       slot<7||slot>20||level<1||level>8||!address||(address&3u)||
       address>UINT32_MAX-AF_GRID_BYTES)return AF_INVALID;
    AfGrid406Table t={0};
    int status=af_joint_asset_decode(raw,bytes,&t.asset);
    if(status!=AF_OK)return status;
    /* 此旧离线适配器只支持1943B；新实际网格入口使用紧凑运行银行。 */
    if(t.asset.matrix_mode)return AF_JOINT_ASSET_UNSUPPORTED;
    if(t.asset.base!=p->base||!same(model,t.asset.model_sha256)||
       af_sha256(raw,bytes,t.payload_sha256)!=AF_OK||!same(p->payload_sha256,t.payload_sha256))return AF_STALE;
    t.slot=slot;t.level=level;t.grid_address=address;*out=t;return AF_OK;
}
int af_grid406_capture(const AfGrid406Table *table,const AfGrid406Key *key,AfGrid406Token *out){
    if(!apart(table,sizeof(*table),out,sizeof(*out))||!apart(key,sizeof(*key),out,sizeof(*out))||
       !table_valid(table)||!key_valid(key))return AF_INVALID;
    AfGrid406Token t={0};t.table=*table;t.key=*key;t.active=1;
    *out=t;return AF_OK;
}
static int token_valid(const AfGrid406Token *t,const AfGrid406Key *key){
    return t&&t->active&&key_same(&t->key,key)&&table_valid(&t->table);
}
int af_grid406_overlay(const AfGrid406Token *t,const AfGrid406Key *key,
    uint32_t mode,uint32_t profile,uint32_t level,uint32_t query_class,
    const void *raw_grid,const void *operation,const void *c4,const void *state,const void *context,
    void *state_out,void *context_out){
    if(!token_valid(t,key))return AF_STALE;
    if(mode||profile||query_class>=4)return AF_JOINT_SKIP;
    if(level!=t->table.level)return AF_STALE;
    const void *inputs[7]={t,key,raw_grid,operation,c4,state,context};
    const size_t lengths[7]={sizeof(*t),sizeof(*key),AF_GRID_BYTES,AF_GRID406_OPERATION_BYTES,
        AF_GRID406_C4_BYTES,AF_GRID406_STATE_BYTES,AF_GRID406_CONTEXT_BYTES};
    for(unsigned i=0;i<7;++i)
        if(!apart(inputs[i],lengths[i],state_out,AF_GRID406_STATE_BYTES)||
           !apart(inputs[i],lengths[i],context_out,AF_GRID406_CONTEXT_BYTES))return AF_INVALID;
    if(!apart(state_out,AF_GRID406_STATE_BYTES,context_out,AF_GRID406_CONTEXT_BYTES))return AF_INVALID;
    /* 原240de2的STRD保存C4到operation+4；grid_state+4是source_class，不能混用。 */
    if(read32((const uint8_t *)operation+4)!=key->c4||read32(c4)!=key->source)return AF_STALE;
    for(unsigned i=0;i<AF_GRID_BYTES;++i)
        if(((const uint8_t *)raw_grid)[i]!=(uint8_t)t->table.asset.recipe.grid[i])return AF_STALE;
    const uint8_t *before=context;
    uint32_t packed=read32(before+0x6b0);
    if(!packed||(packed&3u)||packed>UINT32_MAX-1620u)return AF_JOINT_SKIP;
    uint8_t *a=state_out,*b=context_out;
    for(unsigned i=0;i<AF_GRID406_STATE_BYTES;++i)a[i]=((const uint8_t *)state)[i];
    for(unsigned i=0;i<AF_GRID406_CONTEXT_BYTES;++i)b[i]=before[i];
    write32(a+0x184,t->table.grid_address);a[0x188]=1;a[0x189]=2;
    /* 同地址新内容也必须失效：原判定不读取1215内容摘要。 */
    b[0x54]=255;
    return AF_OK;
}
int af_grid406_finish(AfGrid406Token *t,const AfGrid406Key *key){
    if(!t||!apart(t,sizeof(*t),key,sizeof(*key))||!token_valid(t,key))return AF_STALE;
    t->active=0;return AF_OK;
}
