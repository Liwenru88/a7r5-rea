/* 原AP管理动作的单拥有者请求；此接口不执行I/O、不把入队视为保存成功。 */
#ifndef AF_AP_MANAGE_H
#define AF_AP_MANAGE_H
#include "af_slots.h"

#define AF_AP_MANAGE_VERSION 1u
#define AF_AP_MANAGE_MEDIA_MAX 64u
enum AfApManageOp { AF_MANAGE_SAVE=1, AF_MANAGE_COPY=2, AF_MANAGE_IMPORT=3, AF_MANAGE_CREATE=4, AF_MANAGE_CLEAR=5, AF_MANAGE_RENAME=6, AF_MANAGE_EXPORT=7 };
#define AF_MANAGE_CAP(op) (1u<<((op)-1u))
#define AF_MANAGE_CAP_PERSIST (AF_MANAGE_CAP(AF_MANAGE_SAVE)|AF_MANAGE_CAP(AF_MANAGE_COPY)|AF_MANAGE_CAP(AF_MANAGE_CREATE)|AF_MANAGE_CAP(AF_MANAGE_CLEAR)|AF_MANAGE_CAP(AF_MANAGE_RENAME))
enum AfApManagePhase {
    AF_MANAGE_IDLE=0, AF_MANAGE_QUEUED=1, AF_MANAGE_RUNNING=2,
    AF_MANAGE_COMMITTING=3, AF_MANAGE_DONE=4, AF_MANAGE_FAILED=5,
    AF_MANAGE_CANCELLED=6, AF_MANAGE_UNCERTAIN=7
};
enum AfApManageResult { AF_MANAGE_CANCEL=-20, AF_MANAGE_NOT_READY=-21 };

typedef struct {
    uint32_t op, source_slot, target_slot, overwrite;
    uint32_t name_bytes, media_index;
    uint64_t media_generation;
    AfPreset initial; /* IMPORT/CREATE的显式原厂基底与八项参数，必须为纯参数。 */
    char name[64];
} AfApManageRequest;
typedef struct {
    uint64_t revision;
    uint32_t present, reserved;
    AfPreset initial, saved, working;
} AfApManageSlot;
typedef struct {
    uint64_t ticket;
    AfApManageRequest request;
    AfApManageSlot source, target;
} AfApManageJob;
typedef struct {
    uint64_t ticket, generation;
    int32_t result;
    uint32_t durable, uncertain;
} AfApManageReceipt;
typedef struct {
    uint64_t next_ticket;
    AfApManageJob job;
    AfApManageReceipt receipt;
    uint32_t phase, cancel_requested;
    uint32_t progress_done, progress_total;
} AfApManage;

/* 同一原UI拥有者串行调用，当前不启动线程。所有输入/输出不得与manager或catalog
 * 重叠。只保存请求副本，不调用af_begin_save/af_finish_save；原厂12槽没有输入身份。
 * SAVE要求source==target；COPY要求不同用户槽，IMPORT/CREATE要求source==0。
 * COPY/IMPORT/CREATE覆盖已有槽必须显式overwrite=1；名称为1..63B有效UTF-8。
 * IMPORT的media_generation+media_index由同一次有界浏览返回，不接收原始路径。
 * CLEAR仅已装C07～C20，source/name/media均空，overwrite=1为显式确认；
 * 当前使用槽保护由UI拥有者在开始选择和提交前独立核对，不伪造CP回退。
 * RENAME仅已装C07～C20，source==target、overwrite=0、无media；
 * 名称1..63B有效UTF-8，成功仅改名称/保存代号，initial/saved/working均保持。
 * EXPORT仅已装C07～C20，source==target、overwrite=0、名称/media/initial为空；
 * 仅导出saved完整AFD1，不改变目录/名称/代号或dirty工作值。 */
void af_ap_manage_init(AfApManage *);
int af_ap_manage_submit(AfApManage *,const AfCatalog *,const AfApManageRequest *);
int af_ap_manage_take(AfApManage *,AfApManageJob *);
/* QUEUED取消无需执行后端；RUNNING仅请求取消，仍待任务返回；COMMITTING不取消。
 * 后端进入任何可能发布存储的步骤之前，必须调用commit_begin；该函数再检查
 * 请求所见的source/target快照和pending状态，变化/取消时不允许进入提交。 */
int af_ap_manage_cancel(AfApManage *,uint64_t ticket);
int af_ap_manage_cancelled(const AfApManage *,uint64_t ticket);
int af_ap_manage_progress(AfApManage *,uint64_t ticket,uint32_t done,uint32_t total);
int af_ap_manage_commit_begin(AfApManage *,const AfCatalog *,uint64_t ticket);
/* 成功只接收COMMITTING之后的耐久回执，核对目标代号及已保存快照。
 * 后端必须先完成真实af_persist回读；本接口不产生耐久性，不确认CP成像。
 * uncertain冻结后续请求，直至后端显式恢复成功后调用recovered。
 * 失败/取消不改目录，提交后新增working差异保留。 */
int af_ap_manage_finish(AfApManage *,const AfCatalog *,const AfApManageReceipt *);
int af_ap_manage_recovered(AfApManage *);

/* 锁定4.06的原生菜单准备；共享挂钩由同一装载拥有者串行接入。
 * 0x15e7..0x15eb在原5591行与已有C07..C20之后；注册时再次在真实树查重。
 * descriptor0x637避开原无效身份0x636。原32槽列表不增加管理行。
 * 标题/行名token只能交给原TextSprite字符重载，不能当作UXC资源查找。 */
#define AF_MANAGE_MENU_ROOT 0x15e7u
#define AF_MANAGE_MENU_SAVE 0x15e8u
#define AF_MANAGE_MENU_COPY 0x15e9u
#define AF_MANAGE_MENU_IMPORT 0x15eau
#define AF_MANAGE_MENU_CREATE 0x15ebu
#define AF_MANAGE_MENU_CLEAR 0x1602u
#define AF_MANAGE_MENU_RENAME 0x1603u
#define AF_MANAGE_MENU_EXPORT 0x1604u
#define AF_MANAGE_MENU_DESCRIPTOR 0x637u
#define AF_MANAGE_TEXT_FIRST 0x7fcb0001u
typedef struct {
    uint32_t version, bytes;
    uintptr_t ap_base;
    AfApManage *manager;
    AfCatalog *catalog;
} AfApManageMenuBinding;
typedef struct {
    uint32_t version,bytes;
    void *context;
    int (*pump)(void *,AfApManage *);
    uint32_t capabilities,reserved; /* 1u<<(op-1)，缺位动作不能提交。 */
} AfApManageService;
/* 只接受同进程已校验的真实后端；默认无能力。调用者保证函数/context终身驻留。
 * poll只在原UI线程串行执行一个QUEUED任务，不创建线程、不自行标记成功。 */
int af_ap_manage_service_bind(const AfApManageService *);
int af_ap_manage_service_poll(void);
/* 原确认后的选择界面单独绑定；不会伪造IMPORT转换能力或执行持久化。 */
typedef struct {
    uint32_t version,bytes;
    void *context;
    int (*open)(void *,uint32_t op,uint32_t source_slot);
    uint32_t capabilities,reserved;
} AfApManagePicker;
int af_ap_manage_picker_bind(const AfApManagePicker *);
/* 仅显示只读浏览的结果；不会修改队列phase或发出保存成功回执。 */
int af_ap_manage_menu_notice(uint32_t op,int result);

int af_ap_manage_menu_bind(const AfApManageMenuBinding *);
/* 原注册完成后、UI开始之前调用；追加新行、descriptor和父项，不发布父列表。
 * 原表来源/入口前像/运行树均匹配才注册；模块随后必须驻留，不能热卸载。 */
int af_ap_manage_menu_register(void);
int af_ap_manage_menu_enable(uint32_t value);
int af_ap_manage_menu_is_id(uint32_t menu);
/* 动作身份不是连续ID：CLEAR避开既有目标选择器0x15ec..0x1601。 */
uint32_t af_ap_manage_menu_for_op(uint32_t op);
uint32_t af_ap_manage_menu_parent(uint32_t menu);
uint32_t af_ap_manage_menu_name(uint32_t menu);
const char *af_ap_manage_menu_text(uint32_t token);
/* 显式用户槽上下文由原32槽选择路径传入；切槽使另存/媒体选择失效。
 * configure只准备已明确选择的目标/文件，不入队；SAVE不需要configure。
 * +80仅记录焦点；+88也可由方向键触发，只有ENTER关闭点的一次性许可可提交。 */
int af_ap_manage_menu_context(uint32_t slot);
int af_ap_manage_menu_configure(const AfApManageRequest *);
void af_ap_manage_menu_focus(uint32_t index);
uint32_t af_ap_manage_menu_current(void);
uint32_t af_ap_manage_menu_disabled(void);
/* 只能由真实ENTER获准的专用关闭调用点授权。0始终清除；许可只消费一次。
 * 原+88是值应用回调，方向键／leave也可调用它，本身不证明提交意图。 */
int af_ap_manage_menu_intent(uint32_t menu);
void af_ap_manage_menu_action(uint32_t menu);
int af_ap_manage_menu_result(void);
/* 原UI刷新查询消费一次；只对当前管理页面请求原呈现器重建快照。 */
int af_ap_manage_menu_refresh(void);

#endif
