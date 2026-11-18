/* 显式域映射、参考整数颜色链与经验格的研究组合；不授予机身准入。 */
#ifndef AF_REFERENCE_JOINT_H
#define AF_REFERENCE_JOINT_H
#include "af_edit_joint.h"

#define AF_REFERENCE_MAP_MAX_DIMENSION 17u
#define AF_REFERENCE_MAP_MAX_PAIRS 8192u
#define AF_REFERENCE_SRGB 1u
#define AF_REFERENCE_EDIT_INPUT 2u
#define AF_REFERENCE_EDIT_OUTPUT 3u
#define AF_REFERENCE_RESEARCH 1u
#define AF_REFERENCE_ZERO_ANCHOR 2u
#define AF_REFERENCE_POST_COLOR_GRID 4u
#define AF_REFERENCE_CROSS_BASE_GRID 8u

typedef struct {
    uint32_t schema,input_domain,output_domain,dimension,base;
    float minimum[3],maximum[3];
    /* schema1：三维等距表，红轴最快，连续RGB三元组。
     * schema2：dimension=0，显式(source_sRGB3,native_u16RGB3)成对记录，
     * 按source三通道字典序严格递增；只支持sRGB→Edit输入，未知点SKIP。
     * 两种count均为float数量；数据必须在任务期间不可变。 */
    const float *values;
    size_t count;
    uint8_t source_sha256[32],context_sha256[32],data_sha256[32];
} AfReferenceMap;

typedef struct {
    uint32_t schema,flags,base,grid_base;
    int8_t reference_params[8];
    uint8_t target_cp_sha256[32],edit_source_sha256[32],grid_source_sha256[32];
    const AfEditJointInput *edit;
    const AfJointRecipe *seed;
    const AfEditJointCache *baseline;
    const AfReferenceMap *input_map,*output_map;
    const AfGridModel *grid;
} AfReferenceJointConfig;

typedef struct {
    uint32_t schema,flags,base,grid_base,research_only,camera_apply_allowed;
    int8_t reference_params[8];
    uint8_t target_cp_sha256[32],model_sha256[32],edit_source_sha256[32],
            grid_source_sha256[32],input_map_sha256[32],output_map_sha256[32];
} AfReferenceJointInfo;

typedef struct AfReferenceJoint AfReferenceJoint;
size_t af_reference_joint_state_bytes(void);
size_t af_reference_joint_work_bytes(void);

/* 单独查表会完整核对数据摘要；超出声明域或未知配对点返回SKIP，不静默外推。
 * 不预置码值范围或传递函数；不是把整数码直接归一化为sRGB。 */
int af_reference_map_eval(const AfReferenceMap *,const float input[3],float output[3]);

/* 首次state/work/candidate须清零且独立，工作区按bytes接口驻留分配。
 * baseline须为seed的已准备参考缓存；映射的context摘要与它一致。
 * 首次核对所有表与原来源，复制小型描述符；表/原上下文/baseline借用期间
 * 须由唯一拥有者保证不变，不能跨任务搬移或释放。失败不发布state；
 * work/candidate是私有暂存，可被修改，不得作活动成像上下文。
 * flags必须明确RESEARCH、ZERO_ANCHOR、POST_COLOR_GRID；不同基底的
 * 经验格另需CROSS_BASE_GRID，仅记录组合外推假设，不扩大源标定范围。 */
int af_reference_joint_init(AfReferenceJoint *,const AfReferenceJointConfig *,void *work,
                           AfEditJointCache *candidate,AfGridProgress,void *);
/* 原生构表只接收剥离grid的完整Gamma/矩阵/CC1候选，grid由后续预测消费。
 * 取消/非法候选保持已发布候选与状态；本接口不写原厂表或硬件银行。 */
int af_reference_joint_prepare(AfReferenceJoint *,const AfJointRecipe *,AfGridProgress,void *);
/* 独立16色相区增量模式，recipe.matrix须为零；数组按端点/色相区/六项排列。
 * 与旧API切换会重新准备正确模式，失败/取消保持已发布候选。
 * 仅扩展参考模型可表达空间，不改变原来源、域映射或机身准入。 */
int af_reference_joint_prepare_sector(AfReferenceJoint *,const AfJointRecipe *,
    const int16_t sector_matrix[288],AfGridProgress,void *);
/* 可作为离线求解回调，但不自动构造或注册具有设备资格的AfJointModel。
 * 候选变化时prepare一次，所有颜色共用缓存；像素取固定五列常色邻域。
 * output=经验格(clip(input+映射(候选)-映射(seed)))，这是明确近似顺序，
 * 不声明硬件像素处理顺序；失败不发布output。接口仅单拥有者串行调用。 */
int af_reference_joint_predict(void *,const AfJointRecipe *,const float input[3],float output[3]);
int af_reference_joint_predict_sector(AfReferenceJoint *,const AfJointRecipe *,
    const int16_t sector_matrix[288],const float input[3],float output[3]);
int af_reference_joint_info(const AfReferenceJoint *,AfReferenceJointInfo *);
/* 新模式的模型SHA有独立domain tag；旧info/model的SHA与回调语义保持不变。
 * 新SHA只表明16区模型版本，不提供新的实拍标定或输出域依据。 */
int af_reference_joint_info_sector(const AfReferenceJoint *,AfReferenceJointInfo *);
/* 显式为离线转换器创建完整回调，要求基底和八项参考值完全一致。
 * 只声明求解接口的目标构建和显示域；info仍固定research_only=1、
 * camera_apply_allowed=0，不登记设备能力、不改变IMPORT或成像准入。 */
int af_reference_joint_model(AfReferenceJoint *,const AfPreset *,AfJointModel *);
#endif
