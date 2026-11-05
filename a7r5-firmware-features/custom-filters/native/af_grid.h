/* 原生网格格式与有界LUT拟合。响应模型仅用于转换/误差预测，不是机身应用许可。 */
#ifndef AF_GRID_H
#define AF_GRID_H
#include "af_cube.h"
#include "af_slots.h"
#define AF_GRID_NODES 405u
#define AF_GRID_BYTES 1215u
#define AF_GRID_SAMPLES 4096u
#define AF_GRID_ITERATIONS 256u
#define AF_GRID_CANCELLED (-20)
typedef struct {
    uint32_t schema,base_mask,smooth;
    float coordinates[12],response[36];
    uint8_t sha256[32];
} AfGridModel;
/* 结构有效只表示显式数学模型可执行，不是产品/固件适用性认证。
 * 固定PT条件的paired-v2原始捕获摘要不能单独承载模型身份，默认拒绝。 */
typedef struct { float rgb[3],weight;uint32_t group; } AfGridSample;
/* group的位0为灰阶、位1为肤色；样本和标签由调用者提供，不推断真实场景肤色。 */
typedef struct {
    uint16_t index[8];
    float weights[8],response[9],base[3],target[3],mass;
} AfGridRow;
typedef struct {
    AfGridRow rows[AF_GRID_SAMPLES];
    float x[AF_GRID_BYTES],y[AF_GRID_BYTES],next[AF_GRID_BYTES];
    float gradient[AF_GRID_BYTES],best[AF_GRID_BYTES],errors[AF_GRID_SAMPLES];
} AfGridWork;
typedef struct {
    uint32_t iterations,converged,limited,zero_selected;
    float zero_mse,quantized_mse;
} AfGridFit;
typedef struct {
    uint32_t samples,clipped,gray_samples,skin_samples;
    /* 明确为显示sRGB/D65、8位量化后的ΔE76；顺序：均值/P95/最大/灰阶均值/肤色均值。 */
    float delta_e76[5],rgb_rmse;
} AfGridReport;
typedef struct {float target[3],predicted[3];uint32_t group;} AfGridColor;
/* 通用颜色误差聚合；errors为n个float的独立暂存区。
 * ΔE76及RGB RMSE均按夹取后8位sRGB计算；无模型或场景身份假设。 */
int af_grid_color_report(const AfGridColor *,size_t,float *errors,AfGridReport *);
typedef int (*AfGridProgress)(void *,uint32_t completed,uint32_t total);
int af_grid_model_valid(const AfGridModel *);
int af_grid_row(const AfGridModel *,const float rgb[3],AfGridRow *);
int af_grid_predict(const AfGridModel *,const int8_t grid[AF_GRID_BYTES],const float rgb[3],float out[3]);
/* permutation[i]是源节点i写入的目标字索引，与原CP顺序表一致。 */
int af_grid_pack(const int8_t *,const uint16_t permutation[AF_GRID_NODES],unsigned level,
                 uint32_t output[AF_GRID_NODES]);
/* 工作区必须与全部输入/输出独立。有限迭代；回调非零取消，失败不发布grid/result。 */
int af_grid_fit(const AfGridModel *,uint32_t base,const AfCube *,const AfGridSample *,size_t,
                unsigned iterations,float smoothness,int8_t *,AfGridWork *,AfGridFit *,AfGridProgress,void *);
/* 只评估调用者另行提供的留出样本；不参与拟合选优。失败不发布report。 */
int af_grid_report(const AfGridModel *,const AfCube *,const int8_t *,const AfGridSample *,size_t,
                   AfGridWork *,AfGridReport *);
#endif
