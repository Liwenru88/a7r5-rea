/* Bounded C adaptation of fwtool/fwtool/lz77/__init__.py (inflateLz77).
 * Copyright (c) 2015 ma1co
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
#include "sony-lz77.h"

static int walk(const unsigned char *src, unsigned long size, unsigned char *dst, unsigned long capacity) {
    static const unsigned char lengths[16] = {3,4,5,6,7,8,9,10,11,12,13,14,15,16,32,64};
    unsigned long in = 0, out = 0;
    while (in < size) {
        unsigned int type = src[in++];
        unsigned long block_start = out;
        if (type == 0x0f) {
            if (size - in < 3) return 5;
            ++in;
            unsigned int count = src[in] | src[in + 1] << 8;
            in += 2;
            if (count > size - in || count > capacity - out) return 5;
            if (dst) for (unsigned int i = 0; i < count; ++i) dst[out + i] = src[in + i];
            in += count; out += count;
        } else if (type == 0xf0) {
            int finished = 0;
            while (!finished) {
                if (in == size) return 5;
                unsigned int flags = src[in++];
                for (unsigned int bit = 0; bit < 8; ++bit) {
                    if (flags & (1u << bit)) {
                        if (size - in < 2) return 5;
                        unsigned int first = src[in++], second = src[in++];
                        unsigned int distance = (first & 15) << 8 | second;
                        if (!distance) { finished = 1; break; }
                        unsigned int count = lengths[first >> 4];
                        if (distance > out - block_start || count > capacity - out) return 5;
                        if (dst) for (unsigned int i = 0; i < count; ++i) dst[out + i] = dst[out + i - distance];
                        out += count;
                    } else {
                        if (in == size || out == capacity) return 5;
                        if (dst) dst[out] = src[in];
                        ++in; ++out;
                    }
                }
            }
        } else return 5;
    }
    return out == capacity ? 0 : 5;
}

int sony_lz77_decode(const unsigned char *src, unsigned long size, unsigned char *dst, unsigned long output_size) {
    if (!src || !size || size > 0x1000000 || !output_size || output_size > 0x1000000) return 5;
    unsigned long s = (unsigned long)src, d = (unsigned long)dst;
    if (s + size < s || (dst && (d + output_size < d || (s < d + output_size && d < s + size)))) return 5;
    /* Validate first: malformed immutable input cannot partially overwrite the destination. */
    if (walk(src, size, 0, output_size)) return 5;
    return dst ? walk(src, size, dst, output_size) : 0;
}
