/* 原厂界面接入前的身份/参数分流。无AP绝对地址、全局挂钩或文件I/O。 */
#ifndef AF_UI_H
#define AF_UI_H

#include "af_slots.h"

#define AF_UI_ROWS 33u
#define AF_UI_NATIVE 1
/* 0x15d8是原厂无效身份，研究身份必须避开；仍需全局消费者审计。 */
#define AF_UI_NEW_FIRST 0x15d9u
#define AF_UI_NEW_LAST 0x15e6u

enum AfUiKind { AF_UI_BUILTIN = 0, AF_UI_USER = 1, AF_UI_SPECIAL = 2 };

typedef struct {
    uint32_t menu, kind, slot, selector, native_index;
} AfUiRoute;

/* 原厂身份不变；新增身份仅对已核验4.06行注册表排除冲突，尚未安装。
 * 用户槽native_index始终为UINT32_MAX，禁止用于原厂18项数组。
 * 所有失败不发布输出；对象须独立，调用者串行调用并固定本次菜单身份。 */
int af_ui_item(uint32_t row, AfUiRoute *output);
int af_ui_resolve(uint32_t menu, AfUiRoute *output);
/* 原厂外观返回AF_UI_NATIVE且不触碰输出，由AP适配器委派原函数。
 * 用户槽返回AF_OK才表示已读/修改工作值；不表示CP生效或持久化。
 * direction沿用原厂：0增加，1减少；到达边界保持当前值。 */
int af_ui_read(const AfCatalog *catalog, uint32_t menu, uint32_t parameter, int *output);
int af_ui_step(AfCatalog *catalog, uint32_t menu, uint32_t parameter,
               uint32_t direction, int *output);
int af_ui_assign(AfCatalog *catalog, uint32_t menu, uint32_t parameter,
                 int value, int *output);

/* 原厂显示对象+0x34开始为8组12字节记录，+0x94为布局字段。
 * 只写已证明字段，保留记录内填充及对象其他内容；失败不发布。
 * inhibited须为0/1：0允许、1受限。调用方负责确认模式，不推断照片模式。 */
int af_ui_snapshot(const AfCatalog *catalog, uint32_t menu,
                   const uint8_t inhibited[AF_PARAMETERS], void *output);

#endif
