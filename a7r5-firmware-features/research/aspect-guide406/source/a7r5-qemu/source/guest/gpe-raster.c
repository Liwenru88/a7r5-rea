/* shortcut: uniform overwrite fills only; extend after captured colour/blend layouts are verified. */
typedef unsigned long size_t;
#include "gpe-copy.h"
/* shortcut: only the verified same-format CME copy; conversion/blending need channel semantics. */
int gpe_plan_copy(const unsigned int *p, struct gpe_copy_plan *out) {
    if (!p || !out) return 5;
    const unsigned char *raw = (const unsigned char *)p;
    /* Equal-size CME copies with all transform flags clear do not read the scale fields. */
    if (p[13] > 1 || p[23] != p[13] || raw[0x70] || raw[0x72] != 255 ||
        p[26] || p[29] || (p[30] & 0xffff))
        return 5;
    unsigned int width = p[18], height = p[19], dst_stride = p[12], src_stride = p[22];
    if (!width || !height || width > 8192 || height > 8192 || p[4] != width || p[5] != height ||
        !dst_stride || !src_stride || dst_stride > 16384 || src_stride > 16384) return 5;
    long long dx = (long long)(int)p[2] + (int)p[10] - (int)p[20];
    long long dy = (long long)(int)p[3] + (int)p[11] - (int)p[21];
    int sx = (int)p[16], sy = (int)p[17];
    if (dx < 0 || dy < 0 || sx < 0 || sy < 0 || dx > 16383 || dy > 16383 || sx > 16383 || sy > 16383 ||
        dx + width > dst_stride || (unsigned long)sx + width > src_stride) return 5;
    unsigned int bpp = p[13] ? 4 : 2;
    struct gpe_copy_plan plan = {0};
    plan.destination = (unsigned long long)p[0] | ((unsigned long long)p[1] << 32);
    plan.source = (unsigned long long)p[14] | ((unsigned long long)p[15] << 32);
    plan.destination_pitch = (unsigned long)dst_stride * bpp;
    plan.source_pitch = (unsigned long)src_stride * bpp;
    plan.destination_offset = ((unsigned long)dy * dst_stride + (unsigned long)dx) * bpp;
    plan.source_offset = ((unsigned long)sy * src_stride + (unsigned int)sx) * bpp;
    plan.line = (unsigned long)width * bpp;
    plan.rows = height;
    plan.destination_span = plan.destination_offset + (height - 1UL) * plan.destination_pitch + plan.line;
    plan.source_span = plan.source_offset + (height - 1UL) * plan.source_pitch + plan.line;
    if (plan.destination < 0x410000000ULL || plan.destination >= 0x500000000ULL ||
        plan.source < 0x410000000ULL || plan.source >= 0x500000000ULL ||
        plan.destination_span > 0x4000000 || plan.source_span > 0x4000000 ||
        plan.destination_span > 0x500000000ULL - plan.destination ||
        plan.source_span > 0x500000000ULL - plan.source) return 5;
    unsigned long long dst_start = plan.destination + plan.destination_offset;
    unsigned long long src_start = plan.source + plan.source_offset;
    if (dst_start < plan.source + plan.source_span && src_start < plan.destination + plan.destination_span &&
        !(dst_start == src_start && plan.destination_pitch == plan.source_pitch)) return 5;
    *out = plan;
    return 0;
}
int gpe_copy_rows(unsigned char *destination, unsigned long dst_capacity, const unsigned char *source,
                  unsigned long src_capacity, const struct gpe_copy_plan *plan) {
    if (!destination || !source || !plan || dst_capacity < plan->destination_span || src_capacity < plan->source_span)
        return 5;
    for (unsigned int row = 0; row < plan->rows; ++row)
        for (unsigned long byte = 0; byte < plan->line; ++byte)
            destination[plan->destination_offset + row * plan->destination_pitch + byte] =
                source[plan->source_offset + row * plan->source_pitch + byte];
    return 0;
}
int gpe_uniform_fill(unsigned char *memory, size_t capacity, const unsigned int *p) {
    if (!memory || !p) return 5;
    unsigned int x = p[2], y = p[3], width = p[4], height = p[5], stride = p[6], format = p[7];
    const unsigned char *colour = (const unsigned char *)(p + 8), *blend = (const unsigned char *)(p + 9);
    if (format > 1 || blend[0] || blend[1] != 255 || !width || !height || !stride ||
        x > 16383 || y > 16383 || width > 8192 || height > 8192 || stride > 16384 ||
        x > stride || width > stride - x) return 5;
    if (colour[0] != colour[1] || colour[0] != colour[2] || colour[0] != colour[3]) return 5;
    unsigned int bpp = format ? 4 : 2;
    size_t last = ((size_t)(y + height - 1) * stride + x + width) * bpp;
    if (last > capacity) return 5;
    unsigned char value = format ? colour[0] : (unsigned char)((colour[0] & 240) | (colour[0] >> 4));
    for (unsigned int row = 0; row < height; ++row)
        for (size_t i = 0; i < (size_t)width * bpp; ++i) memory[((size_t)(y + row) * stride + x) * bpp + i] = value;
    return 0;
}
#ifdef GPE_RASTER_SELFTEST
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    unsigned char buffer[64]; memset(buffer, 0x5a, sizeof buffer);
    unsigned int p[14] = {0,0,1,1,2,2,4,0,0,0x1ff00};
    assert(!gpe_uniform_fill(buffer, sizeof buffer, p));
    assert(buffer[0] == 0x5a && buffer[10] == 0 && buffer[13] == 0 && buffer[14] == 0x5a);
    assert(buffer[18] == 0 && buffer[21] == 0 && buffer[22] == 0x5a);
    p[7] = 1; p[8] = 0xffffffffU;
    assert(!gpe_uniform_fill(buffer, sizeof buffer, p) && buffer[20] == 255);
    p[8] = 0xff010203U;
    assert(gpe_uniform_fill(buffer, sizeof buffer, p) == 5);
    p[8] = 0; p[4] = 5;
    assert(gpe_uniform_fill(buffer, sizeof buffer, p) == 5);
    p[4] = 2;
    assert(gpe_uniform_fill(buffer, 10, p) == 5);
    puts("GPE_RASTER_SELFTEST_PASS");
}
#endif
