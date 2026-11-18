/* 收包、验证和软件提交分开；所有已借出对象均有唯一、不可重放的租约。 */
#include "af_recipe_transport.h"
#include "af_sha256.h"
#define TX_MAGIC 0x31585452u
#define RX_MAGIC 0x31585252u
typedef struct {uint64_t session,version;uint32_t operation,slot,offset,length;
#ifndef AF_JOINT_ASSET_LEGACY_ONLY406
    uint32_t total,capabilities;
#endif
    int status;} Frame;
static uint32_t frame_total(const Frame *f){
#ifdef AF_JOINT_ASSET_LEGACY_ONLY406
    (void)f;return AF_JOINT_ASSET_BYTES;
#else
    return f->total;
#endif
}
static uint32_t frame_capabilities(const Frame *f){
#ifdef AF_JOINT_ASSET_LEGACY_ONLY406
    (void)f;return AF_RECIPE_CAP_FULL;
#else
    return f->capabilities;
#endif
}
static int apart(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
static int same(const uint8_t *a,const uint8_t *b,unsigned n){
    unsigned d=0;for(unsigned i=0;i<n;++i)d|=a[i]^b[i];return !d;
}
static uint32_t u32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint64_t u64(const uint8_t *p){return (uint64_t)u32(p)|((uint64_t)u32(p+4)<<32);}
static void put32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(v>>(8*i));}
static void put64(uint8_t *p,uint64_t v){put32(p,(uint32_t)v);put32(p+4,(uint32_t)(v>>32));}
static uint32_t crc(const uint8_t *p){
    uint32_t c=UINT32_MAX;
    for(unsigned i=0;i<124;++i){c^=p[i];for(unsigned j=0;j<8;++j)c=(c>>1)^(0xedb88320u&(0u-(c&1u)));}
    return ~c;
}
static int slot_valid(uint32_t slot){return slot>=1&&slot<=AF_USERS;}
static uint32_t message_size(const AfRecipeMessage *m){
#ifdef AF_JOINT_ASSET_LEGACY_ONLY406
    (void)m;return AF_JOINT_ASSET_BYTES;
#else
    return m->image_bytes;
#endif
}
static int data_offset_valid(uint32_t offset){
    /* 最多26次定长比较，避免紧凑Thumb的余数运算引入未知运行库调用。 */
    uint32_t at=0;
    for(unsigned i=0;i<AF_RECIPE_MAX_DATA_FRAMES;++i,at+=AF_RECIPE_DATA_BYTES)
        if(offset==at)return 1;
    return 0;
}
static int rx_valid(const AfRecipeRx *r){
    return r&&r->magic==RX_MAGIC&&r->session&&(r->capabilities==AF_RECIPE_CAP_FULL||(AF_JOINT_SECTOR_SUPPORTED&&r->capabilities==3u))&&
        r->receiving<=AF_RECIPE_NONE&&r->active<=AF_RECIPE_NONE&&r->offset<=AF_JOINT_ASSET_MAX_BYTES;
}
static void header(uint8_t raw[128],const AfRecipeMessage *m,unsigned operation,unsigned offset,unsigned length,int status){
    for(unsigned i=0;i<128;++i)raw[i]=0;
    raw[0]='A';raw[1]='7';raw[2]='R';raw[3]='1';raw[4]=1;raw[5]=(uint8_t)operation;raw[6]=48;
    put32(raw+8,message_size(m));put32(raw+12,m->slot);
    put64(raw+16,m->session);put64(raw+24,m->version);put32(raw+32,offset);
    raw[36]=(uint8_t)length;raw[37]=(uint8_t)(length>>8);
    raw[38]=(uint8_t)status;raw[39]=(uint8_t)((uint16_t)status>>8);
    put32(raw+40,AF_JOINT_SECTOR_SUPPORTED&&m->image_bytes==AF_JOINT_SECTOR_BYTES?3u:AF_RECIPE_CAP_FULL);
}
static int parse(const void *input,size_t bytes,Frame *out){
    const uint8_t *p=input;Frame f;
    if(!p||bytes!=128||p[0]!='A'||p[1]!='7'||p[2]!='R'||p[3]!='1'||p[4]!=1||p[6]!=48||p[7]||
       !af_joint_asset_size_valid(u32(p+8))||u32(p+40)!=(AF_JOINT_SECTOR_SUPPORTED&&u32(p+8)==AF_JOINT_SECTOR_BYTES?3u:AF_RECIPE_CAP_FULL)||
       u32(p+44)||u32(p+124)!=crc(p))return AF_INVALID;
#ifndef AF_JOINT_ASSET_LEGACY_ONLY406
    f.total=u32(p+8);f.capabilities=u32(p+40);
#endif
    f.operation=p[5];f.slot=u32(p+12);f.session=u64(p+16);f.version=u64(p+24);f.offset=u32(p+32);
    f.length=(unsigned)p[36]|(unsigned)p[37]<<8;
    unsigned status=(unsigned)p[38]|(unsigned)p[39]<<8;f.status=status<32768?(int)status:(int)status-65536;
    if(!f.session||!f.version||!slot_valid(f.slot)||f.length>76)return AF_INVALID;
    for(unsigned i=48+f.length;i<124;++i)if(p[i])return AF_INVALID;
    if(f.operation==AF_RECIPE_BEGIN){if(f.offset||f.length!=76||f.status)return AF_INVALID;}
    else if(f.operation==AF_RECIPE_DATA){
        if(f.offset>=frame_total(&f)||!data_offset_valid(f.offset)||f.status)return AF_INVALID;
        unsigned left=frame_total(&f)-f.offset;
        if(f.length!=(left<76?left:76))return AF_INVALID;
    }else if(f.operation==AF_RECIPE_END){if(f.offset!=frame_total(&f)||f.length||f.status)return AF_INVALID;}
    else if(f.operation==AF_RECIPE_ACK){if(f.offset||f.length!=32||f.status>0)return AF_INVALID;}
    else return AF_INVALID;
    *out=f;return AF_OK;
}
size_t af_recipe_tx_bytes(void){return sizeof(AfRecipeTx);}
size_t af_recipe_rx_bytes(void){return sizeof(AfRecipeRx);}
size_t af_recipe_decode_work_bytes(void){return sizeof(AfJointAssetDecodeWork);}
int af_recipe_tx_init(AfRecipeTx *t,uint64_t session,uint64_t version,uint32_t slot,
    const AfPreset *p,const void *image,size_t bytes){
    uint8_t digest[32];
    if(!t||!session||!version||!slot_valid(slot)||af_validate(p)!=AF_OK||p->kind!=1||!af_joint_asset_size_valid(bytes)||
       !apart(t,sizeof(*t),p,sizeof(*p))||!apart(t,sizeof(*t),image,bytes)||
       af_sha256(image,bytes,digest)||!same(digest,p->payload_sha256,32))return AF_INVALID;
    t->message.session=session;t->message.version=version;t->message.slot=slot;t->message.preset=*p;
    t->message.image_bytes=(uint32_t)bytes;
    for(unsigned i=0;i<AF_JOINT_ASSET_MAX_BYTES;++i)t->message.image[i]=i<bytes?((const uint8_t *)image)[i]:0;
    t->magic=TX_MAGIC;return AF_OK;
}
int af_recipe_tx_frame(const AfRecipeTx *t,uint32_t ordinal,void *output,size_t bytes){
    uint8_t raw[128];
    uint32_t frames=af_recipe_tx_frames(t);
    if(!frames||ordinal>=frames||bytes<128||
       !apart(t,sizeof(*t),output,128))return AF_INVALID;
    const AfRecipeMessage *m=&t->message;
    if(ordinal==0){
        header(raw,m,AF_RECIPE_BEGIN,0,76,0);raw[48]=m->preset.base;raw[49]=1;
        for(unsigned i=0;i<8;++i)raw[50+i]=(uint8_t)m->preset.params[i];
        for(unsigned i=0;i<32;++i){raw[60+i]=m->preset.payload_sha256[i];raw[92+i]=m->preset.lut_sha256[i];}
    }else if(ordinal==frames-1)header(raw,m,AF_RECIPE_END,message_size(m),0,0);
    else{
        unsigned offset=(ordinal-1)*76,left=message_size(m)-offset,n=left<76?left:76;
        header(raw,m,AF_RECIPE_DATA,offset,n,0);
        for(unsigned i=0;i<n;++i)raw[48+i]=m->image[offset+i];
    }
    put32(raw+124,crc(raw));for(unsigned i=0;i<128;++i)((uint8_t *)output)[i]=raw[i];return AF_OK;
}
uint32_t af_recipe_tx_frames(const AfRecipeTx *t){
    if(!t||t->magic!=TX_MAGIC||!af_joint_asset_size_valid(message_size(&t->message)))return 0;
    return AF_JOINT_SECTOR_SUPPORTED&&t->message.image_bytes==AF_JOINT_SECTOR_BYTES?AF_RECIPE_MAX_TOTAL_FRAMES:AF_RECIPE_TOTAL_FRAMES;
}
int af_recipe_rx_init(AfRecipeRx *r,uint64_t session,uint32_t caps){
    if(!r||!session||(caps!=AF_RECIPE_CAP_FULL&&(!AF_JOINT_SECTOR_SUPPORTED||caps!=3u)))return AF_INVALID;
    if(r->magic)return AF_BUSY;
    for(size_t i=0;i<sizeof(*r);++i)((uint8_t *)r)[i]=0;
    r->session=session;r->capabilities=caps;r->receiving=r->active=AF_RECIPE_NONE;r->magic=RX_MAGIC;return AF_OK;
}
int af_recipe_rx_frame(AfRecipeRx *r,const void *input,size_t bytes){
    Frame f;const uint8_t *p=input;AfRecipeOwned *o;
    if(!rx_valid(r)||!apart(r,sizeof(*r),input,bytes)||parse(input,bytes,&f)!=AF_OK||f.operation==AF_RECIPE_ACK)return AF_INVALID;
    if(AF_JOINT_SECTOR_SUPPORTED&&(frame_capabilities(&f)&~r->capabilities))return AF_JOINT_ASSET_UNSUPPORTED;
    if(f.session!=r->session)return AF_STALE;
    if(f.operation==AF_RECIPE_BEGIN){
        AfPreset preset={0};unsigned bank=AF_RECIPE_NONE;
        if(f.version<=r->seen_version)return AF_STALE;
        if(r->receiving!=AF_RECIPE_NONE)return AF_BUSY;
        for(unsigned i=0;i<2;++i)if(r->buffers[i].state==AF_RECIPE_FREE){bank=i;break;}
        if(bank==AF_RECIPE_NONE)return AF_EXHAUSTED;
        if(p[58]||p[59])return AF_INVALID;
        preset.base=p[48];preset.kind=p[49];for(unsigned i=0;i<8;++i)preset.params[i]=(int8_t)p[50+i];
        for(unsigned i=0;i<32;++i){preset.payload_sha256[i]=p[60+i];preset.lut_sha256[i]=p[92+i];}
        if(preset.kind!=1||af_validate(&preset)!=AF_OK)return AF_INVALID;
        o=&r->buffers[bank];o->message.session=f.session;o->message.version=f.version;o->message.slot=f.slot;
        o->message.preset=preset;o->message.image_bytes=frame_total(&f);o->references=0;o->state=AF_RECIPE_RECEIVING;
        r->receiving=bank;r->offset=0;r->seen_version=f.version;r->rejected_valid=0;return AF_OK;
    }
    if(r->receiving==AF_RECIPE_NONE)return AF_STALE;
    o=&r->buffers[r->receiving];
    if(o->message.version!=f.version||o->message.slot!=f.slot||message_size(&o->message)!=frame_total(&f))return AF_STALE;
    if(o->state!=AF_RECIPE_RECEIVING)return AF_BUSY;
    if(f.offset!=r->offset)return AF_STALE;
    if(f.operation==AF_RECIPE_DATA){
        for(unsigned i=0;i<f.length;++i)o->message.image[r->offset+i]=p[48+i];
        r->offset+=f.length;return AF_OK;
    }
    if(r->offset!=message_size(&o->message))return AF_INVALID;
    o->state=AF_RECIPE_COMPLETE;return AF_OK;
}
int af_recipe_rx_validate(AfRecipeRx *r,AfJointAssetDecodeWork *work){
    uint8_t digest[32];
    if(!rx_valid(r)||!apart(r,sizeof(*r),work,sizeof(*work)))return AF_INVALID;
    if(r->receiving==AF_RECIPE_NONE)return AF_EMPTY;
    AfRecipeOwned *o=&r->buffers[r->receiving];
    if(o->state!=AF_RECIPE_COMPLETE)return AF_BUSY;
    int status=af_sha256(o->message.image,message_size(&o->message),digest);
    if(status||!same(digest,o->message.preset.payload_sha256,32))status=AF_INVALID;
    else status=af_joint_asset_decode_work(o->message.image,message_size(&o->message),work,&o->asset);
    if(status==AF_OK&&o->asset.base!=o->message.preset.base)status=AF_STALE;
    if(status!=AF_OK){
        r->rejected.session=o->message.session;r->rejected.version=o->message.version;
        r->rejected.slot=o->message.slot;r->rejected.status=status;
        for(unsigned i=0;i<32;++i)r->rejected.payload_sha256[i]=o->message.preset.payload_sha256[i];
        r->rejected_bytes=message_size(&o->message);
        r->rejected_valid=1;o->state=AF_RECIPE_FREE;r->receiving=AF_RECIPE_NONE;return status;
    }
    o->state=AF_RECIPE_READY;return AF_OK;
}
int af_recipe_rx_rejection(const AfRecipeRx *r,void *output,size_t bytes){
    uint8_t raw[128];
    if(!rx_valid(r)||bytes<128||!apart(r,sizeof(*r),output,128))return AF_INVALID;
    if(!r->rejected_valid)return AF_EMPTY;
    /* 只需要身份头，避免在栈分配完整AfRecipeMessage。 */
    for(unsigned i=0;i<128;++i)raw[i]=0;
    raw[0]='A';raw[1]='7';raw[2]='R';raw[3]='1';raw[4]=1;raw[5]=AF_RECIPE_ACK;raw[6]=48;
    put32(raw+8,r->rejected_bytes);put32(raw+12,r->rejected.slot);
    put64(raw+16,r->rejected.session);put64(raw+24,r->rejected.version);raw[36]=32;
    raw[38]=(uint8_t)r->rejected.status;raw[39]=(uint8_t)((uint16_t)r->rejected.status>>8);
    put32(raw+40,AF_JOINT_SECTOR_SUPPORTED&&r->rejected_bytes==AF_JOINT_SECTOR_BYTES?3u:AF_RECIPE_CAP_FULL);
    for(unsigned i=0;i<32;++i)raw[48+i]=r->rejected.payload_sha256[i];put32(raw+124,crc(raw));
    for(unsigned i=0;i<128;++i)((uint8_t *)output)[i]=raw[i];return AF_OK;
}
static int issue(AfRecipeRx *r,unsigned bank,AfRecipeLease *lease,const AfRecipeOwned **value){
    if(!apart(r,sizeof(*r),lease,sizeof(*lease))||!apart(r,sizeof(*r),value,sizeof(*value))||
       !apart(lease,sizeof(*lease),value,sizeof(*value)))return AF_INVALID;
    unsigned index=AF_RECIPE_LEASES;
    if(r->next_lease==UINT64_MAX||r->buffers[bank].references==UINT32_MAX)return AF_EXHAUSTED;
    for(unsigned i=0;i<AF_RECIPE_LEASES;++i)if(!r->leases[i].lease){index=i;break;}
    if(index==AF_RECIPE_LEASES)return AF_EXHAUSTED;
    uint64_t id=r->next_lease+1;
    *lease=(AfRecipeLease){r->session,r->buffers[bank].message.version,id,bank};
    *value=&r->buffers[bank];r->leases[index]=(AfRecipeReference){id,bank};
    r->next_lease=id;++r->buffers[bank].references;return AF_OK;
}
int af_recipe_rx_take(AfRecipeRx *r,AfRecipeLease *lease,const AfRecipeOwned **out){
    if(!rx_valid(r))return AF_INVALID;
    if(r->receiving==AF_RECIPE_NONE)return AF_EMPTY;
    AfRecipeOwned *o=&r->buffers[r->receiving];if(o->state!=AF_RECIPE_READY)return AF_BUSY;
    int status=issue(r,r->receiving,lease,out);
    if(status==AF_OK){o->state=AF_RECIPE_TAKEN;r->owner=lease->lease;}
    return status;
}
static int lease_index(const AfRecipeRx *r,const AfRecipeLease *t){
    if(!t||t->bank>=2||t->session!=r->session||!t->lease||
       t->version!=r->buffers[t->bank].message.version)return -1;
    for(unsigned i=0;i<AF_RECIPE_LEASES;++i)
        if(r->leases[i].lease==t->lease&&r->leases[i].bank==t->bank)return (int)i;
    return -1;
}
int af_recipe_rx_finish(AfRecipeRx *r,const AfRecipeLease *lease,int decision,void *output,size_t bytes){
    uint8_t raw[128];
    if(!rx_valid(r)||!apart(r,sizeof(*r),lease,sizeof(*lease))||
       !apart(r,sizeof(*r),output,128)||!apart(lease,sizeof(*lease),output,128)||bytes<128||decision>0||decision< -32768)return AF_INVALID;
    if(lease_index(r,lease)<0||r->receiving!=lease->bank||r->owner!=lease->lease)return AF_STALE;
    AfRecipeOwned *o=&r->buffers[lease->bank];if(o->state!=AF_RECIPE_TAKEN)return AF_STALE;
    header(raw,&o->message,AF_RECIPE_ACK,0,32,decision);
    for(unsigned i=0;i<32;++i)raw[48+i]=o->message.preset.payload_sha256[i];put32(raw+124,crc(raw));
    if(decision==AF_OK){
        if(r->active!=AF_RECIPE_NONE){
            AfRecipeOwned *old=&r->buffers[r->active];old->state=old->references?AF_RECIPE_RETIRED:AF_RECIPE_FREE;
        }
        r->active=lease->bank;r->committed_version=lease->version;o->state=AF_RECIPE_ACTIVE;
    }else o->state=AF_RECIPE_RETIRED;
    r->receiving=AF_RECIPE_NONE;r->owner=0;
    for(unsigned i=0;i<128;++i)((uint8_t *)output)[i]=raw[i];return AF_OK;
}
int af_recipe_rx_acquire(AfRecipeRx *r,AfRecipeLease *lease,const AfRecipeOwned **out){
    if(!rx_valid(r))return AF_INVALID;
    if(r->active==AF_RECIPE_NONE)return AF_EMPTY;
    return issue(r,r->active,lease,out);
}
int af_recipe_rx_release(AfRecipeRx *r,const AfRecipeLease *lease){
    if(!rx_valid(r)||!apart(r,sizeof(*r),lease,sizeof(*lease)))return AF_INVALID;
    int index=lease_index(r,lease);if(index<0)return AF_STALE;
    AfRecipeOwned *o=&r->buffers[lease->bank];
    if(o->state==AF_RECIPE_TAKEN)return AF_BUSY;
    if(!o->references)return AF_STALE;
    r->leases[index].lease=0;--o->references;
    if(o->state==AF_RECIPE_RETIRED&&!o->references)o->state=AF_RECIPE_FREE;
    return AF_OK;
}
int af_recipe_rx_cancel(AfRecipeRx *r){
    if(!rx_valid(r))return AF_INVALID;
    if(r->receiving==AF_RECIPE_NONE)return AF_EMPTY;
    AfRecipeOwned *o=&r->buffers[r->receiving];if(o->state==AF_RECIPE_TAKEN)return AF_BUSY;
    o->state=AF_RECIPE_FREE;r->receiving=AF_RECIPE_NONE;return AF_OK;
}
int af_recipe_ack_decode(const void *input,size_t bytes,AfRecipeAck *out){
    Frame f;AfRecipeAck next={0};const uint8_t *p=input;
    if(!apart(input,bytes,out,sizeof(*out))||parse(input,bytes,&f)!=AF_OK||f.operation!=AF_RECIPE_ACK)return AF_INVALID;
    next.session=f.session;next.version=f.version;next.slot=f.slot;next.status=f.status;
    for(unsigned i=0;i<32;++i)next.payload_sha256[i]=p[48+i];
    *out=next;return AF_OK;
}
int af_recipe_tx_ack(const AfRecipeTx *t,const void *input,size_t bytes,AfRecipeAck *out){
    AfRecipeAck next;
    if(!t||t->magic!=TX_MAGIC||!apart(t,sizeof(*t),out,sizeof(*out))||
       !apart(input,bytes,out,sizeof(*out))||af_recipe_ack_decode(input,bytes,&next)!=AF_OK)return AF_INVALID;
    if(u32((const uint8_t *)input+8)!=message_size(&t->message)||next.session!=t->message.session||next.version!=t->message.version||next.slot!=t->message.slot||
       !same(next.payload_sha256,t->message.preset.payload_sha256,32))return AF_STALE;
    *out=next;return AF_OK;
}
