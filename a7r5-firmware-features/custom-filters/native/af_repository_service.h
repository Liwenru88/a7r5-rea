/* 同一AP进程的持久化后端胶合；上下文驻留至绑定者退出，不是独立线程。 */
#ifndef AF_REPOSITORY_SERVICE_H
#define AF_REPOSITORY_SERVICE_H
#include "af_repository.h"
#include "af_ap_media.h"
#include "af_recipe_transport.h"
/* parent_fd必须由隔离客体/经准入的机内挂载明确提供；不打开SD或系统路径。
 * 保留marker=0并显式解码混合文档；IMPORT总能接收完整配方，CUBE另需完整模型。
 * 成功或PARTIAL返回拥有者；status保留实际恢复结果，NULL表示未开库。 */
void *af_repository_service_open(int parent_fd,AfCatalog *,AfLabels *,int *status);
uint32_t af_repository_service_capabilities(void *);
/* 同一拥有者在无活动pump时显式绑定媒体库目录；复制fd，不探测路径。
 * directory=-1解除绑定；不能绑定body仓库本身。仅绑定后提供EXPORT能力。
 * 导出失败文件不会被本接口删除，解除不把不确定回执标记为成功。 */
int af_repository_service_bind_library(void *,int directory_fd);
/* 显式完整联合模型和独立工作区；NULL解除。模型context/样本/工作区保持到解除。
 * source/name/listing/directory由真实浏览选择覆盖，不从binding猜测介质路径。
 * 声明有效只开放研究转换，不授予机身色彩标定或CP成像资格。 */
int af_repository_service_bind_import(void *,const AfRepositoryImport *binding);
/* 生成供af_ap_media_importer_bind使用的驻留回调；调用方负责同一UI拥有者及寿命。
 * 未绑定完整模型时仅CUBE prepare返回NOT_READY；配方直接校验保存。
 * request仅为选槽模板，不以文件读取或保存回执声明成像成功。 */
int af_repository_service_media_importer(void *,AfApMediaImporter *);
int af_repository_service_media_provider_importer(void *,AfApMediaProviderImporter *);
int af_repository_service_pump(void *,AfApManage *);
/* 唯一UI拥有者同步捕获已保存槽的完整载荷及当前八值；输出独立深副本。
 * session/version必须来自发送器锁内实际会话，不猜测版本、不改变工作值。
 * 导入或pump活动时BUSY，坏记录/持久化不确定拒绝；返回AfResult。 */
int af_repository_service_recipe_capture(void *,uint32_t,const AfPreset *,uint64_t,uint64_t,AfRecipeTx *);
/* 仅在没有已绑定/活动UI调用时使用；禁止在仍驻留的AP服务下释放上下文。 */
int af_repository_service_close(void *);
#endif
