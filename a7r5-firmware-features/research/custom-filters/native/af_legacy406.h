/* 原六款的只读内存快照与无损增量适配；不是新存储schema，不执行实际迁移。 */
#ifndef AF_LEGACY406_H
#define AF_LEGACY406_H
#include "af_joint_asset.h"
#define AF_LEGACY406_ROWS 18u
#define AF_LEGACY406_FIELDS 11u
#define AF_LEGACY406_SLOTS 6u
#define AF_LEGACY406_UNSUPPORTED (-40)
/* 字段0..2=current/still/movie旧基底；3..10=对比、高光、阴影、褪色、
 * 饱和、锐度、锐度范围、清晰度。原值每项4B，三基底meta每项40B，
 * 八参数meta每项24B，两类+8均为shadow指针。
 * 外层在原模型锁内复制两份窗口，并明确证明初始化已完成和照片域；本模块不猜就绪。
 * live/shadow存在且冲突时拒绝；absent shadow的字节不解释为真实参数。 */
typedef struct {
    uint8_t ap_sha256[32],cp_sha256[32];
    uint32_t model_ready,photo_domain;
    int32_t live[AF_LEGACY406_FIELDS][AF_LEGACY406_ROWS];
    int32_t shadow[AF_LEGACY406_FIELDS][AF_LEGACY406_ROWS];
    uint32_t shadow_mask[AF_LEGACY406_ROWS];
} AfLegacy406Frame;
typedef struct {
    uint32_t slot,name_bytes;
    char name[64];
    int16_t tone[3],matrix[27],cc1[24];
    int8_t grid[AF_GRID_BYTES];
} AfLegacy406Asset;
typedef struct {
    uint32_t slot,selector,wire,shadow_mask;
    int32_t live[AF_LEGACY406_FIELDS],shadow[AF_LEGACY406_FIELDS];
    AfLegacy406Asset asset;
} AfLegacy406Slot;
typedef struct {
    uint8_t ap_sha256[32],cp_sha256[32];
    uint32_t photo_domain;
    AfLegacy406Slot slots[AF_LEGACY406_SLOTS];
} AfLegacy406Snapshot;
typedef struct {
    int16_t tone[3],matrix[18],cc1[24];
    int8_t grid[AF_GRID_BYTES];
} AfLegacy406Basis;
/* 只接受锁定4.06已继承的六份完整名称/grid/108B增量，不把A7C2标签当R5证据。 */
int af_legacy406_asset_valid(const AfLegacy406Asset *);
/* 固定读取数组索引10..15；失败不发布输出，不修改任何源、catalog或文件。 */
int af_legacy406_capture(const AfLegacy406Frame *,const AfLegacy406Frame *,
                         const AfLegacy406Asset assets[AF_LEGACY406_SLOTS],AfLegacy406Snapshot *);
/* 27项矩阵精确逆为18项，展开回27项逐项相等才成功；tone/CC1/grid全部保留。 */
int af_legacy406_basis(const AfLegacy406Asset *,AfLegacy406Basis *);
/* 仅对外层显式给出的同条件原Gamma应用旧tone；不生成默认ST，不推断像素域。 */
int af_legacy406_gamma(const AfLegacy406Asset *,const uint32_t stock[129],uint32_t output[129]);
/* 完整旧语义缺最终Gamma/模型/源LUT和误差依据，当前一律明确UNSUPPORTED。
 * 不伪造AJR1，不把旧tone删去或再次套用；失败输出保持。 */
int af_legacy406_to_ajr1(const AfLegacy406Snapshot *,uint32_t slot,AfJointAsset *);
#endif
