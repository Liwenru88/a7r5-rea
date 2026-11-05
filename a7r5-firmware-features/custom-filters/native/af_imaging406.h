/* 已协商通信后端与原UI研究发送的具体胶合，不自动安装或启用。 */
#ifndef AF_IMAGING406_H
#define AF_IMAGING406_H
#include "af_ap_ui.h"
#include "af_recipe_transport.h"
#define AF_IMAGING406_RECIPE_SOURCE_VERSION 1u
typedef struct {
    uint32_t version,bytes;
    void *context;
    int (*capture)(void *,uint32_t,const AfPreset *,uint64_t,uint64_t,AfRecipeTx *);
} AfImaging406RecipeSource;
/* 存储启动后发布一次；context和函数驻留至AP退出，唯一UI拥有者使用。
 * 未绑定时不宣告FULL_RECIPE，纯参数绑定行为保持；不读取原厂文件路径。
 * 通信关闭后仅已协商USER20端提供内部NATIVE_ONLY资格；明确原厂事件走退出，
 * 不恢复FULL_RECIPE、普通参数发送或握手，发送接受不代表CP或图像已退出。 */
int af_imaging406_bind_recipe_source(const AfImaging406RecipeSource *);
/* 调用方先核对相同AP映射/通信导入并完成HELLO；在原UI线程将返回结构传给
 * af_ap_imaging_bind。ap_base及三个模块须驻留至AP退出，输出不得覆盖原映像。
 * 未协商factory与snapshot-overlay能力时返回BUSY且不发布；成功仅表示请求接口就绪。
 * 原快照和模式退出挂钩、实际装载仍须核对，不授予产品成像资格。 */
int af_imaging406_binding(uintptr_t verified_ap_base,AfApImagingBinding *);
#endif
