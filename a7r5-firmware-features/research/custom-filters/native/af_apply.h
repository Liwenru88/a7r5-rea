/* 整预设与不可变银行集合协调器。单一事件拥有者使用；没有真实CP回执或设备接口。 */
#ifndef AF_APPLY_H
#define AF_APPLY_H
#include "af_slots.h"
#define AF_APPLY_CONSUMERS 13u
#define AF_APPLY_BANKS 3u
#define AF_APPLY_LEASES 64u
#define AF_APPLY_ALL 0x1fffu
/* 仅传输能力，不是第14个消费者；银行/帧算法仍只接受AF_APPLY_ALL。 */
#define AF_APPLY_CAP_FACTORY_RESTORE 0x10000u
#define AF_APPLY_CAP_SNAPSHOT_OVERLAY 0x20000u
#define AF_APPLY_CAP_FULL_RECIPE 0x40000u
#define AF_APPLY_CAP_USER20 0x80000u
#define AF_APPLY_CAP_SECTOR_MATRIX 0x100000u
#if defined(AF_RECIPE_BRIDGE406) && !defined(AF_JOINT_ASSET_LEGACY_ONLY406)
#define AF_APPLY_SECTOR_ALLOWED AF_APPLY_CAP_SECTOR_MATRIX
#else
#define AF_APPLY_SECTOR_ALLOWED 0u
#endif
#ifdef AF_RECIPE_BRIDGE406
#define AF_APPLY_RECIPE_ALLOWED (AF_APPLY_CAP_FULL_RECIPE|AF_APPLY_CAP_USER20|AF_APPLY_SECTOR_ALLOWED)
#else
#define AF_APPLY_RECIPE_ALLOWED 0u
#endif
#ifdef AF_SNAPSHOT_OVERLAY406
#define AF_APPLY_OVERLAY_ALLOWED AF_APPLY_CAP_SNAPSHOT_OVERLAY
#else
#define AF_APPLY_OVERLAY_ALLOWED 0u
#endif
#ifdef AF_FACTORY_RESTORE406
#define AF_APPLY_PROTOCOL_ALLOWED (AF_APPLY_ALL|AF_APPLY_CAP_FACTORY_RESTORE|AF_APPLY_OVERLAY_ALLOWED|AF_APPLY_RECIPE_ALLOWED)
#define AF_APPLY_PROTOCOL_REQUIRED AF_APPLY_PROTOCOL_ALLOWED
#else
#define AF_APPLY_PROTOCOL_ALLOWED (AF_APPLY_ALL|AF_APPLY_OVERLAY_ALLOWED|AF_APPLY_RECIPE_ALLOWED)
#define AF_APPLY_PROTOCOL_REQUIRED AF_APPLY_PROTOCOL_ALLOWED
#endif
#define AF_APPLY_PACKET_BYTES 128u
#define AF_APPLY_HELLO 1u
#define AF_APPLY_PRESET 2u
/* 仅协商快照覆盖后可退出私有覆盖；不携带伪原厂预设。 */
#define AF_APPLY_NATIVE 3u
#define AF_APPLY_OWNER 0x80000000u

typedef struct {
    /* required仅在字节协议/HELLO中可含能力；slot0仅供协商后的原厂整组恢复。 */
    uint32_t operation,required,slot;
    uint64_t session,version;
    AfPreset preset;
} AfApplyPacket;
typedef struct { uint32_t address,bytes; } AfOutputBank;
typedef struct { uint64_t session,version;uint32_t bank; } AfApplyToken;
typedef struct { uint64_t session,version,lease;uint32_t bank; } AfApplyLease;
typedef struct {
    AfPreset preset;
    uint64_t version;
    uint32_t slot,reserved,started,ready,failed,references;
    AfOutputBank outputs[AF_APPLY_CONSUMERS];
} AfApplyGroup;
typedef struct { AfApplyLease token;uint32_t remaining; } AfApplyFrame;
typedef struct {
    AfApplyGroup groups[AF_APPLY_BANKS];
    AfApplyFrame frames[AF_APPLY_LEASES];
    uint64_t session,last_version,next_lease;
    uint32_t required,active,pending,negotiated,magic;
} AfApply;

/* 字节协议仅绑定源4.06构建/协议版本，不提供认证，不分配实际消息ID。
 * 输入/输出和written须独立；失败不发布输出。仅支持纯参数。 */
int af_apply_packet_encode(const AfApplyPacket *,void *,size_t,size_t *);
int af_apply_packet_decode(const void *,size_t,AfApplyPacket *);
size_t af_apply_bytes(void);
/* 对象首次须清零；session由调用方提供且每次重建必须唯一，不能重置在用对象。
 * required来自已验证模式所需消费者；当前未证明实际13项版本绑定。 */
int af_apply_init(AfApply *,uint64_t session,uint32_t required);
/* 仅真实transport收到并成功解码的对端HELLO可用于机身接入；测试HELLO不是机身握手。 */
int af_apply_negotiate(AfApply *,const AfApplyPacket *);
int af_apply_stage(AfApply *,const AfApplyPacket *,AfApplyToken *);
/* 先预留全部独立输出范围，再启动任何生成任务，避免完成后才发现覆盖在用银行。
 * 地址/长度来自真实分配器；预留本身不拥有或验证该内存的映射和寿命。 */
int af_apply_reserve(AfApply *,const AfApplyToken *,uint32_t,const AfOutputBank *);
/* 全部范围已预留后才允许声明启动；此调用自身不派发任何任务。 */
int af_apply_start(AfApply *,const AfApplyToken *);
/* 银行必须已经完成且由调用方保证不可变/有效。成功/失败均是对应消费者退役；
 * 失败后仍等待其他已声明消费者退役。绝不能用完成位为0代替这些回执。 */
int af_apply_bank(AfApply *,const AfApplyToken *,uint32_t,const AfOutputBank *,int succeeded);
int af_apply_publish(AfApply *,const AfApplyToken *);
/* 未启动可立即取消；启动后必须等待全部消费者退役。 */
int af_apply_abort(AfApply *,const AfApplyToken *);
/* 每帧起始一次声明全部输出；自动附加拥有者屏障，不能在开始后追加消费者。 */
int af_apply_frame(AfApply *,uint32_t output_mask,AfApplyLease *);
int af_apply_view(const AfApply *,const AfApplyLease *,const AfApplyGroup **);
int af_apply_retire(AfApply *,const AfApplyLease *,uint32_t output_mask);
/* 只有真实的帧拥有者最后引用结束才调用；单个JPG/资源池/文件回调不满足条件。 */
int af_apply_owner_end(AfApply *,const AfApplyLease *);
#endif
