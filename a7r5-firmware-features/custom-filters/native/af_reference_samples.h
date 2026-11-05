/* 原生空间实际前向样本；灰阶/暖色标签仅为输入cohort代理，不是实拍人像。 */
#ifndef AF_REFERENCE_SAMPLES_H
#define AF_REFERENCE_SAMPLES_H
#include "af_reference_domain.h"
#define AF_REFERENCE_SAMPLE_PROXY_STEPS 65u
#define AF_REFERENCE_SAMPLE_MAX_SIDE 17u
#define AF_REFERENCE_SAMPLES_INSUFFICIENT (-32)
typedef struct {
    uint32_t schema,base,side;
    uint16_t native_maximum[3];
    const AfEditJointCache *baseline;
} AfReferenceSamplesConfig;
typedef struct {
    uint32_t evaluations,unique,duplicates,training,validation,gray_validation,warm_validation;
    uint32_t occupied_cells,research_only,camera_apply_allowed;
    uint64_t training_cells,validation_cells;
    uint8_t context_sha256[32],recipe_sha256[32],policy_sha256[32],source_sha256[32];
} AfReferenceSamplesReport;
typedef struct {
    float *pairs;size_t pair_capacity; /* float数量，至少6*(side^3+130) */
    float *output_values;size_t output_capacity; /* 至少24个float */
    AfGridSample *training;size_t training_capacity; /* 2..512 */
    AfGridSample *validation;size_t validation_capacity; /* 3..4096 */
    AfReferenceMap *input_map,*output_map;
    AfReferenceSamplesReport *report;
} AfReferenceSamplesBuffers;
typedef struct AfReferenceSamplesState AfReferenceSamplesState;
size_t af_reference_samples_state_bytes(void);
size_t af_reference_samples_work_bytes(void);
/* state/work及所有输入输出独立，首次state清零，借用baseline在任务期间固定。
 * side=3..17，输入lattice按x^2取整；另65等通道与65暖色(1,.72,.48)输入。
 * 每点真实af_edit_joint_eval，输出按固定policy O(code)=code/16383解释。
 * 候选pairs和训练/验证缓冲可被修改，map/report只在完整成功后发布。
 * source RGB去重并保留确定代表，按RGB字典序排序；同4x4x4颜色区域不跨集。
 * 未能取得独立训练/验证及验证两类代理标签时失败，不虚标样本。
 */
int af_reference_samples_start(AfReferenceSamplesState *,const AfReferenceSamplesConfig *,
    const AfReferenceSamplesBuffers *,void *work,AfGridProgress,void *);
/* 每次1..64个前向调用，MORE让出；最后执行有界排序/分组和描述符发布。
 * 回调可取消，活动时重入返回BUSY；完成后再次step返回STALE。
 */
int af_reference_samples_step(AfReferenceSamplesState *,uint32_t budget);
#endif
