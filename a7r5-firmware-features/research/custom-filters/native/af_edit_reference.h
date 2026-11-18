/* 公开Edit捕获的整数域研究算子；不代表4.06 ISP或sRGB/JPG链路。 */
#ifndef AF_EDIT_REFERENCE_H
#define AF_EDIT_REFERENCE_H
#include "af_slots.h"

#define AF_EDIT_REF_MAIN_ENTRIES 65536u
#define AF_EDIT_REF_Y_ENTRIES 32768u
#define AF_EDIT_REF_MAX_PIXELS 4096u

typedef struct {
    int16_t black_level, white_level, pivot;
    float gain;
} AfEditRefYGamma;
typedef struct {
    const float *table, *angles;
    size_t table_entries, angle_entries;
    uint16_t enabled, luma_smooth, chroma_smooth, scale_chroma, quadratic;
    float thresholds[3];
} AfEditRefMatrix;
typedef struct { float coefficients[16]; uint8_t selector; } AfEditRefArea;
typedef struct { int32_t high_cutoff, low_cutoff, high_slope, low_slope; } AfEditRefChroma;
/* 三个端点已经按外观选择规则解析；此接口不猜测外观编号。 */
typedef struct {
    int16_t slopes[3], thresholds[3], low_slope, low_threshold, gain_raw;
    int32_t exposure_300;
} AfEditRefChromaSource;
typedef struct {
    const int16_t *inverse_secondary, *inverse_main, *main_gamma, *secondary_gamma;
    size_t inverse_secondary_entries, inverse_main_entries,
           main_entries, secondary_entries;
} AfEditRefChromaTables;

/* 交错RGB/YCC三元组；输出不可与输入、参数或表重叠。
 * 每次1..4096像素，所有检查成功后才发布输出；不提供机身应用入口。
 * 调用期间由单一拥有者保持输入和参数稳定，禁止fast-math构建。 */
int af_edit_ref_main_gamma(const uint16_t *table, size_t entries,
                          const uint16_t *rgb, size_t pixels, uint16_t *output);
/* RGB为MainGamma后的signed16；CC1为已选择的8个原始半字。
 * 色度有符号位域与增益分别解码，不能再叠加一次CC1色度算子。
 * keep_unclipped为原色度限幅开关，须显式传0或1。 */
int af_edit_ref_rgb_ycc(const int16_t *rgb, size_t pixels,
                       const int16_t coefficients[8], const int16_t luma[3],
                       unsigned keep_unclipped, uint16_t *output);
int af_edit_ref_y_gamma(const uint16_t *table, size_t entries,
                       const AfEditRefYGamma *parameters,
                       const uint16_t *ycc, size_t pixels, uint16_t *output);
int af_edit_ref_ycc_rgb(const uint16_t *ycc, size_t pixels, uint16_t *output);
/* 完整输入行的水平五抽头；采样窗验证只覆盖有两侧邻点的内部列。 */
int af_edit_ref_matrix16(const AfEditRefMatrix *, const uint16_t *rgb,
                         size_t width, size_t height, uint16_t *output);
int af_edit_ref_area(const AfEditRefArea *, const uint16_t *ycc,
                     size_t pixels, uint16_t *output);
int af_edit_ref_chroma_controls(const AfEditRefChromaSource *,
                                const AfEditRefChromaTables *, AfEditRefChroma *);
int af_edit_ref_chroma(const AfEditRefChroma *, const uint16_t *ycc,
                       size_t pixels, uint16_t *output);
#endif
