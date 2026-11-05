/* 公开Edit受限矩阵参数构造；不是CP像素或sRGB域桥。 */
#ifndef AF_EDIT_MATRIX_TABLE_H
#define AF_EDIT_MATRIX_TABLE_H
#include "af_grid.h"
#define AF_EDIT_MATRIX_PAYLOAD_BYTES 276u
#define AF_EDIT_MATRIX_CONFIG_BYTES 552u
#define AF_EDIT_MATRIX_TABLE_ENTRIES (1024u*18u)
typedef struct {
    uint32_t schema;
    uint8_t calibration_identity, output_gamut_mode, trailing_padding[2];
} AfEditMatrixDomain;
typedef struct { uint8_t config[552];float table[1024u*18u]; } AfEditMatrixWork;

/* schema=1，显式identity校准且外部param9+0x44=3（不加输出色域矩阵）。
 * payload中各标志/阈值保持原解码；外部mode不是config+0x224字段。
 * config最后两字节由调用者提供，原解码器不写，不能猜测为0。
 * 第三对角项与第一项必须相等：公开公式共用第一项，非对称情况尚未核实。
 * 采用公开float64代数插值，再一次量化为float32；context4整表有黄金验证，
 * 不保证任意新参数与原Edit浮点构造器逐位相同，不授予机身应用许可。
 * 工作区与所有输入、两输出分离；失败/取消不发布config或table。 */
int af_edit_matrix_table(const uint8_t payload[276], const AfEditMatrixDomain *,
                          AfEditMatrixWork *, uint8_t config[552],
                          float table[1024u*18u], AfGridProgress, void *context);
#endif
