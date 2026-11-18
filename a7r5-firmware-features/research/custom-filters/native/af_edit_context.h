/* 显式Edit候选参数的独立构造事务；不绑定CP、sRGB或网格位置。 */
#ifndef AF_EDIT_CONTEXT_H
#define AF_EDIT_CONTEXT_H
#include "af_edit_chain.h"
#include "af_edit_gamma_table.h"
#include "af_edit_matrix_table.h"
#define AF_EDIT_CONTEXT_PROGRESS_TOTAL 148481u
#define AF_EDIT_CONTEXT_OUTPUT_BUDGET (512u*1024u)
#define AF_EDIT_CONTEXT_WORK_BUDGET (768u*1024u)

typedef struct {
    const AfEditRefChain *baseline;
    const uint32_t *axis, *gamma_y;
    const int32_t *contrast;
    const uint8_t *matrix_payload;
    const int16_t *cc1;
    const AfEditMatrixDomain *matrix_domain;
    const AfEditRefChromaSource *chroma_source;
    const int16_t *secondary_inverse, *secondary_gamma;
    size_t secondary_inverse_entries, secondary_entries;
    uint16_t main_inverse_initial_zero;
} AfEditContextInput;

typedef struct {
    AfEditRefChain chain;
    AfEditRefChromaSource chroma_source;
    uint8_t matrix_config[552];
    float matrix_table[18432], angles[512];
    uint16_t main_gamma[65536];
    int16_t main_inverse[65536], secondary_gamma[65536], secondary_inverse[16384];
} AfEditContext;
typedef struct {
    AfEditContext candidate;
    AfEditGammaWork gamma;
    AfEditMatrixWork matrix;
} AfEditContextWork;

/* 只接受显式Edit格式：128轴/Y、1025contrast、276B矩阵、8个已选择CC1。
 * 基线提供角度/luma/Area/YGamma等；YGamma须匹配secondaryGamma的正半表，
 * secondary inverse重建后须与提供的旧表一致，拒绝混合不同上下文。
 * Gamma→main inverse→matrix→secondary核对→新chroma cutoff，最后一次发布。
 * output四个链表指针均指向自身成员，不借work/输入；output使用期间地址固定，
 * 禁止直接移动/按字节复制结构当作另一可用上下文，也不是持久化记录格式。
 * work、output与所有源缓冲相互独立；单一拥有者保持输入稳定。
 * 失败/取消不改变output，work允许部分更新；不提供任何机身应用许可。 */
int af_edit_context_build(const AfEditContextInput *, AfEditContextWork *, AfEditContext *,
                          AfGridProgress, void *context);
#endif
