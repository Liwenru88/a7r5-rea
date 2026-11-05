/* 固定修改4.06的原AP导入；隔离器只提供显式后端，绝不调用宿主系统服务。 */
#include "af_runtime.h"
#ifdef AF_CP_PRESET406
#include "af_runtime_ap406.h"
#ifdef AF_RECIPE_BRIDGE406
#include "af_sha256.h"
#endif
#endif
extern void *af_stock_dlsym(void *,const char *);
extern int af_stock_open(const char *,int,...);
extern long af_stock_read(int,void *,size_t);
extern int af_stock_close(int);
extern int *af_stock_errno(void);
extern int af_stock_allocate(uint32_t,void **,uint32_t,int);
extern void af_stock_source(void *,uint32_t);
extern int af_stock_send(uint32_t,void *);
extern int af_stock_receive(uint32_t,void **,int);
extern int af_stock_usleep(unsigned);
typedef struct { int64_t seconds,nanoseconds; } AfTimespec;
typedef int (*AfClockGettime)(int,AfTimespec *);
AfRuntime af_ap_runtime;
#ifdef AF_CP_PRESET406
/* 通信任务单独拥有AfRuntime；界面仅消费一次发布的不可变连接快照。 */
static struct { uint64_t session;uint32_t required; } preset_connection;
static uint32_t preset_ready,preset_closed,preset_busy,preset_send_failed;
static uint64_t preset_version;
#ifdef AF_RECIPE_BRIDGE406
static uint32_t native_exit_attempted;
/* 完整发送对象在发布后不可变；通信拥有者只在WAIT状态接收匹配回执。
 * 状态：0未发送，1发送中，2等回执，3有确定回执，4发送／截止故障。 */
static AfRecipeTx recipe_transaction;
static AfRecipeAck recipe_acknowledgment;
static uint64_t recipe_deadline;
static uint32_t recipe_phase;
#endif
static void preset_owner_update(void) {
    if (__atomic_load_n(&preset_send_failed,__ATOMIC_ACQUIRE) && !af_ap_runtime.fault) {
        af_ap_runtime.fault=AF_RT_SEND;af_ap_runtime.hello.state=3;
    }
#ifdef AF_RECIPE_BRIDGE406
    if (__atomic_load_n(&recipe_phase,__ATOMIC_ACQUIRE)==2 &&
        af_ap_runtime.last_now>=recipe_deadline) {
        __atomic_store_n(&recipe_phase,4,__ATOMIC_RELEASE);
        if(!af_ap_runtime.fault)af_ap_runtime.fault=AF_RT_RECIPE;
        af_ap_runtime.hello.state=3;
    }
#endif
    if (af_ap_runtime.fault || af_ap_runtime.hello.state==3) {
        __atomic_store_n(&preset_closed,1,__ATOMIC_RELEASE);
    } else if (af_ap_runtime.hello.state==2 && !__atomic_load_n(&preset_ready,__ATOMIC_RELAXED)
#ifdef AF_FACTORY_RESTORE406
               && (af_ap_runtime.hello.required&AF_APPLY_CAP_FACTORY_RESTORE)
#endif
#ifdef AF_SNAPSHOT_OVERLAY406
               && (af_ap_runtime.hello.required&AF_APPLY_CAP_SNAPSHOT_OVERLAY)
#endif
    ) {
        preset_connection.session=af_ap_runtime.hello.session;
        preset_connection.required=af_ap_runtime.hello.required;
        __atomic_store_n(&preset_ready,1,__ATOMIC_RELEASE);
    }
}
#endif
static AfClockGettime clock_gettime_source;
int af_ap_runtime_clock(uint64_t *out) {
    AfTimespec t={-1,-1};
    if (!out) return AF_INVALID;
    if (!clock_gettime_source)
        clock_gettime_source=(AfClockGettime)af_stock_dlsym(0,"clock_gettime");
    if (!clock_gettime_source || clock_gettime_source(1,&t) || t.seconds<0 ||
        t.nanoseconds<0 || t.nanoseconds>=1000000000 ||
        (uint64_t)t.seconds>(UINT64_MAX-999)/1000) return AF_INVALID;
    *out=(uint64_t)t.seconds*1000+(uint64_t)t.nanoseconds/1000000;
    return AF_OK;
}
int af_ap_runtime_nonce(uint64_t *out) {
    uint8_t bytes[8]={0};
    uint64_t value=0;
    size_t used=0;
    int fd,closed;
    if (!out) return AF_INVALID;
    fd=af_stock_open("/dev/urandom",0);
    if (fd<0) return AF_INVALID;
    for (unsigned tries=0;used<sizeof(bytes) && tries<16;++tries) {
        long n=af_stock_read(fd,bytes+used,sizeof(bytes)-used);
        if (n>0 && (size_t)n<=sizeof(bytes)-used) used+=(size_t)n;
        else if (n!=-1 || *af_stock_errno()!=4) break;
    }
    closed=af_stock_close(fd);
    if (used!=sizeof(bytes) || closed) return AF_INVALID;
    for (unsigned i=0;i<8;++i) value|=(uint64_t)bytes[i]<<(8*i);
    if (!value) return AF_INVALID;
    *out=value;
    return AF_OK;
}
static int send_packet(const void *raw,size_t n,int native_exit) {
    void *message=0;
    const uint8_t *p=raw;
    int result;
    if (!p || n!=128) return AF_INVALID;
    /* 原分配器wait=0：不引入原future的无限等待。 */
    result=af_stock_allocate(0x90030001u,&message,128,0);
    if (result || !message) return AF_INVALID;
#if defined(AF_CP_PRESET406) && defined(AF_RECIPE_BRIDGE406)
    /* 分配期间通信线程可能已经关闭事务；不再发送END，也不猜测缓冲释放。
     * 关闭后不会再次分配，因此此不确定拥有权最多保留一个未发送缓冲。 */
    if(!native_exit&&(__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE) ||
       __atomic_load_n(&recipe_phase,__ATOMIC_ACQUIRE)==4))return AF_INVALID;
#else
    (void)native_exit;
#endif
    for (size_t i=0;i<n;++i) ((uint8_t *)message)[i]=p[i];
    af_stock_source(message,0x80020002u);
    /* AP驱动发送失败的缓冲所有权未证实；不猜测free，私有协议转故障。 */
    return af_stock_send(0x90030001u,message);
}
static int send_hello(const void *raw,size_t n){return send_packet(raw,n,0);}
#ifdef AF_CP_PRESET406
#ifdef AF_RECIPE_BRIDGE406
int af_ap_runtime_native_only_capable(void){
    if(!__atomic_load_n(&preset_ready,__ATOMIC_ACQUIRE) ||
       !__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE))return 0;
    uint32_t needed=AF_APPLY_CAP_USER20|AF_APPLY_CAP_SNAPSHOT_OVERLAY;
    return (preset_connection.required&needed)==needed;
}
static int send_closed_native(void){
    uint32_t expected=0;int result;
    if(!af_ap_runtime_native_only_capable())return AF_IO;
    if(!__atomic_compare_exchange_n(&preset_busy,&expected,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))return AF_BUSY;
    if(native_exit_attempted||!af_ap_runtime_native_only_capable()){result=AF_IO;goto done;}
    uint64_t version=__atomic_load_n(&preset_version,__ATOMIC_RELAXED);
    if(version==UINT64_MAX){result=AF_EXHAUSTED;goto done;}
    AfApplyPacket packet={0};uint8_t raw[128];size_t bytes=0;
    packet.operation=AF_APPLY_NATIVE;packet.session=preset_connection.session;
    packet.required=preset_connection.required;packet.version=version+1;
    result=af_apply_packet_encode(&packet,raw,sizeof(raw),&bytes);
    if(result!=AF_OK)goto done;
    /* 仅明确原厂事件可花掉这一次退出；分配/发送失败也不重发，不恢复私有连接。
     * 原驱动的未知buffer继续保留，不能猜测free或把发送接受称为CP退出完成。 */
    native_exit_attempted=1;
    __atomic_store_n(&preset_version,version+1,__ATOMIC_RELEASE);
    result=send_packet(raw,bytes,1)?AF_IO:AF_OK;
done:
    __atomic_store_n(&preset_busy,0,__ATOMIC_RELEASE);return result;
}
#endif
static int send_input(uint32_t operation,uint32_t slot,const AfPreset *preset) {
    AfApplyPacket next={0};uint8_t packet[128];size_t n=0;
    uint64_t version;uint32_t expected=0;int result;
    if (operation==AF_APPLY_PRESET) {
        if (!preset) return AF_INVALID;
        next.preset=*preset;
        if (af_validate(&next.preset)!=AF_OK || next.preset.kind || slot>AF_USERS
#ifndef AF_FACTORY_RESTORE406
            || slot<1
#endif
        ) return AF_INVALID;
    } else if (operation!=AF_APPLY_NATIVE || slot || preset) return AF_INVALID;
    if (__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE)) return AF_IO;
    if (!__atomic_load_n(&preset_ready,__ATOMIC_ACQUIRE)) return AF_BUSY;
    if (!__atomic_compare_exchange_n(&preset_busy,&expected,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED)) return AF_BUSY;
    /* 与其他界面调用串行化，但从不阻塞原通信任务的接收。 */
    if (__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE)) { result=AF_IO;goto done; }
#ifdef AF_RECIPE_BRIDGE406
    uint32_t phase=__atomic_load_n(&recipe_phase,__ATOMIC_ACQUIRE);
    if(phase==4){result=AF_IO;goto done;}
    if(phase==1 || phase==2){result=AF_BUSY;goto done;}
#endif
    if (operation==AF_APPLY_NATIVE) {
        if (!(preset_connection.required&AF_APPLY_CAP_SNAPSHOT_OVERLAY)) { result=AF_INVALID;goto done; }
    } else if (!slot && !(preset_connection.required&AF_APPLY_CAP_FACTORY_RESTORE)) { result=AF_INVALID;goto done; }
    version=__atomic_load_n(&preset_version,__ATOMIC_RELAXED);
    if (version==UINT64_MAX) { result=AF_EXHAUSTED;goto done; }
    next.operation=operation;next.required=preset_connection.required;
    next.session=preset_connection.session;next.version=version+1;next.slot=slot;
    result=af_apply_packet_encode(&next,packet,sizeof(packet),&n);
    if (result!=AF_OK) goto done;
    __atomic_store_n(&preset_version,next.version,__ATOMIC_RELEASE);
    result=send_hello(packet,n);
    if (result) {
        __atomic_store_n(&preset_send_failed,1,__ATOMIC_RELEASE);
        __atomic_store_n(&preset_closed,1,__ATOMIC_RELEASE);result=AF_IO;
    }
done:
    __atomic_store_n(&preset_busy,0,__ATOMIC_RELEASE);
    return result;
}
int af_ap_runtime_send_preset(uint32_t slot,const AfPreset *preset) {
    return send_input(AF_APPLY_PRESET,slot,preset);
}
int af_ap_runtime_release_preset(void) {
#ifdef AF_RECIPE_BRIDGE406
    if(__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE))return send_closed_native();
#endif
    return send_input(AF_APPLY_NATIVE,0,0);
}
uint64_t af_ap_runtime_last_attempted_version(void) {
    return __atomic_load_n(&preset_version,__ATOMIC_ACQUIRE);
}
uint32_t af_ap_runtime_preset_capabilities(void) {
    if (!__atomic_load_n(&preset_ready,__ATOMIC_ACQUIRE)) return 0;
    return __atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE)?0:preset_connection.required;
}
int af_ap_runtime_preset_status(void){
    if(__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE))return AF_IO;
    if(!__atomic_load_n(&preset_ready,__ATOMIC_ACQUIRE))return AF_BUSY;
    return __atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE)?AF_IO:AF_OK;
}
#ifdef AF_RECIPE_BRIDGE406
static int recipe_preset_same(const AfPreset *a,const AfPreset *b){
    unsigned difference=a->base^b->base;difference|=a->kind^b->kind;
    for(unsigned i=0;i<8;++i)difference|=(uint8_t)a->params[i]^(uint8_t)b->params[i];
    for(unsigned i=0;i<32;++i){difference|=a->payload_sha256[i]^b->payload_sha256[i];difference|=a->lut_sha256[i]^b->lut_sha256[i];}
    return !difference;
}
static int send_recipe(uint32_t slot,const AfPreset *preset,const void *image,size_t bytes,
    AfApRecipeCapture406 capture,void *context,uint32_t timeout_ms) {
    uint32_t expected=0;uint64_t version,now;int result;
    if(af_validate(preset)!=AF_OK || preset->kind!=1 ||
       (capture?(!context||image||bytes):(!image||!af_joint_asset_size_valid(bytes))) || slot<1 || slot>AF_USERS ||
       !timeout_ms || timeout_ms>60000)return AF_INVALID;
    if(__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE))return AF_IO;
    if(!__atomic_load_n(&preset_ready,__ATOMIC_ACQUIRE))return AF_BUSY;
    if(!(preset_connection.required&AF_APPLY_CAP_FULL_RECIPE))return AF_INVALID;
    if(slot<7&&!(preset_connection.required&AF_APPLY_CAP_USER20))return AF_INVALID;
    if(!__atomic_compare_exchange_n(&preset_busy,&expected,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))return AF_BUSY;
    if(__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE)){result=AF_IO;goto done;}
    uint32_t phase=__atomic_load_n(&recipe_phase,__ATOMIC_ACQUIRE);
    if(phase==4){result=AF_IO;goto done;}
    if(phase==1 || phase==2){result=AF_BUSY;goto done;}
    version=__atomic_load_n(&preset_version,__ATOMIC_RELAXED);
    if(version==UINT64_MAX){result=AF_EXHAUSTED;goto done;}
    if(capture){
        result=capture(context,slot,preset,preset_connection.session,version+1,&recipe_transaction);
        if(result!=AF_OK)goto done;
        uint8_t check[128],digest[32];
        if(af_recipe_tx_frame(&recipe_transaction,0,check,sizeof(check))!=AF_OK ||
           recipe_transaction.message.session!=preset_connection.session || recipe_transaction.message.version!=version+1 ||
           recipe_transaction.message.slot!=slot || !recipe_preset_same(preset,&recipe_transaction.message.preset) ||
           af_sha256(recipe_transaction.message.image,recipe_transaction.message.image_bytes,digest)!=AF_OK){result=AF_STALE;goto done;}
        for(unsigned i=0;i<32;++i)if(digest[i]!=preset->payload_sha256[i]){result=AF_STALE;goto done;}
    }else result=af_recipe_tx_init(&recipe_transaction,preset_connection.session,version+1,slot,preset,image,bytes);
    if(result!=AF_OK)goto done;
    if(recipe_transaction.message.image_bytes==AF_JOINT_SECTOR_BYTES&&
       !(preset_connection.required&AF_APPLY_CAP_SECTOR_MATRIX)){result=AF_JOINT_ASSET_UNSUPPORTED;goto done;}
    if(__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE)){result=AF_IO;goto done;}
    if(af_ap_runtime_clock(&now)!=AF_OK || now>UINT64_MAX-timeout_ms){result=AF_INVALID;goto done;}
    recipe_deadline=now+timeout_ms;
    __atomic_store_n(&recipe_phase,1,__ATOMIC_RELEASE);
    __atomic_store_n(&preset_version,version+1,__ATOMIC_RELEASE);
    uint32_t frames=af_recipe_tx_frames(&recipe_transaction);
    for(unsigned i=0;i<frames;++i){
        uint8_t raw[AF_RECIPE_FRAME_BYTES];
        if(__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE) ||
           __atomic_load_n(&recipe_phase,__ATOMIC_ACQUIRE)==4){result=AF_IO;break;}
        result=af_recipe_tx_frame(&recipe_transaction,i,raw,sizeof(raw));
        if(result!=AF_OK)break;
        /* 完整END发送期间可由原通信拥有者接回执，发送对象此时已固定。 */
        if(i==frames-1)__atomic_store_n(&recipe_phase,2,__ATOMIC_RELEASE);
        if(send_hello(raw,sizeof(raw))){result=AF_IO;break;}
    }
    /* 已进入原驱动的END不可原子撤回。即使驱动接受，截止／关闭后也不能报发送成功；
     * 消费者可能已prepared，保留故障及未知结果，不自动回滚或重发。 */
    if(__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE) ||
       __atomic_load_n(&recipe_phase,__ATOMIC_ACQUIRE)==4)result=AF_IO;
    if(result!=AF_OK){
        __atomic_store_n(&recipe_phase,4,__ATOMIC_RELEASE);
        __atomic_store_n(&preset_send_failed,1,__ATOMIC_RELEASE);
        __atomic_store_n(&preset_closed,1,__ATOMIC_RELEASE);
    }
done:
    __atomic_store_n(&preset_busy,0,__ATOMIC_RELEASE);return result;
}
int af_ap_runtime_send_recipe(uint32_t slot,const AfPreset *preset,const void *image,size_t bytes,uint32_t timeout_ms){
    return send_recipe(slot,preset,image,bytes,0,0,timeout_ms);
}
int af_ap_runtime_send_stored_recipe(uint32_t slot,const AfPreset *preset,AfApRecipeCapture406 capture,void *context,uint32_t timeout_ms){
    return capture?send_recipe(slot,preset,0,0,capture,context,timeout_ms):AF_INVALID;
}
int af_ap_runtime_recipe_result(AfRecipeAck *out) {
    uint32_t expected=0;
    if(!out)return AF_INVALID;
    if(__atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE))return AF_IO;
    if(!__atomic_compare_exchange_n(&preset_busy,&expected,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))return AF_BUSY;
    uint32_t phase=__atomic_load_n(&recipe_phase,__ATOMIC_ACQUIRE);
    int result=phase==3?AF_OK:(phase==1 || phase==2?AF_BUSY:(phase==4?AF_IO:AF_EMPTY));
    if(result==AF_OK)*out=recipe_acknowledgment;
    __atomic_store_n(&preset_busy,0,__ATOMIC_RELEASE);return result;
}
static int recipe_reply(const void *raw,uint32_t source,size_t bytes) {
    const uint8_t *p=raw;
    if(!p || source!=0x90030001u || bytes<4 || p[0]!='A' || p[1]!='7' || p[2]!='R' || p[3]!='1')return 0;
    if(bytes!=128 || __atomic_load_n(&preset_closed,__ATOMIC_ACQUIRE) ||
       __atomic_load_n(&recipe_phase,__ATOMIC_ACQUIRE)!=2)return 1;
    AfRecipeAck ack;
    if(af_recipe_tx_ack(&recipe_transaction,raw,bytes,&ack)==AF_OK){
        recipe_acknowledgment=ack;
        __atomic_store_n(&recipe_phase,3,__ATOMIC_RELEASE);
    }
    return 1;
}
#endif
#endif
static const AfRuntimePorts ports={af_ap_runtime_nonce,af_ap_runtime_clock,send_hello,af_stock_receive};
int af_ap_runtime_next(uint32_t queue,void **out) {
#ifdef AF_CP_PRESET406
    preset_owner_update();
#endif
#if defined(AF_CP_PRESET406) && defined(AF_RECIPE_BRIDGE406)
    /* 即使界面尚无任务也须有界等待，避免通信线程先进入无限接收后无法推进截止。 */
    int present=af_rt_next_bounded(&af_ap_runtime,&ports,queue,out,50);
#else
    int present=af_rt_next(&af_ap_runtime,&ports,queue,out);
#endif
#ifdef AF_CP_PRESET406
    preset_owner_update();
#endif
    if (!present && af_ap_runtime.fault) (void)af_stock_usleep(50000);
    return present;
}
int af_ap_runtime_reply(const void *p,uint32_t source,size_t n) {
    int result;
#ifdef AF_CP_PRESET406
    preset_owner_update();
#endif
#if defined(AF_CP_PRESET406) && defined(AF_RECIPE_BRIDGE406)
    /* 先推进真实单调时钟，过期ACK不得复活已关闭的事务。 */
    if(!af_ap_runtime.fault)(void)af_rt_poll(&af_ap_runtime,&ports);
    preset_owner_update();
    result=recipe_reply(p,source,n);
    if(!result)result=af_rt_reply(&af_ap_runtime,&ports,p,source,n);
#else
    result=af_rt_reply(&af_ap_runtime,&ports,p,source,n);
#endif
#ifdef AF_CP_PRESET406
    preset_owner_update();
#endif
    return result;
}
int af_ap_runtime_poll(void) {
    int result;
#ifdef AF_CP_PRESET406
    preset_owner_update();
#endif
    result=af_rt_poll(&af_ap_runtime,&ports);
#ifdef AF_CP_PRESET406
    preset_owner_update();
#endif
    return result;
}
