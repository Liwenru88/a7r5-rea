/* Explicit software model: straight RGBA4444, source-over, nearest stretch and verified power-of-two tile.
   Hardware rounding, premultiplication and the full GPE format mapping remain unverified. */
#include "gpe-sprite.h"

static int span_ok(unsigned long long address, unsigned long bytes) {
    return bytes && bytes <= 0x4000000 && address >= 0x410000000ULL && address <= 0x500000000ULL - bytes;
}
static unsigned short pack(unsigned int r, unsigned int g, unsigned int b, unsigned int a) {
    return (unsigned short)((r & 240) << 8 | (g & 240) << 4 | (b & 240) | a >> 4);
}
static unsigned short blend(unsigned short dst, unsigned int r, unsigned int g, unsigned int b, unsigned int a) {
    if (!a) return dst;
    if (a == 255) return pack(r, g, b, a);
    unsigned int da = (dst & 15) * 17;
    unsigned int denominator = a * 255 + da * (255 - a);
    unsigned int dr = (dst >> 12) * 17, dg = (dst >> 8 & 15) * 17, db = (dst >> 4 & 15) * 17;
    r = (r * a * 255 + dr * da * (255 - a) + denominator / 2) / denominator;
    g = (g * a * 255 + dg * da * (255 - a) + denominator / 2) / denominator;
    b = (b * a * 255 + db * da * (255 - a) + denominator / 2) / denominator;
    return pack(r, g, b, (denominator + 127) / 255);
}
static unsigned short get16(const unsigned char *p) { return (unsigned short)(p[0] | p[1] << 8); }
static void put16(unsigned char *p, unsigned short value) { p[0] = value; p[1] = value >> 8; }

int gpe_plan_sprite(const unsigned int *p, struct gpe_sprite_plan *out) {
    if (!p || !out) return 5;
    const unsigned char *raw = (const unsigned char *)p;
    if (p[13] != 0 || (p[23] != 0 && p[23] != 2) || raw[0x70] > 1 ||
        raw[0x74] > 1 || raw[0x75] > 1 || raw[0x77] || (p[30] & 0xffff) || p[26] ||
        p[10] || p[11] || p[20] || p[21] ||
        (p[23] == 0 && raw[0x76]) ||
        (p[23] == 2 && (raw[0x76] != 14 || raw[0x6f] != 255 || raw[0x70] != 1)) ||
        (!raw[0x70] && raw[0x72] != 255)) return 5;
    unsigned int w = p[4], h = p[5], sw = p[18], sh = p[19], ds = p[12], ss = p[22];
    int dx = (int)p[2], dy = (int)p[3], sx = (int)p[16], sy = (int)p[17];
    int cx = (int)p[6], cy = (int)p[7];
    if (!w || !h || !sw || !sh || w > 8192 || h > 8192 || sw > 8192 || sh > 8192 ||
        !ds || !ss || ds > 16384 || ss > 16384 || sx < 0 || sy < 0 || sx > 16383 || sy > 16383 ||
        (unsigned int)sx + sw > ss || dx < -16384 || dx > 16383 || dy < -16384 || dy > 16383 ||
        cx < 0 || cy < 0 || cx > 16383 || cy > 16383 || !p[8] || !p[9] || p[8] > 8192 || p[9] > 8192 ||
        (unsigned int)cx + p[8] > ds) return 5;
    if (raw[0x75] && (p[24] != 0x3f800000 || p[25] != 0x3f800000 ||
        (w != sw && ((sw - 1) & sw)) || (h != sh && ((sh - 1) & sh)))) return 5;
    struct gpe_sprite_plan s = {0};
    s.memory.destination = (unsigned long long)p[0] | (unsigned long long)p[1] << 32;
    s.memory.source = (unsigned long long)p[14] | (unsigned long long)p[15] << 32;
    s.memory.destination_pitch = ds * 2UL;
    unsigned int sbpp = p[23] == 2 ? 1 : 2;
    s.memory.source_pitch = ss * (unsigned long)sbpp;
    s.memory.source_offset = ((unsigned long)sy * ss + (unsigned int)sx) * sbpp;
    s.memory.source_span = s.memory.source_offset + (sh - 1UL) * s.memory.source_pitch + sw * sbpp;
    if (!span_ok(s.memory.source, s.memory.source_span) || !span_ok(s.memory.destination, 1)) return 5;
    int left = dx > cx ? dx : cx, top = dy > cy ? dy : cy;
    int right = dx + (int)w < cx + (int)p[8] ? dx + (int)w : cx + (int)p[8];
    int bottom = dy + (int)h < cy + (int)p[9] ? dy + (int)h : cy + (int)p[9];
    s.dx = dx; s.dy = dy; s.width = w; s.height = h; s.source_width = sw; s.source_height = sh;
    s.source_format = p[23]; s.mode = raw[0x70]; s.alpha = raw[0x72]; s.tint = p[27]; s.tile = raw[0x75];
    if (right > left && bottom > top) {
        s.left = left; s.top = top; s.right = right; s.bottom = bottom;
        s.memory.rows = bottom - top;
        s.memory.line = (right - left) * 2UL;
        s.memory.destination_span = (bottom - 1UL) * s.memory.destination_pitch + right * 2UL;
        if (!span_ok(s.memory.destination, s.memory.destination_span)) return 5;
        if (s.memory.destination < s.memory.source + s.memory.source_span &&
            s.memory.source < s.memory.destination + s.memory.destination_span) return 5;
    }
    *out = s;
    return 0;
}

int gpe_draw_sprite(unsigned char *dst, unsigned long dc, const unsigned char *src, unsigned long sc,
                    const struct gpe_sprite_plan *s) {
    if (!dst || !src || !s || dc < s->memory.destination_span || sc < s->memory.source_span) return 5;
    unsigned int sbpp = s->source_format == 2 ? 1 : 2;
    for (unsigned int y = s->top; y < s->bottom; ++y) {
        unsigned int j = y - s->dy;
        unsigned int sy = s->tile ? j % s->source_height : (unsigned long)j * s->source_height / s->height;
        for (unsigned int x = s->left; x < s->right; ++x) {
            unsigned int i = x - s->dx;
            unsigned int sx = s->tile ? i % s->source_width : (unsigned long)i * s->source_width / s->width;
            const unsigned char *input = src + s->memory.source_offset + sy * s->memory.source_pitch + sx * sbpp;
            unsigned char *output = dst + y * s->memory.destination_pitch + x * 2UL;
            unsigned int r, g, b, a;
            unsigned short pixel = 0;
            if (sbpp == 1) {
                r = s->tint & 255; g = s->tint >> 8 & 255; b = s->tint >> 16 & 255; a = input[0];
            } else {
                pixel = get16(input);
                r = (pixel >> 12) * 17; g = (pixel >> 8 & 15) * 17; b = (pixel >> 4 & 15) * 17; a = (pixel & 15) * 17;
            }
            if (!s->mode) put16(output, pixel);
            else put16(output, blend(get16(output), r, g, b, (a * s->alpha + 127) / 255));
        }
    }
    return 0;
}

int gpe_fill_rgba4444(unsigned char *dst, unsigned long capacity, const unsigned int *p) {
    if (!dst || !p) return 5;
    const unsigned char *color = (const unsigned char *)(p + 8), *flags = (const unsigned char *)(p + 9);
    unsigned int x = p[2], y = p[3], w = p[4], h = p[5], stride = p[6];
    if (p[7] || flags[0] > 1 || (!flags[0] && flags[1] != 255) || !w || !h ||
        w > 8192 || h > 8192 || x > 16383 || y > 16383 || !stride || stride > 16384 ||
        x > stride || w > stride - x || ((y + h - 1UL) * stride + x + w) * 2 > capacity) return 5;
    unsigned short pixel = pack(color[0], color[1], color[2], color[3]);
    unsigned int alpha = (color[3] * flags[1] + 127) / 255;
    for (unsigned int row = 0; row < h; ++row)
        for (unsigned int col = 0; col < w; ++col) {
            unsigned char *output = dst + ((y + row) * (unsigned long)stride + x + col) * 2;
            put16(output, flags[0] ? blend(get16(output), color[0], color[1], color[2], alpha) : pixel);
        }
    return 0;
}
