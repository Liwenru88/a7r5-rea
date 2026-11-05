/* 固定参考ST端点到Edit整数颜色子链；不注册AfJointModel或声明sRGB/grid支持。 */
#ifndef AF_EDIT_JOINT_H
#define AF_EDIT_JOINT_H
#include "af_edit_context.h"
#include "af_edit_cp_gamma.h"
#define AF_EDIT_JOINT_PROGRESS_TOTAL 148482u

typedef struct {
    const AfEditContextInput *edit;
    const void *cp_gamma_record;
    const uint16_t *matrix_raw, *cc1_raw;
    uint16_t matrix_weights[4], cc1_weights[4];
} AfEditJointInput;
typedef struct {
    AfEditCpGamma gamma;
    uint8_t matrix_payload[276];
    int16_t cc1[8];
    uint32_t matrix_quantized;
} AfEditJointParameters;
typedef struct {
    uint32_t valid, builds, hits;
    uint8_t recipe_sha256[32], source_sha256[32];
    AfEditContext context;
} AfEditJointCache;
typedef struct {
    AfEditContextWork build;
    AfEditJointParameters parameters;
} AfEditJointWork;
typedef struct {
    AfEditRefChainWork pixels;
    uint16_t patch[15], rendered[15];
} AfEditJointEvalWork;

/* 显式固定公开ST的3×16×6矩阵、第一绝对端点加两差分的24项CC1，
 * 以及公开context4矩阵模板均核对摘要；权重是显式本包Q8消费参数。
 * Gamma复用固定ST/col6桥。先原端点构造，再加候选三端点增量，最后原两级混合。
 * 矩阵保留模板低2位，打包有符号14位六项；matrix_quantized统计特殊负偶数的
 * +1量化单位差异，不声称CP浮点系数逐位等价。非零grid明确SKIP。
 * 原九项混合因独立舍入而不再保持1024行和时，六项表示不支持，明确SKIP。
 * 输入/输出独立，失败不发布；这是研究参数适配，不提供机身应用许可。 */
int af_edit_joint_parameters(const AfEditJointInput *,const AfJointRecipe *,AfEditJointParameters *);
/* AJR3研究适配：sector_matrix按(端点*16+色相区)*6排列，范围仍为增量±1024。
 * recipe.matrix须全零；与旧18项不叠加。其余原构造、整数舍入和SKIP条件保持。
 * 数组必须非空且与输出独立；全零扇区的数值输出与旧零矩阵逐点相同。 */
int af_edit_joint_parameters_sector(const AfEditJointInput *,const AfJointRecipe *,
                                    const int16_t sector_matrix[288],AfEditJointParameters *);
/* init仅清理缓存头；未准备的缓存不能评估。context地址在使用期间固定，不可裸移动。 */
int af_edit_joint_init(AfEditJointCache *);
/* 按规范化配方字段及完整借用源内容指纹缓存，每个候选只构造一次。
 * 同配方/来源命中不重建；源改变会失效，非零grid不被忽略。
 * work/cache与所有输入独立。失败/取消保持缓存及计数；单一拥有者串行调用。
 * 输入只在prepare期间借用；成功缓存持有自含表，eval不再读取输入或配方。
 * 此处无AfJointPredict回调，不把Edit整数样本当成归一化sRGB。 */
int af_edit_joint_prepare(const AfEditJointInput *,const AfJointRecipe *,AfEditJointWork *,
                          AfEditJointCache *,AfGridProgress,void *);
/* 独立域标签及完整288项参与候选hash；旧API/hash不变，模式切换不会错命中。 */
int af_edit_joint_prepare_sector(const AfEditJointInput *,const AfJointRecipe *,
    const int16_t sector_matrix[288],AfEditJointWork *,AfEditJointCache *,AfGridProgress,void *);
/* 明确5列常色邻域，保留原平滑标志并取中心像素；非真实照片空间响应。
 * 输入/输出均为Edit整数RGB三元组，无归一化、CUBE或ΔE解释。 */
int af_edit_joint_eval(const AfEditJointCache *,const uint16_t rgb[3],
                       AfEditJointEvalWork *,uint16_t output[3]);
#endif
