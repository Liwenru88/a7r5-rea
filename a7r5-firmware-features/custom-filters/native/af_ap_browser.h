/* 原D4列表的只读LUT浏览；媒体来源由单一拥有者显式提供，不猜挂载点。 */
#ifndef AF_AP_BROWSER_H
#define AF_AP_BROWSER_H
#include "af_media.h"

#define AF_AP_BROWSER_VERSION 1u
#define AF_BROWSER_MENU_ROOT 0x1620u
#define AF_BROWSER_MENU_FILE_FIRST 0x1621u
#define AF_BROWSER_MENU_PREVIOUS 0x1661u
#define AF_BROWSER_MENU_NEXT 0x1662u
#define AF_BROWSER_MENU_CANCEL 0x1663u
#define AF_BROWSER_MENU_DESCRIPTOR 0x639u
#define AF_BROWSER_TEXT_FIRST 0x7fcc0000u
#define AF_BROWSER_PAGE_FILES 17u
#define AF_BROWSER_CANCELLED (-22)
typedef struct {uint32_t version,bytes;uintptr_t ap_base;} AfApBrowserBinding;
typedef struct {uint64_t generation;uint32_t index,reserved;} AfApBrowserSelection;

/* 完整AP摘要/映射/线程由外层锁定；模块核对原入口/模板并在真实树查重。
 * 注册后模块必须驻留，不支持热卸载。所有函数仅由原UI单拥有者串行调用。 */
int af_ap_browser_bind(const AfApBrowserBinding *);
int af_ap_browser_register(void);
int af_ap_browser_enable(uint32_t);
/* 输入是af_media_scan成功发布的独立副本。只复制元数据，不打开/转换文件。
 * 正在浏览时拒绝换代；同代/回退代拒绝。最多255次会话后拒绝而不复用token。
 * 发布后由外层原导航打开ROOT；本模块不伪造页面或自动确认。 */
int af_ap_browser_publish(const AfMediaList *);
/* 仅在已存在的原管理D4页（15e7/Import15ea）与本浏览D4页之间切换。
 * 复用原21f41a8的两次3b7/3bc模型事务，不调用物理屏幕manager，也不留GUI指针。
 * 逻辑父项查询原1bdb214；3bc由原1bd6384查询目标screen，不能当成逻辑父ID。
 * 活动D4内可调用show/back；原确认后的异步close由外层生命周期重开。
 * 必须在原UI线程确认回调/轮询内串行执行，不能从I/O工作线程调用。 */
int af_ap_browser_show(void);
int af_ap_browser_back(void);
int af_ap_browser_is_id(uint32_t);
uint32_t af_ap_browser_parent(uint32_t);
uint32_t af_ap_browser_name(uint32_t);
int af_ap_browser_is_token(uint32_t);
const char *af_ap_browser_text(uint32_t);
uint32_t af_ap_browser_current(void);
void af_ap_browser_focus(uint32_t);
uint32_t af_ap_browser_disabled(void);
/* 真实ENTER成功关闭点的一次性许可，0清除；无许可的+88不选择或换页。 */
int af_ap_browser_intent(uint32_t menu);
void af_ap_browser_action(uint32_t);
/* 原+88只携带menu，不保证先调用+80。确认严格匹配当前3b7/父项/分页。
 * 原ABI没有事件epoch，因此无法区分新会话同一menu的延迟旧确认；
 * 接收者仍须按selection.generation及媒体元数据复验，不可据选择声称导入成功。 */
/* 菜单返回/取消须调用cancel；没有队列/目录/保存副作用。成功选择也不是导入成功。
 * take要求同代；输出仅成功时发布，成功后消费一次。旧代不能取到新选择。 */
int af_ap_browser_cancel(void);
int af_ap_browser_take(uint64_t generation,AfApBrowserSelection *);
int af_ap_browser_result(void);
uint32_t af_ap_browser_page(void);
uint32_t af_ap_browser_rows(void);
int af_ap_browser_refresh(void);
#endif
