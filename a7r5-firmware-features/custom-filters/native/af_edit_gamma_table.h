/* Edit整数域的完整MainGamma表重建；不提供sRGB桥或机身应用许可。 */
#ifndef AF_EDIT_GAMMA_TABLE_H
#define AF_EDIT_GAMMA_TABLE_H
#include "af_grid.h"
#define AF_EDIT_GAMMA_POINTS 128u
#define AF_EDIT_GAMMA_TABLE_ENTRIES 65536u
#define AF_EDIT_GAMMA_CONTRAST_ENTRIES 1025u
#define AF_EDIT_GAMMA_SECONDARY_ENTRIES 16384u
typedef struct { uint16_t table[AF_EDIT_GAMMA_TABLE_ENTRIES]; } AfEditGammaWork;

/* 显式128点递增横轴及18位单调纵值，均从0开始；横轴不超过INT32_MAX。
 * contrast为1025个非负int32；原查表右索引同样截至1023，末项只做有效性校验。
 * 正半表坐标为128*i，先float32插值及截断、ASR2、contrast插值、LSR2。
 * 负半表按原倒序低16位存储，不替换为臆测的奇对称查表。
 * work须与输入及output全部分离；失败/取消仅改变work，不发布output。
 * 回调非零返回AF_GRID_CANCELLED。调用期间由单一拥有者保持缓冲稳定。 */
int af_edit_gamma_table(const uint32_t axis[128], const uint32_t values[128],
                         const int32_t contrast[1025], AfEditGammaWork *,
                         uint16_t output[65536], AfGridProgress, void *context);
/* 只检查正半表的signed16单调性；每个y找NEXT值严格小于y的点数。
 * main inverse原index0不写，使用显式initial_zero保存该语义。
 * 负半表及重复值的左边界均保持原次序；未知/非单调输入拒绝。
 * 工作区、源表、输出分离；取消或失败不发布输出。 */
int af_edit_gamma_main_inverse(const int16_t gamma[65536], uint16_t initial_zero,
                               AfEditGammaWork *, uint16_t output[65536],
                               AfGridProgress, void *context);
/* 原分配可能更大；此接口仅构造原消费者已使用的前16384项。 */
int af_edit_gamma_secondary_inverse(const int16_t gamma[65536], AfEditGammaWork *,
                                    uint16_t output[16384], AfGridProgress, void *context);
#endif
