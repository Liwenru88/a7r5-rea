/* 只更新CP输入字段；不代表消费者、银行或硬件已生效。 */
#ifndef AF_CP406_STATE_H
#define AF_CP406_STATE_H
#include "af_slots.h"
#define AF_CP406_STATE_BYTES 0xdbcu
/* 调用者必须持有原0x24互斥；所有内存范围独立，非法/LUT不写入。 */
int af_cp406_write_state(const AfPreset *,void *state,size_t,uint8_t *update_marker);
/* ARMv7源4.06绑定入口；只供尚未持有0x24锁的调用者。原消息分派已持锁时应调用上述叶函数。
 * 仅研究ELF，实际消息/装载位置尚未安装。
 * 成功仅表示输入已准备；释放锁出错返回AF_IO时输入可能已经改变。 */
int af_cp406_locked_prepare(const AfPreset *);
#endif
