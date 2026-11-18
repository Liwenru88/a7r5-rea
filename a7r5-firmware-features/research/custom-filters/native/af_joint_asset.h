/* 完整联合配方的离线小端格式；不是机身已经批准的ISP schema。 */
#ifndef AF_JOINT_ASSET_H
#define AF_JOINT_ASSET_H
#include "af_joint.h"
#define AF_JOINT_ASSET_HEADER 128u
#define AF_JOINT_ASSET_BODY 1815u
#define AF_JOINT_ASSET_BYTES (AF_JOINT_ASSET_HEADER+AF_JOINT_ASSET_BODY)
#define AF_JOINT_SECTOR_BODY 2355u
#define AF_JOINT_SECTOR_BYTES (AF_JOINT_ASSET_HEADER+AF_JOINT_SECTOR_BODY)
#ifdef AF_JOINT_ASSET_LEGACY_ONLY406
#define AF_JOINT_SECTOR_SUPPORTED 0u
#define AF_JOINT_ASSET_MAX_BYTES AF_JOINT_ASSET_BYTES
#else
#define AF_JOINT_SECTOR_SUPPORTED 1u
#define AF_JOINT_ASSET_MAX_BYTES AF_JOINT_SECTOR_BYTES
#endif
#define AF_JOINT_ASSET_SCHEMA 0x314a4641u
#define AF_JOINT_ASSET_UNSUPPORTED (-30)
/* 原BW/SE只消费9项矩阵且不混合三端点。唯有三份六项完全相同，才有
 * 无歧义的单矩阵增量；此处不替调用者验证其余格式、范围或来源。 */
static inline int af_joint_matrix_native406_bytes_representable(uint32_t base,uint32_t mode,
    const void *coefficients,size_t bytes){
    if(mode>1)return AF_JOINT_ASSET_UNSUPPORTED;
    if(base!=8&&base!=9)return AF_OK;
    unsigned count=mode?192u:12u;const uint8_t *p=coefficients;
    if(!p||bytes!=3u*count)return AF_INVALID;
    for(unsigned i=0;i<count;++i)
        if(p[i]!=p[i+count]||p[i]!=p[i+2u*count])return AF_JOINT_ASSET_UNSUPPORTED;
    return AF_OK;
}
static inline int af_joint_matrix_native406_representable(uint32_t base,uint32_t mode,
    const int16_t *matrix,const int16_t *sectors){
    return af_joint_matrix_native406_bytes_representable(base,mode,
        mode?(const void *)sectors:(const void *)matrix,mode?576u:36u);
}
typedef struct {
    uint32_t base;
    uint8_t model_sha256[32];
    AfJointRecipe recipe;
    uint32_t native_mode;
    int16_t native_tone[3];
    uint32_t native_seed[129];
#ifndef AF_JOINT_ASSET_LEGACY_ONLY406
    /* 内部布局扩展；旧配方必须mode0且sector全零。mode1按端点/色相区/六项排列。 */
    uint32_t matrix_mode;
    int16_t sector_matrix[3u*16u*6u];
#endif
} AfJointAsset;
/* 大缓冲由接收拥有者驻留分配，避免在原消息线程栈上展开完整候选。 */
typedef struct {
    uint8_t checked[AF_JOINT_ASSET_MAX_BYTES];
    AfJointAsset candidate;
    uint32_t gamma_scratch[129];
} AfJointAssetDecodeWork;
/* flags=3：最终Gamma曲线、仅研究；禁止作为旧tone增量再次处理。
 * 不编码C结构填充。CP固定到当前4.06，SHA覆盖摘要区清零的整份载荷，
 * 用于检测头/正文损坏，不提供认证。
 * 所有对象须独立，失败不发布；decode仅验证载荷，不能授予成像应用许可。 */
int af_joint_asset_encode(const AfJointAsset *,void *,size_t,size_t *);
int af_joint_asset_decode(const void *,size_t,AfJointAsset *);
/* work、原字节和output必须独立；失败不发布output，work可被覆盖。
 * 旧decode保留相同行为；消息接入应使用此接口并核实驻留空间寿命。 */
int af_joint_asset_decode_work(const void *,size_t,AfJointAssetDecodeWork *,AfJointAsset *);
/* 只识别家族合法长度；完整身份、范围和摘要仍须decode。 */
static inline int af_joint_asset_size_valid(size_t n){return n==AF_JOINT_ASSET_BYTES||(AF_JOINT_SECTOR_SUPPORTED&&n==AF_JOINT_SECTOR_BYTES);}
static inline size_t af_joint_asset_size(const AfJointAsset *a){
#ifdef AF_JOINT_ASSET_LEGACY_ONLY406
    (void)a;return AF_JOINT_ASSET_BYTES;
#else
    return a&&a->matrix_mode==1?AF_JOINT_SECTOR_BYTES:AF_JOINT_ASSET_BYTES;
#endif
}
static inline unsigned af_joint_asset_converter(const AfJointAsset *a){
#ifdef AF_JOINT_ASSET_LEGACY_ONLY406
    (void)a;return 1u;
#else
    return a->matrix_mode?3u:a->native_mode?2u:1u;
#endif
}
#endif
