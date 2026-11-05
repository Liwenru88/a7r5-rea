/* 固定来源的中性平场 RAW 前端；不代表机身模型、sRGB 域或照片去马赛克。 */
#ifndef AF_EDIT_FRONT_H
#define AF_EDIT_FRONT_H
#include <stddef.h>
#include <stdint.h>

#define AF_EDIT_FRONT_LIMIT 4096u
enum { AF_EDIT_FRONT_OK = 0, AF_EDIT_FRONT_INVALID = -1,
       AF_EDIT_FRONT_UNSUPPORTED = -2 };

typedef struct {
    uint16_t black[3], scale;
    int16_t wb[3], maximum, threshold[3];
    uint16_t weights[3];
} AfEditFront;

/* 只接受显式 RGGB、等绿相位、as-shot WB、零色温偏移/色调/EV。
 * raw/settings 只读，输出不与其重叠；失败不发布参数，无隐式默认值。 */
int af_edit_front_parse_neutral(const void *raw, size_t raw_bytes,
                               const void *settings, size_t settings_bytes,
                               AfEditFront *output);
/* 每次 1..4096 个 RGB 三元组；输入、参数、输出相互独立。
 * ITP 输入仅 0..16383 RAW 码值，输出为整数 ITP；所有输入先校验再写输出。 */
int af_edit_front_itp(const AfEditFront *, const uint16_t *, size_t pixels,
                      uint16_t *output);
/* SSCS 输入/输出为 uint16 整数域，保留公开公式的有符号32位回绕和算术移位。
 * 这里只接受 0<=threshold<=maximum 的有来源参数范围，不归一化权重。 */
int af_edit_front_sscs(const AfEditFront *, const uint16_t *, size_t pixels,
                       uint16_t *output);
#endif
