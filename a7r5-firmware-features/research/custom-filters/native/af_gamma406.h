/* 当前4.06原生Gamma采样域；不推断RGB域桥或硬件插值舍入。 */
#ifndef AF_GAMMA406_H
#define AF_GAMMA406_H
#include "af_slots.h"
#define AF_GAMMA406_POINTS 129u
#define AF_GAMMA406_RECORD 576u
typedef struct { uint32_t left,right,offset,width; } AfGamma406Span;
/* 依据记录+0x204的12个指数生成原横轴；无效/不足/多余细分拒绝，不发布。 */
int af_gamma406_axis(const void *record,uint32_t output[129]);
/* 仅给出原整数码域区间和分子/分母，不执行或假设硬件插值。 */
int af_gamma406_locate(const uint32_t axis[129],uint32_t code,AfGamma406Span *);
/* 从完整候选替换129点及+0x220末点，保持原轴/标志/其他附属字节。 */
int af_gamma406_replace(const void *record,const uint32_t curve[129],void *output);
#endif
