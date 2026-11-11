#ifndef R5_ASPECT_GEOMETRY_H
#define R5_ASPECT_GEOMETRY_H

#include <stdint.h>

enum {
    R5_ASPECT_NATIVE_COUNT = 4,
    R5_ASPECT_COUNT = 10,
    R5_ASPECT_WIRE_FIRST = 0xe0
};

typedef struct {
    uint16_t numerator;
    uint16_t denominator;
} R5AspectRatio;

typedef struct {
    uint16_t x, y, width, height;
} R5AspectRect;

typedef struct {
    uint16_t canvas_width, canvas_height;
    uint16_t width, height, x, y;
} R5AspectGeometry;

extern const R5AspectRatio r5_aspect_ratios[R5_ASPECT_COUNT];

int r5_aspect_fit(uint16_t p, uint16_t q, const R5AspectRect *view, R5AspectRect *result);

/* 取景有效矩形由调用方提供。纵向取景时对调目标宽高比。 */
int r5_aspect_viewport(uint32_t id, const R5AspectRect *view, int portrait,
                       R5AspectRect *result);

/* 输入输出可重叠，失败不改输出。按参考编码布局的对齐条件计算请求副本。 */
int r5_aspect_crop(uint32_t id, const R5AspectGeometry *source, int auxiliary,
                   uint32_t physical_base_low, R5AspectGeometry *result);

#endif
