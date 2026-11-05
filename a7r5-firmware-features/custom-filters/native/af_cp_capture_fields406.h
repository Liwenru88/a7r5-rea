/* 固定4.06的Capture字段合同；不生成版本、生命周期或成像许可。 */
#ifndef AF_CP_CAPTURE_FIELDS406_H
#define AF_CP_CAPTURE_FIELDS406_H
#include "af_slots.h"
#define AF_CP_CAPTURE_FIELDS406_NORMALIZED 47u
#define AF_CP_CAPTURE_FIELDS406_D_BYTES 0x3au
#define AF_CP_CAPTURE_FIELDS406_E_BYTES 9u
#define AF_CP_CAPTURE_FIELDS406_F_BYTES 0x4eu
typedef int (*AfCpCaptureRead)(void *,uint32_t,void *,size_t);

/* 规范顺序固定为D目标偏移升序；未写字节不参与。输出须与输入独立。
 * shadow做原正常逆展开，normalize只取实际D已写字段；失败不写输出。 */
int af_cp_capture_fields406_shadow(const uint8_t shadow[84],uint8_t normalized[47]);
int af_cp_capture_fields406_normalize(const uint8_t d[0x3a],uint8_t normalized[47]);
/* 既要求47B相同，又要求该正常期望可区分原诊断分支；相同不产生身份。 */
int af_cp_capture_fields406_matches(const uint8_t shadow[84],const uint8_t d[0x3a]);
/* 核对AA81CA→AA856E正常前向的全部已写字段；原表/全局读取均显式提供。
 * 调试覆盖、旧六marker、未知表索引/原诊断分支返回EMPTY；读取错误原样返回。
 * D/E须为拥有者保持稳定的本次快照。F4C/4D不从D推导、不改写；仅核调用
 * 期间F完整4E字节稳定，外层仍须核真实formatter/core前后的写者epoch与快照。
 * OK只是数值字段吻合，不能替代Capture出生/B覆盖/任务/scope来源资格。 */
int af_cp_capture_fields406_formatter(const uint8_t d[0x3a],const uint8_t e[9],
    const uint8_t f[0x4e],AfCpCaptureRead read,void *context);
#endif
