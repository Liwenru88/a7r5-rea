/* 仓库已保存LUT到完整发送副本；仅唯一UI拥有者串行调用。 */
#ifndef AF_REPOSITORY_RECIPE_H
#define AF_REPOSITORY_RECIPE_H
#include "af_repository.h"
#include "af_recipe_transport.h"
/* 返回AfStoreResult；已有保存请求返回AF_PERSIST_BUSY。
 * 仅已保存的C01..C20私有记录，必须精确匹配expected_saved_revision且无uncertain状态。
 * 未替换原生六槽不由本接口猜测或迁移；真实发送对前六槽另核USER20能力。
 * 显式重读到共享三缓冲，AfStore只用局部副本；不加载catalog、不清dirty、
 * 不自动恢复旧代。新读代号、银行或摘要不同就拒绝。
 * 完整AFD1和AJR1头/基底/模型身份核验后，最后深拷贝到out。
 * AJR1完整组件语义继续由接收端decode_work核验，此处不授予成像资格。
 * out必须与repo/catalog/labels和三个缓冲完全独立；失败不发布out。
 */
int af_repository_recipe_capture(const AfRepository *,uint32_t slot,uint64_t expected_saved_revision,
    uint64_t session,uint64_t version,AfRecipeTx *out);
/* 仅检查当前内存目录、保存代号和完整工作预设；不执行I/O，不读取原缓冲。
 * 发送期间保存、清空、工作参数变化或保存请求开始后返回STALE。
 * 返回OK也不保证未受控外部进程此刻没有修改文件；不是机身成像回执。
 */
int af_repository_recipe_current(const AfRepository *,const AfRecipeTx *,uint64_t expected_saved_revision);
#endif
