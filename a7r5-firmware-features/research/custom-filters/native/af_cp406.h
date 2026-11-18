/* 4.06纯参数前缀适配。只处理字节，不提供成像确认、帧引用或安装入口。 */
#ifndef AF_CP406_H
#define AF_CP406_H
#include "af_slots.h"

#define AF_CP406_PREFIX_BYTES 0xe70u

/* source为当前帧原参数前缀；destination须独立且由调用方拥有。
 * 保留所有其他字节，仅替换基底和八项字段。size同时约束两个缓冲区。
 * 调用期间source须稳定，调用方负责同步及帧引用管理。
 * 不能用此前缀单独构造完整0xc4上下文；不支持LUT载荷。 */
int af_cp406_overlay(const AfPreset *preset, const void *source, void *destination,
                     size_t size);
/* 仅确认字段相符，绝不能当作CP应用成功、任务完成或帧释放。 */
int af_cp406_matches(const AfPreset *preset, const void *snapshot, size_t size);
#endif
