/* 公式及固定摘要见tests/fixtures/edit_front32_source_lock.json；不读写设备。 */
#include "af_edit_front.h"
#include <float.h>
#include <stdint.h>

#if defined(__FAST_MATH__)
#error "RAW 前端需要逐步 float32 舍入，禁止 fast-math"
#endif
_Static_assert(sizeof(float) == 4 && FLT_RADIX == 2 && FLT_MANT_DIG == 24,
               "需要 IEEE float32");

static int span(const void *p, size_t bytes, uintptr_t *end) {
    uintptr_t a = (uintptr_t)p;
    if (!p || !bytes || a > UINTPTR_MAX - bytes) return 0;
    *end = a + bytes;
    return 1;
}
static int separate(const void *a, size_t an, const void *b, size_t bn) {
    uintptr_t ae, be;
    return span(a, an, &ae) && span(b, bn, &be) &&
           (ae <= (uintptr_t)b || be <= (uintptr_t)a);
}
static uint16_t u16(const uint8_t *p) {
    return (uint16_t)((uint16_t)p[0] | (uint16_t)p[1] << 8);
}
static uint32_t u32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static int16_t s16(uint16_t n) {
    return (int16_t)(n <= INT16_MAX ? (int32_t)n : (int32_t)n - 65536);
}
static int parameters(const AfEditFront *p) {
    if (!p || (uintptr_t)p % _Alignof(AfEditFront) || !p->scale || p->maximum < 0)
        return 0;
    for (unsigned c = 0; c < 3; ++c)
        if (p->wb[c] < 0 || p->threshold[c] < 0 || p->threshold[c] > p->maximum ||
            p->weights[c] > 1020) return 0;
    return 1;
}
int af_edit_front_parse_neutral(const void *raw, size_t rn, const void *settings,
                               size_t sn, AfEditFront *output) {
    if (rn < 0x1400 || sn < 0x2b2 || (uintptr_t)output % _Alignof(AfEditFront) ||
        !separate(raw, rn, output, sizeof(*output)) ||
        !separate(settings, sn, output, sizeof(*output))) return AF_EDIT_FRONT_INVALID;
    const uint8_t *r = raw, *s = settings;
    if (u32(r+0x84) != 0 || u32(r+0x88) != 1 || u32(r+0x8c) != 1 ||
        u32(r+0x90) != 2 || u32(s+0x1e8) != 1 || u32(s+0x1f0) ||
        u32(s+0x1f4) || u32(s+0x1f8) || u16(r+0x4c) != u16(r+0x4e) ||
        u16(r+0x3a) != u16(r+0x3c)) return AF_EDIT_FRONT_UNSUPPORTED;
    AfEditFront p = {0};
    p.scale = u16(r+0x40);
    p.maximum = s16(u16(r+0xf82));
    const unsigned b[3] = {0x38,0x3a,0x3e}, w[3] = {0x4a,0x4c,0x50};
    for (unsigned c = 0; c < 3; ++c) {
        p.black[c] = u16(r+b[c]);
        /* 零 EV/偏移/色调时，二进制精确的 gain/256 可用整数除法向零截断。 */
        int64_t scaled = (int64_t)s16(u16(r+w[c])) * u32(r+0x9d8) / 256;
        p.wb[c] = s16((uint16_t)((uint64_t)scaled & 65535u));
        p.threshold[c] = s16(u16(r+0xf84+2*c));
    }
    p.weights[0] = r[0x1207];
    p.weights[1] = (uint16_t)(r[0x1208] + r[0x1209]);
    p.weights[2] = r[0x120a];
    if (!parameters(&p)) return AF_EDIT_FRONT_UNSUPPORTED;
    *output = p;
    return AF_EDIT_FRONT_OK;
}
static int buffers(const AfEditFront *p, const uint16_t *in, size_t n, uint16_t *out) {
    if (!n || n > AF_EDIT_FRONT_LIMIT || (uintptr_t)in % _Alignof(uint16_t) ||
        (uintptr_t)out % _Alignof(uint16_t)) return 0;
    size_t bytes = n * 3 * sizeof(uint16_t);
    return separate(in, bytes, out, bytes) &&
           separate(p, sizeof(*p), in, bytes) &&
           separate(p, sizeof(*p), out, bytes) && parameters(p);
}
int af_edit_front_itp(const AfEditFront *p, const uint16_t *in, size_t n, uint16_t *out) {
    if (!buffers(p, in, n, out)) return AF_EDIT_FRONT_INVALID;
    for (size_t i = 0; i < n*3; ++i)
        if (in[i] > 16383) return AF_EDIT_FRONT_INVALID;
    float gains[3];
    for (unsigned c = 0; c < 3; ++c) {
        gains[c] = (float)p->scale * (1.0f/32768.0f);
        gains[c] = gains[c] * (float)p->wb[c];
        gains[c] = gains[c] * (1.0f/16.0f);
    }
    for (size_t i = 0; i < n*3; ++i) {
        float v = (float)((int32_t)in[i] - p->black[i%3]) * gains[i%3];
        out[i] = v <= 0.0f ? 0 : v >= 16383.0f ? 16383 : (uint16_t)v;
    }
    return AF_EDIT_FRONT_OK;
}
/* C 的负数右移与窄有符号转换不作语言级假设。 */
static int64_t right(int64_t v, unsigned bits) {
    int64_t d = (int64_t)1 << bits;
    return v >= 0 ? v / d : -((-v + d - 1) / d);
}
static int64_t signed32(int64_t v) {
    uint32_t n = (uint32_t)(uint64_t)v;
    return n <= INT32_MAX ? (int64_t)n : (int64_t)n - INT64_C(4294967296);
}
static int64_t divide(int64_t v, int64_t d) { return d ? v/d : 0; }
int af_edit_front_sscs(const AfEditFront *p, const uint16_t *in, size_t n, uint16_t *out) {
    if (!buffers(p, in, n, out)) return AF_EDIT_FRONT_INVALID;
    for (size_t i = 0; i < n; ++i) {
        int64_t r=in[3*i], g=in[3*i+1], b=in[3*i+2];
        int64_t tr=p->threshold[0], tg=p->threshold[1], tb=p->threshold[2];
        if (r <= tr || g <= tg || b <= tb) {
            out[3*i]=(uint16_t)r; out[3*i+1]=(uint16_t)g; out[3*i+2]=(uint16_t)b;
            continue;
        }
        int64_t gf = divide((g-tg)*128,p->maximum-tg);
        if (gf > 128) gf=128;
        int64_t selected=b<r?b:r, t=b<r?tb:tr;
        int64_t sf=selected>p->maximum?128:divide((selected-t)*128,p->maximum-t);
        int64_t amount=128-right(sf*gf,7), dr=amount*(r-g), db=amount*(b-g);
        int64_t green=right(signed32(((int64_t)p->weights[0]*r+
                      (int64_t)p->weights[1]*g+(int64_t)p->weights[2]*b)*128-
                      dr*p->weights[0]-db*p->weights[2]),14);
        out[3*i]=(uint16_t)((uint64_t)right(signed32(green*128+dr),7)&65535u);
        out[3*i+1]=(uint16_t)((uint64_t)green&65535u);
        out[3*i+2]=(uint16_t)((uint64_t)right(signed32(green*128+db),7)&65535u);
    }
    return AF_EDIT_FRONT_OK;
}
