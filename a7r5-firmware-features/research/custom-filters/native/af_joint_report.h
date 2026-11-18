/* 完整联合预测后的独立样本报告；不认证相机颜色。 */
#ifndef AF_JOINT_REPORT_H
#define AF_JOINT_REPORT_H
#include "af_joint.h"
typedef struct {AfGridColor colors[AF_GRID_SAMPLES];float errors[AF_GRID_SAMPLES];} AfJointReportWork;
/* 调用者保证样本未用于拟合；导入协调器另行核对颜色不重合。
 * 输入/输出/工作区须独立，失败或取消不发布报告。 */
int af_joint_report(const AfJointModel *,uint32_t base,const AfCube *,const AfJointRecipe *,
                    const AfGridSample *,size_t,AfJointReportWork *,AfGridReport *,AfGridProgress,void *);
#endif
