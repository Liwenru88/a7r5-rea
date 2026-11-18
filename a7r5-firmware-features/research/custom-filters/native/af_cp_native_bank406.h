/* 原0x24锁下的两个驻留配方；只持有CPU原组件借用，不确认图像成功。 */
#ifndef AF_CP_NATIVE_BANK406_H
#define AF_CP_NATIVE_BANK406_H
#include "af_cp_input406.h"
#include "af_cp_runtime_asset406.h"

#define AF_CP_NATIVE_BANKS406 2u
#define AF_CP_NATIVE_WORKERS406 3u

typedef struct {
    uint32_t refs,valid,slot;
    uint64_t generation,version;
    AfPreset preset;
    AfCpRuntimeAsset406 asset;
} AfCpNativeBank406;
typedef struct {
    uint32_t state,bank;
    uint64_t generation,version,ticket;
} AfCpNativeTicket406;
typedef struct {
    uint32_t active;
    uint64_t generation,next_lease;
    AfCpNativeBank406 banks[AF_CP_NATIVE_BANKS406];
    AfCpNativeTicket406 leases[AF_CP_NATIVE_WORKERS406];
} AfCpNativeBanks406;
typedef struct {
    uint32_t worker,bank;
    uint64_t generation,version,ticket;
    const AfCpRuntimeAsset406 *asset;
    const AfPreset *preset;
} AfCpNativeLease406;

/* 整体只在boot启动其他任务前全零一次，无活动期reset。内部字段禁止外写。
 * accept/borrow/clear均由调用者持有同一原0x24互斥；release可跨原worker任务。
 * active为bank+1，零表示已退出私有配方；引用未排空的旧bank永不覆写。
 * accept只接受kind1和native_mode1；完整校验后只深copy组件需要的运行字段，
 * 不驻留拟合Gamma/native_seed；以kind0/空摘要投影发布九值。
 * accept失败不换active；borrow/release失败不改变调用者输出或引用所有权。
 * worker只接受原completion identity2/3/6，每个各有一个唯一票据槽。
 * 非active但尚未重用的bank仍可按完全相符的旧token借用，不能按同九值猜版本。
 * 所有输入和输出对象须与state及彼此独立，且保持各自类型对齐。 */
size_t af_cp_native_bank406_bytes(void);
int af_cp_native_bank406_accept_locked(AfCpNativeBanks406 *,AfCpOverride406 *,uint64_t version,
    uint32_t slot,const AfPreset *,const AfJointAsset *,uint8_t *marker);
int af_cp_native_bank406_borrow_locked(AfCpNativeBanks406 *,const AfCpInput406Token *,
    uint32_t worker,AfCpNativeLease406 *);
int af_cp_native_bank406_release(AfCpNativeBanks406 *,const AfCpNativeLease406 *);
int af_cp_native_bank406_clear_active_locked(AfCpNativeBanks406 *);
#endif
