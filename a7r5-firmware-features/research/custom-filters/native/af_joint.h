/* 原生联合组件与有界整数搜索；完整颜色模型由显式后端提供。 */
#ifndef AF_JOINT_H
#define AF_JOINT_H
#include "af_grid.h"
#define AF_JOINT_COMPONENTS 15u
#define AF_JOINT_SAMPLES 512u
#define AF_JOINT_EVALUATIONS 16384u
#define AF_JOINT_SKIP (-21)
#define AF_JOINT_MODEL_ERROR (-22)
typedef struct {
    uint32_t gamma[129];
    int16_t matrix[18],cc1[24];
    int8_t grid[AF_GRID_BYTES];
} AfJointRecipe;
/* 每个端点矩阵六项增量按行和为零展开成九项；不是16扇区block13。 */
int af_joint_expand_matrix(const int16_t input[18],int16_t output[27]);
int af_joint_valid(const AfJointRecipe *);
int af_joint_gamma(const uint32_t input[129],const int16_t tone[3],uint32_t output[129]);
/* work为独立驻留129点暂存；失败不发布output，避免CP嵌套消息栈大数组。 */
int af_joint_gamma_work(const uint32_t input[129],const int16_t tone[3],uint32_t work[129],uint32_t output[129]);
/* 只读逐点核对seed/tone确定性重建结果，不需要临时曲线或64位除法。 */
int af_joint_gamma_matches(const uint32_t input[129],const int16_t tone[3],const uint32_t expected[129]);
/* 576字节小端原记录，只更新129点与+0x220末点；失败不写输出。 */
int af_joint_gamma_record(const void *input,const int16_t tone[3],void *output);
/* 返回0成功，SKIP表示该原生组合不可行，其他值为模型错误。
 * 必须预测同一个完整组合，不允许只实现网格；不隐含机身颜色验收。 */
typedef int (*AfJointPredict)(void *,const AfJointRecipe *,const float input[3],float output[3]);
typedef struct {
    uint32_t schema,base_mask,components,domain;
    uint8_t cp_sha256[32],model_sha256[32];
    AfJointPredict predict;
    void *context;
} AfJointModel;
extern const uint8_t af_joint_cp_sha256[32];
/* 只验证声明和本包身份；实际标定仍由显式后端和对应证据负责。 */
int af_joint_model_valid(const AfJointModel *,uint32_t base);
typedef struct {
    uint32_t evaluations;
    uint16_t gamma_step,tone_step,matrix_step,cc1_step,grid_step;
} AfJointOptions;
typedef struct {
    AfJointRecipe current,trial;
    float target[AF_JOINT_SAMPLES][3],mass[AF_JOINT_SAMPLES];
} AfJointWork;
typedef struct {
    uint32_t evaluations,predictions,rejected,attempted_components,accepted[4];
    float initial_mse,final_mse;
    uint32_t research_only;
} AfJointFit;
#define AF_JOINT_MORE 1
/* 仅内存工作状态，不是存储或消息ABI；首次使用须清零，不允许重入。
 * samples、work及model.context在整个分批任务期间由唯一拥有者保持稳定。 */
typedef struct {
    AfJointModel model;
    AfJointOptions options;
    AfJointFit fit;
    const AfGridSample *samples;
    size_t count;
    AfJointWork *work;
    AfJointRecipe *output;
    AfJointFit *result;
    AfGridProgress progress;
    void *context;
    double best;
    uint32_t cursor[4],steps[4],tone_step,family,polarity,phase;
} AfJointState;
size_t af_joint_state_bytes(void);
/* start只准备独立目标和基线，返回MORE；不发布output/result。
 * step每次1..64个候选，MORE表示让出给原事件轮询，OK才发布完整输出。
 * 取消/错误终止本次状态，显式start可重开；完成后重复step返回STALE。 */
int af_joint_fit_start(AfJointState *,const AfJointModel *,uint32_t base,const AfCube *,
    const AfGridSample *,size_t,const AfJointRecipe *,const AfJointOptions *,AfJointWork *,
    AfJointRecipe *,AfJointFit *,AfGridProgress,void *);
int af_joint_fit_step(AfJointState *,uint32_t evaluations);
/* 训练集与完整模型显式传入，整数候选的整体8位RGB误差单调选优。
 * 有限预算、逐组交替；取消/错误不发布recipe/result。工作区不可借作输入。
 * 模型/上下文/输入在调用期间须由唯一拥有者保持稳定；非跨线程锁。 */
int af_joint_fit(const AfJointModel *,uint32_t base,const AfCube *,const AfGridSample *,size_t,
                 const AfJointRecipe *seed,const AfJointOptions *,AfJointWork *,AfJointRecipe *,
                 AfJointFit *,AfGridProgress,void *);
#endif
