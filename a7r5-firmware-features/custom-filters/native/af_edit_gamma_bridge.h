/* 公开Edit128点到当前CP129点的研究参数重采样；不是像素域桥。 */
#ifndef AF_EDIT_GAMMA_BRIDGE_H
#define AF_EDIT_GAMMA_BRIDGE_H
#include "af_gamma406.h"
/* 限定已核对轴：Edit_x/32与CP前127点及末点精确相等，CP独有61440。
 * 保留128共同点纵值；缺点按纵值线性插值后向下取整。不减半、不按末点归一化。
 * 只保留18位单调曲线，保持CP原记录元数据；失败不发布，输入输出不能重叠。
 * 调用成功只生成研究记录，不确认纵值物理等价或授予原厂/用户槽成像应用许可。 */
int af_edit_gamma_bridge(const uint32_t edit_x[128], const uint32_t edit_y[128],
                          const void *cp_record, void *output_record);
#endif
