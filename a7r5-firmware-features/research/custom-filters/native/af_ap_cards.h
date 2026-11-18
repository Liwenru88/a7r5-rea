/* 原D4双卡选择；只发布卡槽编号，不探卡、不改变媒体提供者。 */
#ifndef AF_AP_CARDS_H
#define AF_AP_CARDS_H
#include "af_slots.h"

#define AF_AP_CARDS_VERSION 1u
#define AF_CARDS_MENU_ROOT 0x1664u
#define AF_CARDS_MENU_SLOT0 0x1665u
#define AF_CARDS_MENU_SLOT1 0x1666u
#define AF_CARDS_MENU_CANCEL 0x1667u
#define AF_CARDS_MENU_DESCRIPTOR 0x63au
#define AF_CARDS_TEXT_FIRST 0x7fd00000u
#define AF_CARDS_CANCELLED (-22)

typedef struct {uint32_t version,bytes;uintptr_t ap_base;} AfApCardsBinding;
typedef struct {uint64_t generation;uint32_t slot,reserved;} AfApCardSelection;

/* 外层锁定完整AP摘要、映射及UI线程；本模块核原入口/模板并在原树查重。
 * 注册后入口、行、文字均须驻留；所有接口由原UI单拥有者串行调用。 */
int af_ap_cards_bind(const AfApCardsBinding *);
int af_ap_cards_register(void);
int af_ap_cards_enable(uint32_t);
/* 每次打开使用严格递增generation，默认取消；不调用媒体或文件接口。
 * 等待选择/尚未take时不覆盖旧结果；255次后拒绝复用文字令牌。 */
int af_ap_cards_begin(uint64_t generation);
int af_ap_cards_take(uint64_t generation,AfApCardSelection *);
int af_ap_cards_result(void);
int af_ap_cards_cancel(void);
int af_ap_cards_refresh(void);
int af_ap_cards_is_id(uint32_t);
uint32_t af_ap_cards_parent(uint32_t);
uint32_t af_ap_cards_name(uint32_t);
uint32_t af_ap_cards_compact(uint32_t);
int af_ap_cards_is_token(uint32_t);
const char *af_ap_cards_text(uint32_t);
uint32_t af_ap_cards_current(void);
void af_ap_cards_focus(uint32_t);
uint32_t af_ap_cards_disabled(void);
/* 仅外层真实ENTER成功关闭点可授予；0总能清除，+88本身不授权。
 * take仍须核本次generation；原事件ABI不带epoch，不能识别同menu迟到旧键。 */
int af_ap_cards_intent(uint32_t menu);
void af_ap_cards_action(uint32_t menu);
#endif
