/* 这里只拥有完整配方与软件决定；真正CP表生成、原子切换和帧退役由消费者负责。 */
#include "af_cp_recipe406.h"

typedef struct {
    AfCpRecipe406Config config;
    AfRecipeRx receiver;
    AfJointAssetDecodeWork decode;
    AfRecipeLease pending_lease;
    const AfRecipeOwned *pending;
    uint8_t reply[AF_RECIPE_FRAME_BYTES];
    int last_result,last_send;
} Owner;
static Owner *owner;

static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
static uint32_t u32(const uint8_t *p) {
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static uint64_t version(const uint8_t *p) {
    /* 只使用固定32位移位，避免紧凑Thumb引入未证明的__aeabi_llsl。 */
    return (uint64_t)u32(p+24)|((uint64_t)u32(p+28)<<32);
}
static int config_valid(const AfCpRecipe406Config *c) {
    if(!c||!c->handshake||!c->input_version||!c->input_slot||!c->input_fault||
       !c->allocate||!c->release||!c->send||!c->consume||
       (uintptr_t)c->handshake%_Alignof(AfHandshake)||
       (uintptr_t)c->input_version%_Alignof(uint64_t)||
       (uintptr_t)c->input_slot%_Alignof(uint32_t)||
       (uintptr_t)c->input_fault%_Alignof(uint32_t))return 0;
    return apart(c->handshake,sizeof(*c->handshake),c->input_version,sizeof(*c->input_version))&&
        apart(c->handshake,sizeof(*c->handshake),c->input_slot,sizeof(*c->input_slot))&&
        apart(c->handshake,sizeof(*c->handshake),c->input_fault,sizeof(*c->input_fault))&&
        apart(c->input_version,sizeof(*c->input_version),c->input_slot,sizeof(*c->input_slot))&&
        apart(c->input_version,sizeof(*c->input_version),c->input_fault,sizeof(*c->input_fault))&&
        apart(c->input_slot,sizeof(*c->input_slot),c->input_fault,sizeof(*c->input_fault));
}
size_t af_cp_recipe406_owner_bytes(void){return sizeof(Owner);}
int af_cp_recipe406_bind(const AfCpRecipe406Config *config) {
    if(owner)return AF_BUSY;
    if(!config_valid(config))return AF_INVALID;
    AfCpRecipe406Config c=*config;
    if(c.handshake->state||*c.input_version||*c.input_slot||*c.input_fault)return AF_BUSY;
    Owner *next=c.allocate(c.context,sizeof(*next));
    if(!next)return AF_EXHAUSTED;
    if((uintptr_t)next%_Alignof(Owner)||!apart(next,sizeof(*next),config,sizeof(*config))||
       !apart(next,sizeof(*next),c.handshake,sizeof(*c.handshake))||
       !apart(next,sizeof(*next),c.input_version,sizeof(*c.input_version))||
       !apart(next,sizeof(*next),c.input_slot,sizeof(*c.input_slot))||
       !apart(next,sizeof(*next),c.input_fault,sizeof(*c.input_fault))) {
        c.release(c.context,next);return AF_INVALID;
    }
    for(size_t i=0;i<sizeof(*next);++i)((uint8_t *)next)[i]=0;
    next->config=c;next->last_result=AF_EMPTY;owner=next;return AF_OK;
}
int af_cp_recipe406_unbind(void) {
    if(!owner)return AF_EMPTY;
    if(owner->config.handshake->state||owner->receiver.magic)return AF_BUSY;
    AfCpRecipe406Config c=owner->config;Owner *old=owner;owner=0;
    c.release(c.context,old);return AF_OK;
}
int af_cp_recipe406_ready(const AfHandshake *handshake) {
    return owner&&owner->config.handshake==handshake&&config_valid(&owner->config)&&
        !*owner->config.input_fault;
}
uint64_t af_cp_recipe406_seen_version(void){return owner?owner->receiver.seen_version:0;}
int af_cp_recipe406_busy(void) {
    return owner&&(owner->pending||(owner->receiver.magic&&owner->receiver.receiving!=AF_RECIPE_NONE));
}
#ifdef AF_CP_NATIVE406
int af_cp_recipe406_cancel_partial(uint64_t session,uint64_t next_version){
    Owner *o=owner;
    if(!o)return AF_EMPTY;
    AfHandshake *h=o->config.handshake;
    if(h->state!=5||!session||h->session!=session||!(h->required&AF_APPLY_CAP_USER20))return AF_INVALID;
    if(*o->config.input_fault)return AF_IO;
    if(next_version<=*o->config.input_version||next_version<=o->receiver.seen_version)return AF_STALE;
    if(o->pending)return AF_BUSY;
    return o->receiver.magic?af_recipe_rx_cancel(&o->receiver):AF_EMPTY;
}
#endif
int af_cp_recipe406_last_result(void){return owner?owner->last_result:AF_EMPTY;}
int af_cp_recipe406_last_send(void){return owner?owner->last_send:AF_EMPTY;}
static int send_reply(Owner *o) {
    o->last_send=o->config.send(o->config.context,o->reply,sizeof(o->reply),0x80020002u);
    if(o->last_send){*o->config.input_fault=1;return AF_IO;}
    return AF_OK;
}
int af_cp_recipe406_pending(AfRecipeLease *lease,const AfRecipeOwned **out) {
    if(!owner)return AF_EMPTY;
    if(!apart(owner,sizeof(*owner),lease,sizeof(*lease))||
       !apart(owner,sizeof(*owner),out,sizeof(*out))||!apart(lease,sizeof(*lease),out,sizeof(*out)))return AF_INVALID;
    if(!owner->pending)return AF_EMPTY;
    *lease=owner->pending_lease;*out=owner->pending;return AF_OK;
}
int af_cp_recipe406_finish(int decision) {
    Owner *o=owner;
    if(!o||!o->pending)return AF_EMPTY;
    if(decision>0||decision< -32768)return AF_INVALID;
    if(decision==AF_BUSY){o->last_result=AF_BUSY;return AF_BUSY;}
    if(decision==AF_IO){
        /* 未知消费者结果不能通过负ACK伪装为已回滚，更不能解除其指针拥有权。 */
        *o->config.input_fault=1;o->last_result=AF_IO;return AF_IO;
    }
    AfRecipeLease lease=o->pending_lease;
    if(decision==AF_OK&&lease.version<=*o->config.input_version)return AF_STALE;
    int result=af_recipe_rx_finish(&o->receiver,&lease,decision,o->reply,sizeof(o->reply));
    if(result!=AF_OK){o->last_result=result;return result;}
    if(decision==AF_OK){
        *o->config.input_version=lease.version;*o->config.input_slot=o->pending->message.slot;
    }
    o->pending=0;o->last_result=decision;
    if(decision!=AF_OK){
        result=af_recipe_rx_release(&o->receiver,&lease);
        if(result!=AF_OK){*o->config.input_fault=1;o->last_result=result;return result;}
    }
    /* 已确认决定先提交，再发送；发送失败不回滚，也不自动重发或重调消费者。 */
    result=send_reply(o);return result==AF_OK?AF_OK:result;
}
int af_cp_recipe406_release(const AfRecipeLease *lease) {
    if(!owner)return AF_EMPTY;
    return af_recipe_rx_release(&owner->receiver,lease);
}
int af_cp_recipe406_receive(const void *input,uint32_t source,size_t bytes) {
    const uint8_t *p=input;
    if(source!=0x80020002u||!p||bytes<4||p[0]!='A'||p[1]!='7'||p[2]!='R'||p[3]!='1')return 0;
    Owner *o=owner;
    if(!o)return 1;
    if(bytes!=AF_RECIPE_FRAME_BYTES||!apart(o,sizeof(*o),p,bytes)){o->last_result=AF_INVALID;return 1;}
    AfHandshake *h=o->config.handshake;
    if(*o->config.input_fault){o->last_result=AF_IO;return 1;}
    if(h->state!=5||!h->session||!(h->required&AF_APPLY_CAP_FULL_RECIPE)){
        o->last_result=AF_BUSY;return 1;
    }
    if(u32(p+12)<7&&!(h->required&AF_APPLY_CAP_USER20)){o->last_result=AF_INVALID;return 1;}
    if(o->pending){o->last_result=AF_BUSY;return 1;}
    if(!o->receiver.magic){
        uint32_t caps=AF_RECIPE_CAP_FULL;
        if(AF_JOINT_SECTOR_SUPPORTED&&(h->required&AF_APPLY_CAP_SECTOR_MATRIX))caps|=AF_RECIPE_CAP_SECTOR;
        int status=af_recipe_rx_init(&o->receiver,h->session,caps);
        if(status!=AF_OK){o->last_result=status;return 1;}
    }
    if(o->receiver.session!=h->session){o->last_result=AF_STALE;return 1;}
    if(version(p)<=*o->config.input_version){o->last_result=AF_STALE;return 1;}
    int result=af_recipe_rx_frame(&o->receiver,p,bytes);o->last_result=result;
    if(result!=AF_OK||p[5]!=AF_RECIPE_END)return 1;
    result=af_recipe_rx_validate(&o->receiver,&o->decode);o->last_result=result;
    if(result!=AF_OK){
        if(af_recipe_rx_rejection(&o->receiver,o->reply,sizeof(o->reply))==AF_OK)(void)send_reply(o);
        return 1;
    }
    /* 完整副本的独立租约在堆对象外保存，满足接收器的输入/输出独立约束。 */
    AfRecipeLease lease;const AfRecipeOwned *pending;
    result=af_recipe_rx_take(&o->receiver,&lease,&pending);o->last_result=result;
    if(result!=AF_OK)return 1;
    o->pending_lease=lease;o->pending=pending;
    result=o->config.consume(o->config.context,pending,&lease);
    /* 消费者只调用一次；BUSY/IO保留完整对象，后续只能由真实拥有者显式决定。 */
    (void)af_cp_recipe406_finish(result);return 1;
}
