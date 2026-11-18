/* 既有HELLO和可选纯参数输入；不回复银行、像素或帧释放成功。 */
#include "af_handshake.h"
#ifdef AF_CP_NATIVE406
#include "af_cp_native406.h"
#endif
#ifdef AF_RECIPE_BRIDGE406
#include "af_cp_recipe406.h"
#endif
#ifdef AF_CP_PRESET406
#include "af_cp406_state.h"
#ifdef AF_SNAPSHOT_OVERLAY406
#include "af_cp_override406.h"
#endif
/* 单一原消息任务拥有；这些值只诊断输入交接，不是图像代号回执。 */
uint64_t af_cp_hs_input_version;
uint32_t af_cp_hs_input_slot,af_cp_hs_input_fault;
int af_cp_hs_last_prepare=AF_EMPTY;
#endif
AfHandshake af_cp_handshake;
int af_cp_hs_last_send;
static uint8_t response[128];
int af_cp_hs_configure(uint32_t required) {
    /* 未证明原任务排空时禁止重建会话和回退输入版本。 */
    if(af_cp_handshake.state)return AF_BUSY;
#ifdef AF_RECIPE_BRIDGE406
    if((required&AF_APPLY_CAP_FULL_RECIPE) && !af_cp_recipe406_ready(&af_cp_handshake))return AF_BUSY;
#endif
#if defined(AF_CP_PRESET406) && defined(AF_SNAPSHOT_OVERLAY406)
    /* 编译成功不表示原快照gate已安装；未确认时原厂消息仍正常委派。 */
    if ((required&AF_APPLY_CAP_SNAPSHOT_OVERLAY) && af_cp_override406_ready()!=1) return AF_BUSY;
#endif
    int result=af_hs_server_init(&af_cp_handshake,required);
#ifdef AF_CP_PRESET406
    if (result==AF_OK) {
        af_cp_hs_input_version=0;af_cp_hs_input_slot=af_cp_hs_input_fault=0;
        af_cp_hs_last_prepare=AF_EMPTY;
    }
#endif
    return result;
}
#ifdef AF_RUNTIME406
int af_cp_hs_start_once(void) {
    /* 再次经过启动点也不清除已绑定会话，更不能代替银行/帧排空。 */
    if(af_cp_handshake.state)return AF_BUSY;
#ifdef AF_CP_NATIVE406
    int bound=af_cp_native406_bind_once();if(bound!=AF_OK)return bound;
#endif
    return af_cp_hs_configure(AF_APPLY_PROTOCOL_REQUIRED);
}
#endif
int af_cp_hs_receive(const void *p,uint32_t source,size_t bytes) {
#ifdef AF_CP_NATIVE406
    af_cp_native406_receive_finished();
#endif
#ifdef AF_RUNTIME406
    /* 启动时原锁可能暂忙；仅原消息拥有者重试未初始化态，不重置已绑定会话。 */
    if (!af_cp_handshake.state) (void)af_cp_hs_start_once();
#endif
#ifdef AF_RECIPE_BRIDGE406
    if(af_cp_recipe406_receive(p,source,bytes)){
#ifdef AF_CP_NATIVE406
        af_cp_native406_receive_finished();
#endif
        return 1;
    }
#endif
    size_t size=0;
    int handled=af_hs_server(&af_cp_handshake,p,bytes,source,response,sizeof(response),&size);
#ifdef AF_CP_PRESET406
    /* 原入口在0x24互斥之前分流；仅由该单一任务调用有锁入口。
     * 复用既有128字节PRESET，不新增消息ID或“应用完成”回复。 */
    if (handled && !size && (((const uint8_t *)p)[6]==AF_APPLY_PRESET ||
                            ((const uint8_t *)p)[6]==AF_APPLY_NATIVE) && !((const uint8_t *)p)[7]) {
        AfApplyPacket packet;
        int result=AF_INVALID;
        if (af_apply_packet_decode(p,bytes,&packet)==AF_OK &&
            (packet.operation==AF_APPLY_PRESET || packet.operation==AF_APPLY_NATIVE) && af_cp_handshake.state==5 &&
            packet.session==af_cp_handshake.session && packet.required==af_cp_handshake.required) {
            int gate=af_cp_hs_input_fault?AF_IO:AF_OK;
#if defined(AF_CP_NATIVE406) && defined(AF_RECIPE_BRIDGE406)
            /* 只有本次USER20原生端的明确新版NATIVE可丢弃尚未take的分片。
             * helper先核session/version/fault/pending；旧四页构建不引入此胶合。 */
            if(gate==AF_OK&&packet.operation==AF_APPLY_NATIVE&&(packet.required&AF_APPLY_CAP_USER20)){
                gate=af_cp_recipe406_cancel_partial(packet.session,packet.version);
                if(gate==AF_EMPTY)gate=AF_OK;
            }
#endif
            if (gate!=AF_OK) result=gate;
#ifdef AF_RECIPE_BRIDGE406
            else if(af_cp_recipe406_busy())result=AF_BUSY;
            else if(packet.version<=af_cp_recipe406_seen_version())result=AF_STALE;
#endif
            else if (packet.version<=af_cp_hs_input_version) result=AF_STALE;
            else {
#ifdef AF_SNAPSHOT_OVERLAY406
                if (packet.required&AF_APPLY_CAP_SNAPSHOT_OVERLAY)
                    result=packet.operation==AF_APPLY_NATIVE?af_cp_override406_release(packet.version):
                        af_cp_override406_prepare(packet.version,packet.slot,&packet.preset);
                else
#endif
                    result=packet.operation==AF_APPLY_PRESET?af_cp406_locked_prepare(&packet.preset):AF_INVALID;
                if (result==AF_OK) {
                    af_cp_hs_input_version=packet.version;
                    af_cp_hs_input_slot=packet.slot;
                } else if (result==AF_IO) {
                    /* 解锁失败可能已改变输入；本次任务内关闭后续私有准备。 */
                    af_cp_hs_input_fault=1;
                }
            }
        }
        af_cp_hs_last_prepare=result;
    }
#endif
    if (handled && size) {
        typedef int (*Sender)(const void *,size_t,uint32_t);
        af_cp_hs_last_send=((Sender)(uintptr_t)0x496181u)(response,size,0x80020002u);
    }
    return handled;
}
