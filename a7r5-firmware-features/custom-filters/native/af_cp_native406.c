#include "af_cp_native406.h"
#include "af_cp_jobs406.h"
#include "af_cp_components406.h"
#ifdef AF_CP_CAPTURE406
#include "af_cp_capture406.h"
#endif

#if defined(__arm__) && defined(AF_CP_NATIVE406)
extern AfHandshake af_cp_handshake;
extern uint64_t af_cp_hs_input_version;
extern uint32_t af_cp_hs_input_slot,af_cp_hs_input_fault;
static AfCpNativeBanks406 banks;
/* 完整AJR3接收拥有者的固定上限；运行银行已去除两份不用的曲线，页数不变。 */
static _Alignas(8) uint8_t receiver_arena[17600];
static uint32_t stage,arena_used,pending_copy;
static AfRecipeLease copied_lease;
static uint32_t load(const uint32_t *p){return __atomic_load_n(p,__ATOMIC_SEQ_CST);}
static void store(uint32_t *p,uint32_t n){__atomic_store_n(p,n,__ATOMIC_SEQ_CST);}
static void copy(void *d,const void *s,size_t n){for(size_t i=0;i<n;++i)((uint8_t *)d)[i]=((const uint8_t *)s)[i];}
static int installed(void){
    const volatile uint8_t *factor=(const volatile uint8_t *)(uintptr_t)0xbef718u;
    for(unsigned i=0;i<288;++i)if(factor[i]!=af_cp_native406_factor_expected[i])return 0;
#ifdef AF_CP_CAPTURE406
    const uint32_t starts[8]={0xbef524u,0xbef582u,0xbef65au,0xbef678u,0xbef69cu,0xbef6ecu,0xbef838u,0xbef5c0u};
    const uint16_t lengths[8]={26,6,6,8,20,20,400,96};
    unsigned at=0;
    for(unsigned part=0;part<8;++part){
        const volatile uint8_t *actual=(const volatile uint8_t *)(uintptr_t)starts[part];
        unsigned bytes=lengths[part];
        for(unsigned i=0;i<bytes;++i,++at)if(actual[i]!=af_cp_native406_capture_expected[at])return 0;
    }
    if(af_cp_native406_capture_expected[582]||af_cp_native406_capture_expected[583])return 0;
#endif
    for(unsigned i=0;i<AF_CP_NATIVE406_HOOKS;++i){
        uint32_t a=af_cp_native406_hooks[i].address;
        if(!a||a>UINT32_MAX-4)return 0;
        const volatile uint8_t *actual=(const volatile uint8_t *)(uintptr_t)a;
        for(unsigned j=0;j<4;++j)if(actual[j]!=af_cp_native406_hooks[i].code[j])return 0;
    }
    return 1;
}
AfCpNativeBanks406 *af_cp_native406_banks(void){return &banks;}
static int jobs_failed(void){
    AfCpJobs406 *jobs=af_cp_jobs406_target_state();
    return !jobs||load(&jobs->fault);
}
static void close_private(void){store(&stage,3);af_cp_override406_close();}
int af_cp_native406_ready(void){return load(&stage)==2&&!af_cp_override406_faulted()&&!jobs_failed()
#ifdef AF_CP_CAPTURE406
    &&af_cp_capture406_target_ready()
#endif
    ;}
static void *allocate(void *context,size_t bytes){
    (void)context;
    if(arena_used||!bytes||bytes>sizeof(receiver_arena))return 0;
    arena_used=1;return receiver_arena;
}
static void release(void *context,void *p){(void)context;if(p==receiver_arena)arena_used=0;}
static int send(void *context,const void *data,size_t bytes,uint32_t source){
    (void)context;return ((int(*)(const void *,size_t,uint32_t))(uintptr_t)0x496181u)(data,bytes,source);
}
static int consume(void *context,const AfRecipeOwned *owned,const AfRecipeLease *lease){
    (void)context;
    if(!af_cp_native406_ready()||pending_copy)return AF_IO;
    if(!owned||!lease||owned->asset.native_mode!=1)return AF_JOINT_ASSET_UNSUPPORTED;
    int result=af_cp_override406_prepare_joint(owned->message.version,owned->message.slot,
        &owned->message.preset,&owned->asset);
    /* 两个原生副本仍被worker借用是确定的未提交，不挂起无唤醒者的Rx事务。
     * 负ACK保留原active且立即归还incoming；只由之后明确的新版本再尝试。 */
    if(result==AF_BUSY)return AF_EXHAUSTED;
    if(result==AF_OK){copy(&copied_lease,lease,sizeof(*lease));pending_copy=1;}
    return result;
}
int af_cp_native406_bind_once(void){
    uint32_t value=load(&stage);
    if(value==2)return af_cp_native406_ready()?AF_OK:AF_IO;
    if(value)return value==1?AF_BUSY:AF_IO;
    if(!installed()){close_private();return AF_IO;}
    /* 原锁暂忙时尚未初始化任何对象，可由原消息拥有者以后再试。 */
    if(!af_cp_override406_ready())return af_cp_override406_faulted()?AF_IO:AF_BUSY;
    store(&stage,1);
    if(af_cp_jobs406_bind_target(&banks)!=AF_OK||af_cp_components406_bind_target()!=AF_OK){close_private();return AF_IO;}
#ifdef AF_CP_CAPTURE406
    if(af_cp_capture406_bind_target()!=AF_OK){close_private();return AF_IO;}
#endif
    AfCpRecipe406Config config;
    for(size_t i=0;i<sizeof(config);++i)((volatile uint8_t *)&config)[i]=0;
    config.handshake=&af_cp_handshake;config.input_version=&af_cp_hs_input_version;
    config.input_slot=&af_cp_hs_input_slot;config.input_fault=&af_cp_hs_input_fault;
    config.allocate=allocate;config.release=release;config.send=send;config.consume=consume;
    if(af_cp_recipe406_bind(&config)!=AF_OK){close_private();return AF_IO;}
    store(&stage,2);return AF_OK;
}
void af_cp_native406_receive_finished(void){
    /* 仅原通信拥有者调用；深副本已独立，软件决定完成后归还Rx租约。 */
    if(load(&stage)==2&&(af_cp_override406_faulted()||jobs_failed()))close_private();
#ifdef AF_CP_CAPTURE406
    if(load(&stage)==2&&!af_cp_capture406_target_ready())close_private();
#endif
    if(load(&stage)==3)af_cp_hs_input_fault=1;
    if(!pending_copy)return;
    AfRecipeLease lease;const AfRecipeOwned *pending;
    int result=af_cp_recipe406_pending(&lease,&pending);
    if(result==AF_EMPTY){
        if(af_cp_recipe406_release(&copied_lease)==AF_OK)pending_copy=0;
        else{close_private();af_cp_hs_input_fault=1;}
    }else if(result!=AF_OK){close_private();af_cp_hs_input_fault=1;}
}
void af_cp_native406_queue_target(void *d,const void *s,size_t n,uint32_t lr,const void *sp){
    /* 内核原copy处不能取任务/锁；故障传播也只写原子粘性位。 */
    af_cp_jobs406_queue_target(d,s,n,lr,sp);
    if(load(&stage)==2&&jobs_failed())af_cp_override406_close();
}
void af_cp_native406_shot_copy_target(void *d,const void *s,size_t n,uint32_t lr){
    /* 完整原复制先执行一次；后处理只失效真实id2工作的Gamma比较缓存。 */
    ((void(*)(void *,const void *,size_t))(uintptr_t)0x5f51bcu)(d,s,n);
    (void)af_cp_components406_shot_after_target(d,s,n,lr);
}
#else
AfCpNativeBanks406 *af_cp_native406_banks(void){return 0;}
int af_cp_native406_bind_once(void){return AF_IO;}
int af_cp_native406_ready(void){return 0;}
void af_cp_native406_receive_finished(void){}
void af_cp_native406_queue_target(void *d,const void *s,size_t n,uint32_t lr,const void *sp){(void)d;(void)s;(void)n;(void)lr;(void)sp;}
void af_cp_native406_shot_copy_target(void *d,const void *s,size_t n,uint32_t lr){(void)d;(void)s;(void)n;(void)lr;}
#endif
