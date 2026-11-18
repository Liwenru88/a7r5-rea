/* 原D4的用户目标槽选择；只回调明确选择，不执行I/O或确认已保存。 */
#ifndef AF_AP_TARGETS_H
#define AF_AP_TARGETS_H
#include "af_ap_manage.h"
#define AF_AP_TARGETS_VERSION 2u
#define AF_AP_TARGET_CHOICE_VERSION 2u
#define AF_TARGETS_ROOT 0x15ecu
#define AF_TARGETS_SLOT_FIRST 0x15edu
#define AF_TARGETS_CANCEL 0x1601u
#define AF_TARGETS_DESCRIPTOR 0x638u
#define AF_TARGETS_TEXT_FIRST 0x7fcd0000u
#define AF_TARGETS_COPY 2u
#define AF_TARGETS_IMPORT 3u
#define AF_TARGETS_CREATE 4u
#define AF_TARGETS_CLEAR 5u
#define AF_TARGETS_EXPORT 7u
#define AF_TARGETS_CANCELLED (-23)
#define AF_TARGETS_CONFIRM_REQUIRED (-24)
enum AfApTargetsStage {AF_TARGETS_SELECT=1,AF_TARGETS_CONFIRM_WAIT=2,AF_TARGETS_CONFIRM=3};
typedef struct {
    uint32_t version,bytes;
    uint64_t generation;
    uint32_t op,source_slot,target_slot,overwrite;
    AfApManageSlot source,target;
} AfApTargetChoice;
_Static_assert(sizeof(AfApTargetChoice)==512,"目标选择包必须为512字节");
typedef struct {
    uint32_t version,bytes;
    uintptr_t ap_base;
    const AfCatalog *catalog;
    void *context;
    int (*chosen)(void *,const AfApTargetChoice *);
} AfApTargetsBinding;
/* 外层校验完整AP及映射，所有调用在原UI线程串行。chosen/context须终身驻留；
 * 回调只在获准ENTER关闭点消费许可后调用一次，须复制choice，不得保留临时指针。
 * chosen返回AF_OK仅代表选择已接收，不代表保存成功。模块不访问管理队列。 */
int af_ap_targets_bind(const AfApTargetsBinding *);
int af_ap_targets_register(void);
int af_ap_targets_enable(uint32_t);
/* generation由UI单拥有者单调分配；COPY要求已安装source，CREATE/IMPORT source=0。
 * 快照校验source及目标的initial/saved/working/revision/pending；变化时拒绝旧确认。
 * C01..C06只在用户显式二次确认后写overlay；未替换仍原native，禁止自动迁移。
 * 同槽COPY拒绝；C07..C20已装槽进入二次确认。
 * IMPORT/COPY及管理动作接受有效完整LUT快照；CREATE仍只覆盖纯参数目标。
 * 确认页默认取消；重新呈现就绪后第二次真实ENTER才产生overwrite=1选择包。
 * 旧六overlay尚不存在时target.present仍0，overwrite1表示明确替换原生槽。
 * 最多255个页面代际，token不回绕；取消后可用新generation重开。 */
int af_ap_targets_begin(uint32_t op,uint32_t source_slot,uint64_t generation);
/* 只清空已装overlay；旧六清空后tombstone回原native。protected_slot为实际当前用户槽或0（原厂）。
 * 与CREATE/COPY相同，第一次选择后必须原D4重新呈现默认取消的确认页。 */
int af_ap_targets_begin_clear(uint32_t protected_slot,uint64_t generation);
/* 已安装overlay的已保存完整版本导出；未overlay旧六不迁移、不导出原生私有结构。
 * 直接呈现默认取消的两行确认。
 * 只回传同槽选择及完整快照，overwrite始终0；不在此写文件或确认成功。 */
int af_ap_targets_begin_export(uint32_t source_slot,uint64_t generation);
/* 只复用原3b7/3bc事务；逻辑父项经1bdb214，目标screen经1bd6384。
 * 这两事务本身不重建物理D4；外层负责已证明的原页面生命周期。 */
int af_ap_targets_show(void);
int af_ap_targets_back(void);
int af_ap_targets_is_id(uint32_t);
uint32_t af_ap_targets_parent(uint32_t);
uint32_t af_ap_targets_name(uint32_t);
int af_ap_targets_is_token(uint32_t);
const char *af_ap_targets_text(uint32_t);
int af_ap_targets_available(uint32_t menu);
uint32_t af_ap_targets_current(void);
uint32_t af_ap_targets_stage(void);
/* 外层已证原manager实际打开D4，且原初始化选中取消后调用；不自行开屏。 */
int af_ap_targets_presented(void);
/* 确认页两行的短标签；普通槽行返回空，由既有Cxx短名路由处理。 */
const char *af_ap_targets_command_text(uint32_t menu);
void af_ap_targets_focus(uint32_t);
uint32_t af_ap_targets_disabled(void);
/* 真实ENTER成功关闭点的一次性许可，0清除；方向键／leave不得授权。 */
int af_ap_targets_intent(uint32_t menu);
void af_ap_targets_action(uint32_t);
/* +88本身不证明确认，另有一次性intent；继续匹配当前3b7/真实父项/目录快照。
 * 原ABI未传事件epoch，无法识别新会话相同menu的延迟旧确认；
 * chosen仍携带当前generation供管理拥有者和后端再次验证。 */
int af_ap_targets_cancel(void);
int af_ap_targets_result(void);
int af_ap_targets_refresh(void);
#endif
