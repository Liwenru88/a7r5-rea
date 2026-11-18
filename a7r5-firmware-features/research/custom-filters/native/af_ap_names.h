/* 创意外观主页面名称专用分流；不接存储、成像或其他文字组件。 */
#ifndef AF_AP_NAMES_H
#define AF_AP_NAMES_H
#include "af_labels.h"

#define AF_AP_NAMES_BIND_VERSION 1u
#define AF_AP_NAMES_FILTER_TITLE 0x7fcf0001u
#define AF_AP_NAMES_TOKEN_FIRST 0x7fca0001u
#define AF_AP_NAMES_COMPACT_FIRST 0x7fce0000u
typedef struct {
    uint32_t version, bytes;
    uintptr_t ap_base, obj_base;
    const AfLabels *labels;
} AfApNamesBinding;

/* 外层先校验锁定4.06 AP/libObj来源及映射，后安装定向BL调用点。
 * title接主页面AP+0x2208e8c；参数页AP+0x220c8a0亦可复用，须由外层
 * 额外校验97e7231a前像，并先分流AP+0x220c8dc的基底图标来源。
 * sprite仅接AP+0x1885b38；labels须满足_Alignof(AfLabels)。
 * 不挂全局名称getter，不全局替换原20个文字资源ID。
 * labels只在真实恢复/提交回读成功后publish，原UI线程串行消费。
 * 不提供解绑：私有token可留在原模型中，模块/两入口须保持驻留。
 * AP与libObj基址均须非零且按页对齐；原基址0研究回执不可用于本绑定。 */
int af_ap_names_bind(const AfApNamesBinding *);
/* 禁用后既有token仍回原资源；必须先bind，不能因此直接移除挂钩。 */
int af_ap_names_enable(uint32_t);
/* 一旦启用过，原模型可能保留标记；即便随后禁用，也必须保持入口驻留。 */
int af_ap_names_detach_allowed(void);
uint32_t af_ap_names_title(uint32_t menu);
/* 仅D4左侧窄行使用短名称；右侧选中标题仍用title保留完整名称及状态。
 * 短标记只表示固定菜单身份，不携带文件内容；模块禁用后仍须解码。 */
uint32_t af_ap_names_compact(uint32_t menu);
/* 原字符重载深拷贝UTF-8；其返回寄存器不是状态。使用原getString检查
 * 分配后的记录，空记录回原资源。没有本模块token的资源完整委派。 */
void af_ap_names_sprite(void *sprite, uint32_t resource);
#endif
