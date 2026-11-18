/* 无动态分配、无文件接口、不依赖locale。三维解析与插值不代表成像转换。 */
#include "af_cube.h"
#include <float.h>

static int space(char c) { return c == ' ' || c == '\t' || c == '\r'; }
static int digit(char c) { return c >= '0' && c <= '9'; }
static const char *skip(const char *p, const char *end) {
    while (p < end && space(*p)) ++p;
    return p;
}
static int ended(const char *p, const char *end) {
    p = skip(p, end);
    return p == end || *p == '#';
}
static int key(const char *p, const char *end, const char *name, const char **rest) {
    while (*name && p < end && *name == *p) { ++name; ++p; }
    if (*name || (p < end && !space(*p))) return 0;
    *rest = skip(p, end);
    return 1;
}

/* 有限十进制：最多32个尾数数字，显式指数绝对值最多64。 */
static int number(const char **cursor, const char *end, float *output) {
    const char *p = skip(*cursor, end);
    double value = 0;
    int sign = 1, digits = 0, fraction = 0, exponent = 0, exp_sign = 1, shift;
    if (p < end && (*p == '+' || *p == '-')) { if (*p == '-') sign = -1; ++p; }
    while (p < end && digit(*p)) {
        if (++digits > 32) return 0;
        value = value*10 + (*p++-'0');
    }
    if (p < end && *p == '.') {
        ++p;
        while (p < end && digit(*p)) {
            if (++digits > 32) return 0;
            ++fraction;
            value = value*10 + (*p++-'0');
        }
    }
    if (!digits) return 0;
    if (p < end && (*p == 'e' || *p == 'E')) {
        ++p;
        if (p < end && (*p == '+' || *p == '-')) { if (*p == '-') exp_sign = -1; ++p; }
        if (p == end || !digit(*p)) return 0;
        while (p < end && digit(*p)) {
            exponent = exponent*10 + (*p++-'0');
            if (exponent > 64) return 0;
        }
    }
    if (p < end && !space(*p) && *p != '#') return 0;
    shift = exp_sign*exponent - fraction;
    while (shift > 0) { value *= 10; --shift; }
    while (shift < 0) { value /= 10; ++shift; }
    value *= sign;
    if (value > FLT_MAX || value < -FLT_MAX) return 0;
    *output = (float)value;
    *cursor = p;
    return 1;
}

static int triple(const char *p, const char *end, float values[3]) {
    uint32_t i;
    for (i = 0; i < 3; ++i) if (!number(&p, end, &values[i])) return 0;
    return ended(p, end);
}

static int domain_valid(const AfCube *cube) {
    uint32_t i;
    for (i = 0; i < 3; ++i)
        if (!(cube->domain_max[i] > cube->domain_min[i])) return 0;
    return 1;
}

int af_cube_parse(const char *source, size_t bytes, AfCube *output,
                  float *storage, size_t capacity_floats, AfCubeLimits limits) {
    AfCube candidate;
    const char *p, *end;
    size_t count = 0, needed = 0;
    uint32_t i, seen_min = 0, seen_max = 0, seen_title = 0;
    if (!source || !output || !storage || !bytes) return AF_CUBE_INVALID;
    if (bytes > limits.max_bytes || limits.max_dimension < 2) return AF_CUBE_BUDGET;
    candidate.dimension = 0;
    candidate.values = storage;
    for (i = 0; i < 3; ++i) { candidate.domain_min[i] = 0; candidate.domain_max[i] = 1; }
    p = source;
    end = source + bytes;
    while (p < end) {
        const char *line = p, *line_end, *rest;
        float values[3];
        while (p < end && *p != '\n') { if (*p == '\0') return AF_CUBE_INVALID; ++p; }
        line_end = p;
        if (p < end) ++p;
        if ((size_t)(line_end-line) > 4096) return AF_CUBE_BUDGET;
        line = skip(line, line_end);
        if (ended(line, line_end)) continue;
        if (key(line, line_end, "LUT_3D_SIZE", &rest)) {
            uint32_t n = 0;
            size_t total;
            if (candidate.dimension || count || rest == line_end || !digit(*rest)) return AF_CUBE_INVALID;
            while (rest < line_end && digit(*rest)) {
                uint32_t d = (uint32_t)(*rest++-'0');
                if (n > (UINT32_MAX-d)/10) return AF_CUBE_BUDGET;
                n = n*10+d;
            }
            if (!ended(rest, line_end) || n < 2) return AF_CUBE_INVALID;
            if (n > limits.max_dimension) return AF_CUBE_BUDGET;
            total = n;
            if (total > SIZE_MAX/n) return AF_CUBE_BUDGET;
            total *= n;
            if (total > SIZE_MAX/n) return AF_CUBE_BUDGET;
            total *= n;
            if (total > SIZE_MAX/3) return AF_CUBE_BUDGET;
            needed = total*3;
            if (needed > capacity_floats) return AF_CUBE_CAPACITY;
            candidate.dimension = n;
        } else if (key(line, line_end, "DOMAIN_MIN", &rest)) {
            if (count || seen_min++ || !triple(rest, line_end, candidate.domain_min)) return AF_CUBE_INVALID;
        } else if (key(line, line_end, "DOMAIN_MAX", &rest)) {
            if (count || seen_max++ || !triple(rest, line_end, candidate.domain_max)) return AF_CUBE_INVALID;
        } else if (key(line, line_end, "TITLE", &rest)) {
            if (count || seen_title++ || rest == line_end || *rest++ != '"') return AF_CUBE_INVALID;
            while (rest < line_end && *rest != '"') ++rest;
            if (rest == line_end || !ended(rest+1, line_end)) return AF_CUBE_INVALID;
        } else {
            if (!candidate.dimension || !domain_valid(&candidate)) return AF_CUBE_INVALID;
            if (!triple(line, line_end, values)) return AF_CUBE_INVALID;
            if (count >= needed) return AF_CUBE_ROWS;
            for (i = 0; i < 3; ++i) storage[count++] = values[i];
        }
    }
    if (!candidate.dimension || !domain_valid(&candidate)) return AF_CUBE_INVALID;
    if (count != needed) return AF_CUBE_ROWS;
    *output = candidate;
    return AF_CUBE_OK;
}

int af_cube_eval(const AfCube *cube, const float rgb[3], float output[3]) {
    uint32_t lower[3], axis, channel, r, g, b;
    double weight[3], result[3] = {0,0,0};
    if (!cube || !rgb || !output || !cube->values || cube->dimension < 2 || !domain_valid(cube)) return AF_CUBE_INVALID;
    for (axis = 0; axis < 3; ++axis) {
        double value, scaled;
        if (!(rgb[axis] >= -FLT_MAX && rgb[axis] <= FLT_MAX)) return AF_CUBE_INVALID;
        value = ((double)rgb[axis]-cube->domain_min[axis]) /
                ((double)cube->domain_max[axis]-cube->domain_min[axis]);
        if (value < 0) value = 0;
        if (value > 1) value = 1;
        scaled = value*(cube->dimension-1);
        lower[axis] = value == 1 ? cube->dimension-2 : (uint32_t)scaled;
        weight[axis] = scaled-lower[axis];
    }
    for (b = 0; b < 2; ++b) for (g = 0; g < 2; ++g) for (r = 0; r < 2; ++r) {
        size_t index = (((size_t)lower[2]+b)*cube->dimension+lower[1]+g)*cube->dimension+lower[0]+r;
        double w = (r ? weight[0] : 1-weight[0])*(g ? weight[1] : 1-weight[1])*(b ? weight[2] : 1-weight[2]);
        for (channel = 0; channel < 3; ++channel) result[channel] += w*cube->values[index*3+channel];
    }
    for (channel = 0; channel < 3; ++channel) {
        if (!(result[channel] >= -FLT_MAX && result[channel] <= FLT_MAX)) return AF_CUBE_INVALID;
    }
    for (channel = 0; channel < 3; ++channel) output[channel] = (float)result[channel];
    return AF_CUBE_OK;
}
