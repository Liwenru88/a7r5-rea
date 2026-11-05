/* 固定槽位与编辑核心。无文件/设备接口；保存成功由真实存储层确认后调用。 */
#ifndef AF_SLOTS_H
#define AF_SLOTS_H

#include <stddef.h>
#include <stdint.h>

#define AF_BUILTINS 12u
#define AF_USERS 20u
#define AF_PARAMETERS 8u

enum AfResult {
    AF_OK = 0, AF_INVALID = -1, AF_EMPTY = -2, AF_EXISTS = -3,
    AF_BUSY = -4, AF_STALE = -5, AF_IO = -6, AF_EXHAUSTED = -7
};

typedef struct {
    uint8_t base;
    uint8_t kind; /* 0：纯参数；1：已校验LUT载荷的引用。 */
    int8_t params[AF_PARAMETERS];
    uint8_t payload_sha256[32];
    uint8_t lut_sha256[32];
} AfPreset;

typedef struct {
    AfPreset snapshot;
    uint64_t expected_revision;
    uint64_t request;
    uint32_t slot;
} AfSave;

typedef struct {
    AfPreset initial, saved, working;
    uint64_t saved_revision;
    AfSave pending;
    uint8_t present;
} AfSlot;

typedef struct {
    AfSlot slots[AF_USERS];
    uint64_t next_request;
} AfCatalog;

size_t af_catalog_bytes(void);
void af_catalog_init(AfCatalog *catalog);
int af_builtin_selector(uint32_t index);
int af_validate(const AfPreset *preset);
/* 安装仅改变内存目录；调用者须先完成持久化/回读。不是机内保存实现。 */
int af_install(AfCatalog *catalog, uint32_t slot, const AfPreset *preset, int overwrite);
/* 仅在完整持久化记录校验成功后恢复；保留initial，工作值从saved开始。
 * 单一目录拥有者调用；活动保存请求存在时拒绝，不把读取当作写入确认。 */
int af_catalog_load(AfCatalog *catalog, uint32_t slot, const AfPreset *initial,
                     const AfPreset *saved, uint64_t generation);
int af_read(const AfCatalog *catalog, uint32_t slot, int saved, AfPreset *output);
int af_edit(AfCatalog *catalog, uint32_t slot, uint32_t parameter, int value);
/* 纯参数槽仅更新工作基底，保留八项及initial/saved；LUT需重新拟合后整体替换。
 * 与参数编辑相同，保存进行中允许产生新工作版本，不改已捕获的保存快照。 */
int af_edit_base(AfCatalog *catalog, uint32_t slot, uint32_t base);
int af_dirty(const AfCatalog *catalog, uint32_t slot);
/* initial=0恢复保存版本；initial=1重置到滤镜创建值，不移除LUT。 */
int af_restore(AfCatalog *catalog, uint32_t slot, int initial);
int af_begin_save(AfCatalog *catalog, uint32_t slot, AfSave *save);
int af_finish_save(AfCatalog *catalog, const AfSave *save, int write_succeeded);

#endif
