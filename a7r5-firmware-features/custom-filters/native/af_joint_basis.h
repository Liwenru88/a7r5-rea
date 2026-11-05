/* 受约束17维原生基函数与网格搜索；复用显式完整模型，不提供相机标定。 */
#ifndef AF_JOINT_BASIS_H
#define AF_JOINT_BASIS_H
#include "af_joint.h"
#define AF_JOINT_BASIS_CONTROLS 17u

typedef struct {
    uint32_t evaluations;
    uint16_t tone_step,matrix_step,cc1_step,grid_step;
    uint16_t tone_bound[3],matrix_bound,cc1_bound;
} AfJointBasisOptions;

typedef struct {
    AfJointModel model;
    AfJointBasisOptions options;
    AfJointFit fit;
    AfJointRecipe seed;
    const AfGridSample *samples;
    size_t count;
    AfJointWork *work;
    AfJointRecipe *output;
    AfJointFit *result;
    AfGridProgress progress;
    void *context;
    double best;
    int16_t controls[AF_JOINT_BASIS_CONTROLS];
    uint32_t cursor[4],steps[4],family,polarity,phase;
} AfJointBasisState;

size_t af_joint_basis_state_bytes(void);
/* controls依次为3项Q10明暗、6项共享矩阵增量和8项共享CC1增量。
 * 每个原始端点保留自己的基值，再加同一增量；不修改原厂基底或输入。
 * Gamma始终从seed.gamma一次重建，避免多轮累积舍入漂移。保留seed网格。
 * 非法输入返回INVALID；无法用原生范围表达返回SKIP；失败不发布output。 */
int af_joint_basis_recipe(const AfJointRecipe *seed,const int16_t controls[17],
                          AfJointRecipe *output);
/* state首次清零；state/work/输出和全部输入独立。start复制seed/model/options，
 * samples和model.context须由唯一拥有者保持稳定；不得搬动活动state。
 * 步长及边界均为原生整数，tone/矩阵/CC1边界1..1024，网格步长1..32。
 * 边界只限制相对seed的共享增量，不表示模型已标定该范围。
 * start只准备基线，返回MORE；step每次1..64个候选，完成前不发布output/result。
 * 输出与原AfJointRecipe完全相同，最终值已量化；不改变既有消息或存储ABI。 */
int af_joint_basis_start(AfJointBasisState *,const AfJointModel *,uint32_t base,
    const AfCube *,const AfGridSample *,size_t,const AfJointRecipe *,
    const AfJointBasisOptions *,AfJointWork *,AfJointRecipe *,AfJointFit *,
    AfGridProgress,void *);
int af_joint_basis_step(AfJointBasisState *,uint32_t budget);
/* 同一状态机的同步包装。取消、模型错误或非法输入均不发布候选和统计。 */
int af_joint_basis_fit(const AfJointModel *,uint32_t base,const AfCube *,
    const AfGridSample *,size_t,const AfJointRecipe *,const AfJointBasisOptions *,
    AfJointWork *,AfJointRecipe *,AfJointFit *,AfGridProgress,void *);
#endif
