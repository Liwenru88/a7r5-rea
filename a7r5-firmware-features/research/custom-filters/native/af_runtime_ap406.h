/* 原AP界面的纯参数发送入口；必须与启用PRESET的CP模块成对绑定。 */
#ifndef AF_RUNTIME_AP406_H
#define AF_RUNTIME_AP406_H
#include "af_runtime.h"
/* 调用方提供稳定的工作预设副本；不读取目录、不开线程。
 * 兼容就绪后使用真实启动会话和单调发送版本；竞争只返回AF_BUSY。
 * AF_OK仅表示原发送器接受，不代表CP已准备、成像、保存或帧释放。
 * 原发送失败后关闭私有发送，缓冲所有权仍沿原证据边界，不猜测free。 */
int af_ap_runtime_send_preset(uint32_t slot,const AfPreset *);
/* 与PRESET共用会话及单调版本；要求对端已协商快照覆盖，AF_OK仍仅表示发送接受。
 * 新USER20配对端在关闭后，明确原厂事件可消耗一次NATIVE退出尝试；失败不重发，
 * 仍关闭LUT/参数发送，不重建握手、不猜测释放原驱动buffer或已take的CP对象。 */
int af_ap_runtime_release_preset(void);
/* AF_FACTORY_RESTORE406配对构建中，slot0为原厂完整工作快照，仍走同一PRESET。
 * 只读返回已发布的协议能力或0；界面不得直接读取/轮询AfRuntime。 */
uint32_t af_ap_runtime_preset_capabilities(void);
/* 仅观察连接快照：BUSY尚未就绪，IO已关闭，OK已发布；不触碰通信拥有者普通字段。
 * 不启动或重建握手，不代表CP参数或图像完成。 */
int af_ap_runtime_preset_status(void);
/* 最近一次发送尝试的版本；失败同样消耗版本，不是CP/图像回执。 */
uint64_t af_ap_runtime_last_attempted_version(void);
#ifdef AF_RECIPE_BRIDGE406
#include "af_recipe_transport.h"
/* 内部UI资格：已完成真实HELLO且当前关闭，并协商USER20+SNAPSHOT。
 * 不是新wire能力，不代表剩余尝试次数、CP已退出或连接已恢复。 */
int af_ap_runtime_native_only_capable(void);
/* 调用期间源由唯一UI拥有者保持；先深拷贝，再沿原发送器有界发送28帧。
 * timeout_ms须为1..60000，源错/未协商不消耗版本，发送尝试消耗共享版本。
 * AF_OK仅表示28次发送被接受；等待ACK时拒绝其他私有发送。
 * C01..C06仅在另有USER20协商能力时发送；未替换的原生六槽仍走原路径。
 * 错源/旧ACK不改变状态，超时或发送错误关闭私有发送，不自动重发。 */
int af_ap_runtime_send_recipe(uint32_t slot,const AfPreset *,const void *,size_t,uint32_t timeout_ms);
/* 原发送锁内给出真实会话和下一单调版本，由唯一UI拥有者读取已保存完整配方。
 * capture不得重入发送；输出必须深拷贝且与expected完全一致。失败不消耗版本。
 * 文件读取不阻塞原通信任务；捕获完毕后才开始发送截止计时。 */
typedef int (*AfApRecipeCapture406)(void *,uint32_t,const AfPreset *,uint64_t,uint64_t,AfRecipeTx *);
int af_ap_runtime_send_stored_recipe(uint32_t slot,const AfPreset *,AfApRecipeCapture406,void *,uint32_t timeout_ms);
/* AF_BUSY等待决定；AF_OK表示得到匹配ACK，实际决定在out.status。
 * ACK只确认软件prepared／拒绝，不代表EVF/JPG。失败不发布out。
 * 与send_preset一样仅唯一UI拥有者调用；不会清除回执或隐式开始下一事务。 */
int af_ap_runtime_recipe_result(AfRecipeAck *out);
#endif
#endif
