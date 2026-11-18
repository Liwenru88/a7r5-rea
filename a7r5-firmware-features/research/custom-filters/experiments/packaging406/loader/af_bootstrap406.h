/* 原初始化入口调用；返回值仅为AP接线状态，不是存储或成像验收。 */
#ifndef AF_BOOTSTRAP406_H
#define AF_BOOTSTRAP406_H
#include <stdint.h>
/* .init_array[104]的原构造前入口；只安装原登记观察，不进入UI/模型。 */
int af_bootstrap406_early(uintptr_t ap_base);
int af_bootstrap406(uintptr_t ap_base);
int af_bootstrap406_status(void);
/* 仅报告近似转换服务绑定；不代表CP或图像已经生效。 */
int af_bootstrap406_reference_status(void);
/* 独立于prepare状态：BUSY等真实HELLO，完成返回机内服务绑定结果，失败不重试。 */
int af_bootstrap406_startup_status(void);
/* 配对原生分支由永久refresh观察者在真HELLO且原Main空闲时发布元数据。
 * 代码入口在prepare中预装，活跃期不再改RX权限；默认分支BUSY。 */
int af_bootstrap406_publish(void);
/* 外层必须在原UI唯一拥有者中提供已证明的目录fd；本模块从不选择数据路径。 */
int af_bootstrap406_bind_storage(int body_parent,int library);
/* 产品发布准入后才检查精确/setting挂载并交给原仓库；不回退、不改变权限。 */
int af_bootstrap406_bind_native_storage(int library);
/* 首次默认物理slot0；外层原UI可显式切换slot1。活动浏览/转换拒绝切换。
 * 原生句柄及介质源独立于body fd；初始化不读取卡，原UI确认scan才访问原Fsys。
 * 存储发布和媒体资格分开报告；未绑定完整模型不声称导入成功。 */
int af_bootstrap406_bind_native_media(unsigned slot);
int af_bootstrap406_media_status(void);
#endif
