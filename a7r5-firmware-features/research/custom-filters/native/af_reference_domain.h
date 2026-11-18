/* 固定上游预览sRGB解释下的参考域表生成；不是相机色彩标定。 */
#ifndef AF_REFERENCE_DOMAIN_H
#define AF_REFERENCE_DOMAIN_H
#include "af_reference_joint.h"

#define AF_REFERENCE_DOMAIN_POLICY 1u
#define AF_REFERENCE_DOMAIN_MAX_EVALUATIONS 4096u
extern const uint8_t af_reference_domain_policy_sha256[32];

typedef struct {
    uint32_t schema,policy,base,dimension,evaluations_per_node;
    /* 来源矩阵任务接受uint16输入，范围由调用者显式限定，不猜测RAW白位。 */
    uint16_t native_minimum[3],native_maximum[3];
    float unreachable_tolerance;
    uint8_t context_sha256[32];
    const AfEditJointCache *baseline;
} AfReferenceDomainConfig;

typedef struct {
    uint32_t nodes,evaluations,unreachable,research_only,camera_apply_allowed;
    float mean_max_abs_rgb,max_abs_rgb,unreachable_tolerance;
    uint16_t native_minimum[3],native_maximum[3];
    uint8_t context_sha256[32],policy_sha256[32],source_sha256[32];
} AfReferenceDomainReport;

typedef struct {
    float *input_values,*output_values;
    size_t input_capacity,output_capacity;
    AfReferenceMap *input_map,*output_map;
    AfReferenceDomainReport *report;
} AfReferenceDomainBuffers;

typedef struct AfReferenceDomainState AfReferenceDomainState;
size_t af_reference_domain_state_bytes(void);
size_t af_reference_domain_work_bytes(void);
/* state首次清零，状态、工作区、源和全部输出相互独立且在任务期间固定。
 * input_values容量为dimension^3*3，output_values为24个float。
 * 先计算125个原生粗网格样本，再逐节点有界反解代表输入，最终整体发布。
 * 输出域采用明确上游约定q/16383，输入代表解不要求全局可逆；unreachable
 * 只统计本预算内未达容差的颜色，不能证明全局不可达。values是候选暂存，
 * 取消可部分改写；map/report输出只在OK发布。
 * 不执行上游代码、设备服务、照片解码或硬件模拟。 */
int af_reference_domain_start(AfReferenceDomainState *,const AfReferenceDomainConfig *,
                             const AfReferenceDomainBuffers *,void *work,AfGridProgress,void *);
/* 每次预算1..64个有界工作单元，MORE让出；回调中重入返回BUSY。
 * 到达候选预算保留本节点最优代表解，报告残差，不冒充达到精度阈值。 */
int af_reference_domain_step(AfReferenceDomainState *,uint32_t budget);
#endif
