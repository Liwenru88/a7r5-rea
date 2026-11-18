/* 固定公开context4数值资产的描述符装配；无I/O/分配，不授予机身标定。 */
#ifndef AF_REFERENCE_ASSETS_H
#define AF_REFERENCE_ASSETS_H
#include "af_edit_joint.h"
#define AF_REFERENCE_ASSETS_BYTES 377304u
typedef struct {
    uint32_t valid;
    const uint8_t *raw;
    AfEditRefChain baseline;
    AfEditMatrixDomain matrix_domain;
    AfEditRefChromaSource chroma_source;
    AfEditContextInput context;
    AfEditJointInput joint;
} AfReferenceAssets;
extern const uint8_t af_reference_assets_sha256[32];
size_t af_reference_assets_owner_bytes(void);
/* 严格核377304B长度、固定SHA、至少4字节对齐及所有输出独立性后一次发布。
 * raw始终借用，必须保持只读及驻留至模型/导入任务结束。
 * 成功后joint.edit/context.baseline等指向owner自身，不能移动或裸复制owner。
 * 所有原生输入均来自固定公开数值和显式标量，未读取当前AP/CP运行表。
 * 调用者另分配AfEditJointWork/cache并沿原af_edit_joint_prepare完成实际构表。
 */
int af_reference_assets_bind(const void *raw,size_t bytes,AfReferenceAssets *owner);
/* 仅从已绑定原576字节记录生成初始联合配方；其他组件增量和网格清零。
 * 输出独立且失败不发布，不将seed生成认作设备成像许可。
 */
int af_reference_assets_seed(const AfReferenceAssets *,AfJointRecipe *);
#endif
