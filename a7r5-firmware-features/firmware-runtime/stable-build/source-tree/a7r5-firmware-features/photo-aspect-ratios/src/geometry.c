#include "geometry.h"

const R5AspectRatio r5_aspect_ratios[R5_ASPECT_COUNT] = {
    {3, 2}, {4, 3}, {16, 9}, {1, 1},
    {17, 6}, {65, 24}, {5, 4}, {7, 6}, {191, 100}, {47, 20}
};

/* ARMv7 裸机编译时不依赖除法运行库。所有调用的除数均为正。 */
static uint32_t divide(uint32_t value, uint32_t divisor)
{
    uint32_t quotient = 0;
    uint32_t remainder = 0;
    for (unsigned bit = 32; bit != 0; --bit) {
        remainder = (remainder << 1) | ((value >> (bit - 1)) & 1u);
        if (remainder >= divisor) {
            remainder -= divisor;
            quotient |= 1u << (bit - 1);
        }
    }
    return quotient;
}

int r5_aspect_fit(uint16_t p, uint16_t q, const R5AspectRect *view, R5AspectRect *result)
{
    if (!p || !q || !view || !result ||
        !view->width || !view->height ||
        (uint32_t)view->x + view->width > UINT16_MAX ||
        (uint32_t)view->y + view->height > UINT16_MAX)
        return 0;

    uint32_t width = view->width;
    uint32_t height = view->height;
    if (width * q >= height * p)
        width = divide(height * p, q);
    else
        height = divide(width * q, p);
    if (!width || !height)
        return 0;

    *result = (R5AspectRect) {
        view->x + (view->width - width) / 2u,
        view->y + (view->height - height) / 2u,
        width, height
    };
    return 1;
}

int r5_aspect_viewport(uint32_t id, const R5AspectRect *view, int portrait,
                       R5AspectRect *result)
{
    if (id >= R5_ASPECT_COUNT)
        return 0;
    R5AspectRatio ratio = r5_aspect_ratios[id];
    if (portrait)
        return r5_aspect_fit(ratio.denominator, ratio.numerator, view, result);
    return r5_aspect_fit(ratio.numerator, ratio.denominator, view, result);
}

int r5_aspect_crop(uint32_t id, const R5AspectGeometry *source, int auxiliary,
                   uint32_t physical_base_low, R5AspectGeometry *result)
{
    if (id < R5_ASPECT_NATIVE_COUNT || id >= R5_ASPECT_COUNT || !source || !result)
        return 0;

    R5AspectGeometry input = *source;
    uint32_t sw = input.width, sh = input.height;
    uint32_t cw = input.canvas_width, ch = input.canvas_height;
    uint32_t tolerance = auxiliary ? 16u : 0u;
    if (!sw || !sh || (sw & 1u) || (sh & 1u) || (cw & 127u) ||
        (physical_base_low & 15u) ||
        sw * 2u > sh * 3u + tolerance || sh * 3u > sw * 2u + tolerance ||
        input.x + sw > cw || input.y + sh > ch)
        return 0;

    uint32_t p = r5_aspect_ratios[id].numerator;
    uint32_t q = r5_aspect_ratios[id].denominator;
    uint32_t width, height;
    if (sw * q >= sh * p) {
        height = sh & ~7u;
        width = divide(height * p + q * 8u, q * 16u) * 16u;
        if (width > sw)
            width = sw & ~15u;
    } else {
        width = sw & ~15u;
        height = divide(width * q + p * 4u, p * 8u) * 8u;
        if (height > sh)
            height = sh & ~7u;
    }

    uint32_t read_width = (width + 127u) & ~127u;
    if (width < 16u || height < 8u || read_width > cw || height > ch)
        return 0;

    uint32_t x = (input.x + (sw - width) / 2u) & ~7u;
    uint32_t min_x = (input.x + 7u) & ~7u;
    uint32_t max_x = input.x + sw - width;
    if (max_x > cw - read_width)
        max_x = cw - read_width;
    if (x > max_x)
        x = max_x & ~7u;
    if (x < min_x)
        x = min_x;
    if (x > max_x)
        return 0;

    uint32_t y = input.y + (sh - height) / 2u;
    if (y > ch - height)
        y = ch - height;
    *result = (R5AspectGeometry) {cw, ch, width, height, x, y};
    return 1;
}
