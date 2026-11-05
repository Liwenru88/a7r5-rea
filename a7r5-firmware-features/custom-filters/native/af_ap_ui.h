/* 当前4.06原厂界面的离线接入；绑定不等于安装、成像或持久化成功。 */
#ifndef AF_AP_UI_H
#define AF_AP_UI_H

#include "af_ui.h"
#include "af_ap_lifecycle.h"
#include "af_labels.h"
#include "af_ap_manage.h"
#include "af_ap_targets.h"
extern AfLabels af_ap_labels;
extern AfApManage af_ap_manager;

#define AF_AP_BIND_VERSION 1u
#define AF_AP_IMAGE_SPAN ((uintptr_t)0x08e84000u)

typedef struct {
    uint32_t version, bytes;
    uintptr_t base, mapped_bytes, application_init;
    uint8_t ap_sha256[32];
} AfApBinding;

#define AF_AP_IMAGING_VERSION 2u
/* 对应配对协议的FACTORY_RESTORE能力；未协商时不能绑定研究发送。 */
#define AF_AP_IMAGING_FACTORY_RESTORE 0x10000u
#define AF_AP_IMAGING_SNAPSHOT_OVERLAY 0x20000u
#define AF_AP_IMAGING_FULL_RECIPE 0x40000u
#define AF_AP_IMAGING_USER20 0x80000u
#define AF_AP_IMAGING_SECTOR_MATRIX 0x100000u
/* 仅同进程UI标记，不编码进A7P1：关闭后的明确原厂事件只可尝试NATIVE退出。 */
#define AF_AP_IMAGING_NATIVE_ONLY 0x80000000u
#define AF_AP_IMAGING_REQUIRED (AF_AP_IMAGING_FACTORY_RESTORE|AF_AP_IMAGING_SNAPSHOT_OVERLAY)
typedef struct {
    uint32_t version,bytes;
    void *context;
    uint32_t (*capabilities)(void *);
    int (*send)(void *,uint32_t slot,const AfPreset *);
    int (*factory)(void *,uint32_t selector,AfPreset *);
    int (*release)(void *);
} AfApImagingBinding;
/* 显式研究接线，默认关闭。factory读取本包原锁下实际工作值；
 * send使用已协商factory恢复和快照覆盖的配对后端，slot0明确表示原厂。
 * release明确退出私有覆盖，旧六槽/特殊项不伪装为纯参数预设。
 * 回调及context驻留至AP退出；唯一UI拥有者调用，不可重入。
 * 实际快照和模式退出挂钩仍须安装，本接口不授予产品成像验收资格。 */
int af_ap_imaging_bind(const AfApImagingBinding *);
/* 仅最近一次请求/发送状态，绝非CP已准备或照片应用回执。
 * BUSY请求由原UI刷新拥有者重试；后续明确事件替换待发请求，非BUSY失败不重发。 */
int af_ap_imaging_result(void);

#define AF_AP_IMAGING_PROVIDER_VERSION 1u
typedef struct {
    uint32_t version,bytes;
    void *context;
    int (*resolve)(void *,AfApImagingBinding *);
} AfApImagingProvider;
/* 启动装载者仅发布驻留提供者，不在未知线程绑定或发送。
 * 原refresh拥有者首次满足界面/选择资格后解析；BUSY等待握手，其余失败不自动重试。
 * 成功仅绑定已有发送接口，不补发此前选择，不表示CP或照片已应用。 */
int af_ap_imaging_provider_bind(const AfApImagingProvider *);
/* UI拥有者读取：未登记NOT_READY、等待BUSY、已绑定OK或终止失败。 */
int af_ap_imaging_provider_result(void);

/* 仅AF_AP_DYNAMIC构建开放绑定。调用者须已校验原AP完整SHA-256、ELF映射、
 * 重定位和每页权限，并保证下述全部前像可读；摘要字段不是来源审计的替代。
 * 本函数再核对锚点、全部57处挂钩、额外原入口和列表描述符。
 * 只能在原初始化和任何挂钩安装之前，由单一拥有者串行调用；失败不改绑定。
 * 不修改AP、不自动挂钩、不注册新行，不发布成像成功回执。 */
int af_ap_bind(const AfApBinding *binding);
/* 只附加新行；传入自然原登记回执，不重放原5591项范围，不启用列表。 */
int af_ap_after_original_registration(const AfApRegistration *receipt);
/* 仅注册之前允许解绑；注册后新行仍属于原注册器，不能假称可安全卸载。 */
int af_ap_unbind(void);
/* 调用方已停止原UI线程；注册/启用后拒绝恢复入口，保留可能残留的文字标记。 */
int af_ap_detach_allowed(void);
uintptr_t af_ap_bound_base(void);
/* 注册完成后，在原UI线程调用；恢复描述符的原指针和计数。
 * 描述符被其他拥有者改变时拒绝覆盖。禁用不移除已注册行、不释放模块。 */
int af_ap_research_enable(uint32_t value);
/* 已提交名称缓存更新后的原UI线程通知；只请求当前槽刷新，不确认保存/成像。 */
int af_ap_label_refresh(uint32_t slot);
/* 原UI选择器绑定回调；不新增队列、不把选择接收当保存成功。 */
int af_ap_manage_ui_open(void *,uint32_t op,uint32_t source_slot);
int af_ap_manage_ui_chosen(void *,const AfApTargetChoice *);
uint32_t af_ap_manage_ui_state(void);
uint32_t af_ap_manage_ui_screen(void);
int af_ap_manage_ui_result(void);
/* 仅扩展创意外观描述符的当前selector；原厂690getter保持独立。 */
uint32_t af_ap_current(void);
uint32_t af_ap_rename_state(void);

#endif
