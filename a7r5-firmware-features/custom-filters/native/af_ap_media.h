/* 显式介质服务到原D4只读浏览；不提供模型、导入提交或保存成功回执。 */
#ifndef AF_AP_MEDIA_H
#define AF_AP_MEDIA_H
#include "af_ap_browser.h"
#include "af_ap_manage.h"
#define AF_AP_MEDIA_VERSION 1u
enum AfApMediaPhase {AF_AP_MEDIA_IDLE=0,AF_AP_MEDIA_BROWSING=1,
    AF_AP_MEDIA_READ_READY=2,AF_AP_MEDIA_CANCELLED=3,AF_AP_MEDIA_FAILED=4};
typedef int (*AfApMediaScan)(int,uint64_t,AfMediaList *,AfMediaList *);
typedef int (*AfApMediaRead)(int,const AfMediaList *,uint32_t,void *,size_t,
                            AfMediaSource *,AfGridProgress,void *);
typedef struct {
    uint32_t version,bytes;
    int32_t directory;uint32_t reserved;
    AfApMediaScan scan;AfApMediaRead read;
    void *source;size_t capacity;
} AfApMediaBinding;
typedef struct {
    uint64_t generation;
    uint32_t index,reserved;
    AfMediaSource source;
} AfApMediaInfo;
/* 转换服务只接收已稳定读取的选择身份；不得借此回执Imported。
 * prepare复制列表和摘要，request提供纯参数基底、名称及同代选择。
 * 所有函数与context驻留在同一UI拥有者；cancel仅释放尚未提交的选择，
 * 活动转换须返回BUSY，调用者保持原fd/缓冲直到实际任务结束。 */
typedef struct {
    uint32_t version,bytes;
    void *context;
    int (*prepare)(void *,int,const AfMediaList *,const AfApMediaInfo *);
    int (*request)(void *,AfApManageRequest *);
    int (*cancel)(void *);
} AfApMediaImporter;
/* 与v1目录fd接口并存；不改已有结构布局，不允许混绑两种导入器。 */
typedef struct {
    uint32_t version,bytes;
    AfMediaProvider provider;
    void *source;size_t capacity;
} AfApMediaProviderBinding;
typedef struct {
    uint32_t version,bytes;
    void *context;
    int (*prepare)(void *,const AfMediaProvider *,const AfMediaList *,const AfApMediaInfo *);
    int (*request)(void *,AfApManageRequest *);
    int (*cancel)(void *);
} AfApMediaProviderImporter;
int af_ap_media_provider_bind(const AfApMediaProviderBinding *);
int af_ap_media_provider_rebind(const AfApMediaProviderBinding *);
int af_ap_media_provider_importer_bind(const AfApMediaProviderImporter *);
/* 原生选卡服务只重绑提供者，不枚举／读取／转换；真实UI确认后单拥有者调用。
 * 回调成功必须已完成对应slot0/1的provider_rebind；失败保持旧提供者。
 * context／函数驻留到进程结束，不能与源工作区或media状态交叠。 */
typedef struct {
    uint32_t version,bytes;
    void *context;
    int (*select)(void *,uint32_t slot);
} AfApMediaCardService;
int af_ap_media_card_service_bind(const AfApMediaCardService *);
int af_ap_media_card_available(void);
int af_ap_media_card_select(uint32_t slot);
/* 最近一次成功选卡；UINT32_MAX表示尚未选择，不代表物理插卡状态。 */
uint32_t af_ap_media_card_current(void);
int af_ap_media_importer_bind(const AfApMediaImporter *);
/* 仅在READ_READY且prepare成功后提供模板；目标槽和覆盖许可由原D4选择器补全。 */
int af_ap_media_import_request(AfApManageRequest *);
/* 所有调用仅限同一UI拥有者。fd／函数／源缓冲保持至成功rebind且不可被外层复用。
 * source仅为可丢弃工作区；失败不发布info。源缓冲不得与本模块／浏览器别名。
 * scan/read来自已核对的真实系统服务；测试回调不能取得产品或机身资格。 */
int af_ap_media_bind(const AfApMediaBinding *);
/* 外层明确提供新卡／目录fd时重绑；浏览中或转换服务仍借用输入时拒绝。
 * 成功后旧fd／缓冲方可释放。
 * 保留单调代号，清除旧读取状态；不是自动探测卡，也不关闭调用方fd。 */
int af_ap_media_rebind(const AfApMediaBinding *);
/* 仅在真实Import确认时调用。浏览器show核对原当前menu及其真正父项。
 * open不读文件、不提交管理任务；首次扫描绑定目录身份，后续身份变化拒绝。 */
int af_ap_media_open(void);
/* 原确认会关闭D4。延迟到原manager回到主菜单后用prepare只准备真实列表，
 * 由外层原生命周期设置3b2并打开D4；不伪造旧Import页面状态。 */
int af_ap_media_prepare(void);
/* 原UI刷新串行处理换页／选择；稳定读回后调用显式转换服务准备目标选择。
 * 未绑定服务仍返回NOT_READY；成功仅表示可选目标，尚未转换、保存或成像。
 * 同步读取最多8MiB；这里不承诺读取期间的按键取消，浏览阶段可取消。
 * 完整转换/成像未接通前，不能将READ_READY当Imported或Saved。 */
int af_ap_media_poll(void);
/* 选择器已由原框架关闭时消费选择／取消与读取，不调用show/back或重开页面。
 * 返回值同poll；外层再用原生命周期打开父页。 */
int af_ap_media_finish(void);
/* 外层MENU／离开浏览页时调用，不强行打开别的页面，不产生队列请求。 */
int af_ap_media_cancel(void);
uint32_t af_ap_media_phase(void);
int af_ap_media_result(void);
int af_ap_media_snapshot(AfApMediaInfo *);
const char *af_ap_media_name(void);
int af_ap_media_refresh(void);
#endif
