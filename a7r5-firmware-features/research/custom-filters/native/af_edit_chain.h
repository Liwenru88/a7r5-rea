/* 公开Edit整数颜色子链；不是RAW解码、显示sRGB桥或本机ISP适配。 */
#ifndef AF_EDIT_CHAIN_H
#define AF_EDIT_CHAIN_H
#include "af_edit_reference.h"

typedef struct {
    AfEditRefMatrix matrix;
    const uint16_t *main_gamma, *y_gamma;
    size_t main_entries, y_entries;
    int16_t cc1[8], luma[3];
    uint16_t keep_unclipped;
    AfEditRefArea area;
    AfEditRefChroma chroma;
    AfEditRefYGamma levels;
} AfEditRefChain;

typedef struct {
    uint16_t a[AF_EDIT_REF_MAX_PIXELS*3], b[AF_EDIT_REF_MAX_PIXELS*3];
} AfEditRefChainWork;

/* 显式完整上下文与独立工作区，任何阶段失败都不发布output。
 * 依次执行矩阵、Gamma、CC1、AreaComp、色度抑制、YGamma及RGB转换。
 * 不包含原链中间的锐化、降噪等空间阶段，也不假定残差网格的位置。
 * 输入为Edit后SSCS/矩阵前整数RGB；输出仍为参考颜色子链整数域。
 * 上下文及借用表在调用期间由同一拥有者保持不变，不授予机身应用能力。 */
int af_edit_ref_color(const AfEditRefChain *, const uint16_t *rgb,
                      size_t width, size_t height, AfEditRefChainWork *, uint16_t *output);
#endif
