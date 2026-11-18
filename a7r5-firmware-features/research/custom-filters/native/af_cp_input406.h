/* 原DBC快照和两个E70复制目的的版本伴随；不复制原字节，不确认成像或退休。 */
#ifndef AF_CP_INPUT406_H
#define AF_CP_INPUT406_H
#include "af_cp_override406.h"

#define AF_CP_INPUT406_SNAPSHOT 0x164eef0u
#define AF_CP_INPUT406_COPY_A 0x1653c68u
#define AF_CP_INPUT406_COPY_B 0x16589e0u
#define AF_CP_INPUT406_REQUEST 0x163f3f0u
#define AF_CP_INPUT406_SNAPSHOT_BYTES 0xdbcu
#define AF_CP_INPUT406_COPY_BYTES 0xe70u
#define AF_CP_INPUT406_VD_OFFSET 0xdc0u
#ifdef AF_CP_CAPTURE406
#define AF_CP_INPUT406_RECORDS 4u
#else
#define AF_CP_INPUT406_RECORDS 3u
#endif
#define AF_CP_INPUT406_WORDS 10u
#define AF_CP_INPUT406_USER_VERSION 1u
#define AF_CP_INPUT406_VD_VALID 2u

typedef struct AfCpInput406Token {
    uint64_t version;
    uint32_t source,epoch,origin_snapshot_epoch,slot,mode,flags,native_vd;
    AfPreset actual;
} AfCpInput406Token;
/* Begin输出的奇数epoch票据只能结束对应写入；调用者保存至同次End。 */
typedef struct {uint32_t source,epoch;} AfCpInput406Write;
/* 内部字段禁止外部读写。published仅通过32位原子访问；其余由各记录唯一写者拥有。
 * sequence不回卷，UINT32_MAX表示永久耗尽。captured属于正在执行的同次原复制。 */
typedef struct {
    uint32_t sequence,valid,published[AF_CP_INPUT406_WORDS];
    uint32_t operation,operation_epoch,source_epoch,expected_vd;
    uint32_t captured[AF_CP_INPUT406_WORDS],seen_version_lo,seen_version_hi;
} AfCpInput406Record;
typedef struct AfCpInput406 {AfCpInput406Record records[AF_CP_INPUT406_RECORDS];} AfCpInput406;

size_t af_cp_input406_bytes(void);
/* state只在所有任务启动前清零一次，活动期不能重置。三个固定记录各自唯一写者；
 * 跨原任务仅调用read。Begin必须在原写入之前，End必须在原写入之后；helper失败
 * 仍须完整执行原memcpy/原厂流程，只关闭该目的的私有资格。无内部分配和等待。
 * 地址为已证原逻辑地址；actual为同一目的的稳定可读映射，宿主可显式提供缓冲。
 * 所有票据、预设、actual和输出须独立于state，失败不发布票据或输出。 */
int af_cp_input406_snapshot_begin(AfCpInput406 *,uint32_t destination,size_t,AfCpInput406Write *);
/* Native可expected=NULL，从实际字节读取原厂九值；其他模式必须提供匹配kind0预设。
 * USER需要非零version和用户slot；FACTORY_PENDING需要非零version和slot0。
 * NATIVE/FACTORY_PENDING均无USER_VERSION，不伪造LUT/图像身份。
 * snapshot不含DC0头；所有版本来自真实锁内拥有者，不根据九字段相等推导。 */
int af_cp_input406_snapshot_end(AfCpInput406 *,const AfCpInput406Write *,uint64_t version,
    uint32_t slot,uint32_t mode,const AfPreset *expected,const void *actual,size_t);
/* 两个E70目的只从canonical snapshot捕获token。expected_vd必须是原调用的真实VD；
 * copy_end校验目的DC0首word、九值及canonical epoch仍与Begin一致才发布派生token。 */
int af_cp_input406_copy_begin(AfCpInput406 *,uint32_t destination,uint32_t source,size_t,
    uint32_t expected_vd,AfCpInput406Write *);
int af_cp_input406_copy_end(AfCpInput406 *,const AfCpInput406Write *,const void *actual,size_t);
/* 单次有界读：只接受同一偶数stamp；忙/无效/耗尽分别返回BUSY/EMPTY/EXHAUSTED。
 * Token只证明源复制时的输入版本，不持有源、银行或图像帧引用。 */
int af_cp_input406_read(const AfCpInput406 *,uint32_t source,AfCpInput406Token *);
/* 只由该固定目的的唯一原写者调用；撤销历史资格，不触碰原字节。 */
int af_cp_input406_invalidate(AfCpInput406 *,uint32_t destination);
#endif
