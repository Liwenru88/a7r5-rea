/* 原厂媒体模型只读快照；调用者须处于原UI模型已就绪的同一线程。 */
#ifndef AF_MEDIA_SNAPSHOT406_H
#define AF_MEDIA_SNAPSHOT406_H
#include <stddef.h>
#include <stdint.h>
#include "af_slots.h"

#define AF_MEDIA_SNAPSHOT406_BYTES 0x150u
#define AF_MEDIA_SNAPSHOT406_AP_SPAN 0x8e84000u
typedef struct {
    uint8_t bytes[AF_MEDIA_SNAPSHOT406_BYTES];
} AfMediaSnapshot406;

/* ap_base/ap_span须来自调用者已核对完整源摘要和映射的同包AP绑定。
 * 只在late原UI模型ready后调用；本函数不创建原模型、锁、scope或线程。
 * 原lock→getter→复制0x150→unlock在同一调用线程内完成；随后才发布output。
 * output不得与整个AP映射交叠。失败保持output，不向调用者泄露原全局指针。
 * 副本包含原3×0x70记录；仅槽0/1已有物理卡槽语义，第三项不推断。
 * 原getter与锁函数前像是绑定防误用检查，不代替完整源/生命周期审核。 */
int af_ap_media_snapshot406(uintptr_t ap_base,size_t ap_span,AfMediaSnapshot406 *output);
#endif
