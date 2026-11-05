/* 有界三维CUBE源读取。调用者提供候选工作区；禁止复用正在成像的缓冲。 */
#ifndef AF_CUBE_H
#define AF_CUBE_H

#include <stddef.h>
#include <stdint.h>

enum AfCubeResult {
    AF_CUBE_OK = 0, AF_CUBE_INVALID = -1, AF_CUBE_BUDGET = -2,
    AF_CUBE_CAPACITY = -3, AF_CUBE_ROWS = -4
};

typedef struct {
    uint32_t dimension;
    float domain_min[3], domain_max[3];
    const float *values;
} AfCube;

typedef struct {
    uint32_t max_dimension;
    size_t max_bytes;
} AfCubeLimits;

/* 只在全部成功时发布output。storage为暂存区，失败时可包含部分样本。 */
int af_cube_parse(const char *source, size_t bytes, AfCube *output,
                  float *storage, size_t capacity_floats, AfCubeLimits limits);
/* 按DOMAIN归一化并夹取输入，红轴最快；不剪裁LUT输出、不执行ISP拟合。 */
int af_cube_eval(const AfCube *cube, const float rgb[3], float output[3]);

#endif
