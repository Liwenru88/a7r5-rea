/* 校验后交给原组件的驻留深副本；不是文件、消息或持久化格式。 */
#ifndef AF_CP_RUNTIME_ASSET406_H
#define AF_CP_RUNTIME_ASSET406_H
#include "af_joint_asset.h"

typedef struct {
    int16_t matrix[18],cc1[24];
    int8_t grid[AF_GRID_BYTES];
} AfCpRuntimeRecipe406;
typedef struct {
    uint32_t base;
    uint8_t model_sha256[32];
    AfCpRuntimeRecipe406 recipe;
    uint32_t native_mode;
    int16_t native_tone[3];
    /* 旧18项与新版独立扇区显式区分，不改变旧配方的意义。 */
    uint32_t matrix_mode;
    int16_t sector_matrix[288];
} AfCpRuntimeAsset406;

/* 仅在完整格式、seed/tone与参数范围校验成功后调用，输入/输出须独立。
 * 原组件只消费tone，不读取拟合Gamma或seed；去掉这两份冗余曲线。
 * 逐字节清零包含填充，避免freestanding构建引入隐式memclr依赖。 */
static inline void af_cp_runtime_asset406_copy_validated(AfCpRuntimeAsset406 *out,
                                                        const AfJointAsset *in){
    for(size_t i=0;i<sizeof(*out);++i)((volatile uint8_t *)out)[i]=0;
    out->base=in->base;out->native_mode=in->native_mode;
    for(unsigned i=0;i<32;++i)out->model_sha256[i]=in->model_sha256[i];
    for(unsigned i=0;i<3;++i)out->native_tone[i]=in->native_tone[i];
    for(unsigned i=0;i<18;++i)out->recipe.matrix[i]=in->recipe.matrix[i];
    for(unsigned i=0;i<24;++i)out->recipe.cc1[i]=in->recipe.cc1[i];
    for(unsigned i=0;i<AF_GRID_BYTES;++i)out->recipe.grid[i]=in->recipe.grid[i];
    out->matrix_mode=in->matrix_mode;
    for(unsigned i=0;i<288;++i)out->sector_matrix[i]=in->sector_matrix[i];
}
static inline int af_cp_runtime_asset406_matrix(const AfCpRuntimeAsset406 *a,uint32_t sector,int16_t out[27]){
    if(!a||sector>=16||a->matrix_mode>1)return AF_INVALID;
    if(!a->matrix_mode)return af_joint_expand_matrix(a->recipe.matrix,out);
    int16_t selected[18];
    for(unsigned e=0;e<3;++e)for(unsigned j=0;j<6;++j)selected[6*e+j]=a->sector_matrix[(16*e+sector)*6+j];
    return af_joint_expand_matrix(selected,out);
}
#endif
