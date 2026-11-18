/* 常驻ST参考近似模型接入实际导入服务；不开放CP成像或其他基底。 */
#ifndef AF_REFERENCE_IMPORT_H
#define AF_REFERENCE_IMPORT_H
#include "af_reference_joint.h"
/* 唯一UI拥有者调用，须在界面服务能力快照发布前完成。
 * 首次构造固定上游预览近似和可达样本，随后复用；不读设备或相机。
 * 服务关闭钩子解除借用，常驻缓冲保留至进程结束，最多一份。
 * 分配/来源/样本失败不绑定IMPORT，不改变已保存槽或原厂表。 */
int af_reference_import_bind(void *service);
/* 只供确认无活动任务的service_close调用；不执行I/O或释放借用中对象。 */
void af_reference_import_closed(void *service);
int af_reference_import_info(void *service,AfReferenceJointInfo *);
#endif
