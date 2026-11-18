/* 4.29 常驻 CP 纵横比核心实现（紧凑等价版，放入 .text 安全区 0xbef7b0..0xbefdc0 <= 1552B）。 */
#include <stdint.h>

typedef struct {
    uint16_t canvas_width, canvas_height;
    uint16_t width, height;
    uint16_t x, y;
} R5AspectGeometry;

enum {
    GFW = 0x157aa10, MANAGER = 0x163f3c8, POOL = 0x1112c54,
    GFW_ASPECT = 0xcc, SNAPSHOT = MANAGER + 0x28, SNAPSHOT_BYTES = 0xdbc,
    TASK_STRIDE = 0x6688, TASK_COUNT = 490, TASK_ASPECT = 0x24,
    TASK_REQUEST = 0x5ae8, TASK_PRIMARY = 0x5980, TASK_SECONDARY = 0x5988,
    MAIN_ROI = 0x5f78, SCN_ROI = 0x5fdc
};

typedef struct {
    uint32_t selection, sequence, frozen_id, request;
    uint8_t tasks[TASK_COUNT];
} AspectState;

#define state (*(AspectState *)0x1a394a0u)
_Static_assert(sizeof(AspectState) <= 512, "CP 比例状态超出 512B 限制");

static const uint16_t RATIOS[6][2] = {
    {17, 6}, {65, 24}, {5, 4}, {7, 6}, {191, 100}, {47, 20}
};

static inline uint32_t r32(uintptr_t addr) { return *(const volatile uint32_t *)addr; }
static inline uint16_t r16(const uint8_t *p) { return (uint16_t)(p[0] | (uint16_t)p[1] << 8); }
static inline int custom(uint32_t id) { return id >= 4u && id < 10u; }

static uint32_t udiv(uint32_t v, uint32_t d) {
    uint32_t q = 0, r = 0;
    for (int i = 31; i >= 0; --i) {
        r = (r << 1) | ((v >> i) & 1u);
        if (r >= d) { r -= d; q |= 1u << i; }
    }
    return q;
}

static int crop_geo(uint32_t id, const R5AspectGeometry *src, int aux, R5AspectGeometry *dst) {
    if (!custom(id) || !src || !dst) return 0;
    uint32_t sw = src->width, sh = src->height, cw = src->canvas_width, ch = src->canvas_height;
    uint32_t tol = aux ? 16u : 0u;
    if (!sw || !sh || (sw & 1u) || (sh & 1u) || (cw & 127u) ||
        sw * 2u > sh * 3u + tol || sh * 3u > sw * 2u + tol ||
        src->x + sw > cw || src->y + sh > ch)
        return 0;
    uint32_t p = RATIOS[id - 4u][0], q = RATIOS[id - 4u][1], w, h;
    if (sw * q >= sh * p) {
        h = sh & ~7u;
        w = udiv(h * p + q * 8u, q * 16u) * 16u;
        if (w > sw) w = sw & ~15u;
    } else {
        w = sw & ~15u;
        h = udiv(w * q + p * 4u, p * 8u) * 8u;
        if (h > sh) h = sh & ~7u;
    }
    uint32_t rw = (w + 127u) & ~127u;
    if (w < 16u || h < 8u || rw > cw || h > ch) return 0;
    uint32_t x = (src->x + (sw - w) / 2u) & ~7u;
    uint32_t min_x = (src->x + 7u) & ~7u;
    uint32_t max_x = src->x + sw - w;
    if (max_x > cw - rw) max_x = cw - rw;
    if (x > max_x) x = max_x & ~7u;
    if (x < min_x) x = min_x;
    if (x > max_x) return 0;
    uint32_t y = src->y + (sh - h) / 2u;
    if (y > ch - h) y = ch - h;
    *dst = (R5AspectGeometry){(uint16_t)cw, (uint16_t)ch, (uint16_t)w, (uint16_t)h, (uint16_t)x, (uint16_t)y};
    return 1;
}

static uint8_t *slot(uintptr_t task) {
    uint32_t base = r32(POOL + 0x10), count = r32(POOL + 4);
    if (!base || count > TASK_COUNT || task < base) return 0;
    uint32_t off = task - base, idx = udiv(off, TASK_STRIDE);
    return (idx < count && idx * TASK_STRIDE == off) ? &state.tasks[idx] : 0;
}

static uint32_t task_id(uintptr_t task) {
    uint8_t *e = slot(task);
    return (e && r32(task + TASK_ASPECT) == 2) ? __atomic_load_n(e, __ATOMIC_ACQUIRE) : 0;
}

static int is_jpeg(uintptr_t task) {
    uint32_t p = r32(task + TASK_PRIMARY), s = r32(task + TASK_SECONDARY);
    return p == 1 || s == 1 || p == 2 || s == 2;
}

void r5_cp_select(uintptr_t gfw, uint32_t wire) {
    uint32_t id = wire - 0xe0u + 4u;
    uint32_t tok = (__atomic_load_n(&state.selection, __ATOMIC_RELAXED) & ~15u) + 16u;
    __atomic_store_n(&state.selection, tok, __ATOMIC_SEQ_CST);
    *(volatile uint32_t *)(gfw + GFW_ASPECT) = custom(id) ? 2u : wire;
    __atomic_store_n(&state.selection, custom(id) ? (tok | id) : tok, __ATOMIC_RELEASE);
}

void *r5_cp_snapshot(void *dst, const void *src, uint32_t bytes, uint32_t caller) {
    uint32_t sel = __atomic_load_n(&state.selection, __ATOMIC_ACQUIRE);
    uint32_t req = r32(MANAGER);
    void *res = ((void *(*)(void *, const void *, uint32_t))0x5f51bcu)(dst, src, bytes);
    if ((uintptr_t)dst != SNAPSHOT) return res;
    uint32_t id = sel & 15u;
    if (caller != 0xaf153bu || (uintptr_t)src != GFW || bytes != SNAPSHOT_BYTES ||
        !custom(id) || r32(SNAPSHOT + GFW_ASPECT) != 2 || req != r32(MANAGER) ||
        sel != __atomic_load_n(&state.selection, __ATOMIC_ACQUIRE))
        id = 0;
    uint32_t seq = __atomic_load_n(&state.sequence, __ATOMIC_RELAXED) + 2u;
    __atomic_store_n(&state.sequence, seq | 1u, __ATOMIC_SEQ_CST);
    state.request = req;
    state.frozen_id = id;
    __atomic_store_n(&state.sequence, seq, __ATOMIC_RELEASE);
    return res;
}

void r5_cp_capture_copy(void *dst, const void *src) {
    uintptr_t task = (uintptr_t)dst - 0x20u;
    uint8_t *e = slot(task);
    if (e) __atomic_store_n(e, 0, __ATOMIC_RELEASE);
    ((void (*)(void *, const void *))0x4596f5u)(dst, src);
    if (!e || (uintptr_t)src != SNAPSHOT || r32(task + TASK_ASPECT) != 2) return;
    uint32_t seq = __atomic_load_n(&state.sequence, __ATOMIC_ACQUIRE);
    uint32_t req = state.request, id = state.frozen_id;
    __atomic_thread_fence(__ATOMIC_ACQ_REL);
    if (!(seq & 1u) && seq == __atomic_load_n(&state.sequence, __ATOMIC_RELAXED) &&
        req == r32(task + TASK_REQUEST) && req == r32(MANAGER) && custom(id))
        __atomic_store_n(e, (uint8_t)id, __ATOMIC_RELEASE);
}

void r5_cp_pool_reset(uintptr_t pool) {
    if (pool == POOL) ((void (*)(void *, uint32_t))0x5f58b0u)(state.tasks, TASK_COUNT);
}

void *r5_cp_clone_copy(void *dst, const void *src, uint32_t bytes) {
    void *res = ((void *(*)(void *, const void *, uint32_t))0x5f51bcu)(dst, src, bytes);
    uintptr_t task = (uintptr_t)dst - 0x20u;
    uint8_t *e = slot(task);
    if (e) {
        uint32_t id = task_id((uintptr_t)src - 0x20u);
        if (r32(task + TASK_ASPECT) != 2 || !custom(id)) id = 0;
        __atomic_store_n(e, (uint8_t)id, __ATOMIC_RELEASE);
    }
    return res;
}

void r5_cp_pool_release(uintptr_t pool, uintptr_t task) {
    if (pool == POOL) {
        uint8_t *e = slot(task);
        if (e) __atomic_store_n(e, 0, __ATOMIC_RELEASE);
    }
    ((void (*)(uintptr_t, uintptr_t))0xae0993u)(pool, task);
}

void *r5_cp_jpeg_copy(void *dst, const void *src, uint32_t bytes, uintptr_t task) {
    void *res = ((void *(*)(void *, const void *, uint32_t))0x5f51bcu)(dst, src, bytes);
    uint32_t id = task_id(task);
    uintptr_t off = (uintptr_t)src - task;
    if (custom(id) && is_jpeg(task) && bytes == sizeof(R5AspectGeometry)) {
        if (off == MAIN_ROI) crop_geo(id, (const R5AspectGeometry *)src, 0, (R5AspectGeometry *)dst);
        else if (off == SCN_ROI) {
            R5AspectGeometry tmp;
            if (crop_geo(id, (const R5AspectGeometry *)(task + MAIN_ROI), 0, &tmp))
                crop_geo(id, (const R5AspectGeometry *)src, 1, (R5AspectGeometry *)dst);
        }
    }
    return res;
}

void r5_cp_thumbnail_clear(uint8_t *dst, uint32_t bytes, uintptr_t task) {
    ((void (*)(void *, uint32_t))0x5f58b0u)(dst, bytes);
    uint32_t id = task_id(task);
    R5AspectGeometry main_g, cropped;
    if (!custom(id) || !is_jpeg(task) || bytes != 0x20 || (r32(task + 0x3c) & 4u) ||
        !crop_geo(id, (const R5AspectGeometry *)(task + MAIN_ROI), 0, &main_g))
        return;
    uint16_t *in = (uint16_t *)(dst - 0xbc), *out = (uint16_t *)(dst - 0x34);
    if (out[4] != 160 || out[5] != 120) return;
    R5AspectGeometry src = {in[0], in[1], in[4], in[5], in[2], in[3]};
    if (!crop_geo(id, &src, 1, &cropped)) return;
    uint32_t fw = 160, fh = 120;
    if (160u * cropped.height <= 120u * cropped.width) fh = udiv(160u * cropped.height, cropped.width);
    else fw = udiv(120u * cropped.width, cropped.height);
    fw &= ~3u; fh &= ~1u;
    if (!fw || !fh) return;
    in[2] = cropped.x; in[3] = cropped.y;
    in[4] = in[8] = cropped.width; in[5] = in[9] = cropped.height;
    out[6] = (uint16_t)((160u - fw) / 2u); out[7] = (uint16_t)((120u - fh) / 2u);
    out[8] = (uint16_t)fw; out[9] = (uint16_t)fh;
}

void r5_cp_notify_jpeg(uint16_t *wh, uintptr_t task, uint32_t fmt) {
    uint32_t id = task_id(task);
    if (!custom(id) || (fmt != 1 && fmt != 4)) return;
    R5AspectGeometry res;
    const uint8_t *src = (const uint8_t *)(task + MAIN_ROI);
    if (r16(src + 4) == wh[0] && r16(src + 6) == wh[1] &&
        crop_geo(id, (const R5AspectGeometry *)src, 0, &res)) {
        wh[0] = res.width; wh[1] = res.height;
    }
}

uint32_t r5_cp_raw_emb(void *pkt, uint8_t *hdr, uintptr_t task) {
    uint32_t res = ((uint32_t (*)(void *, void *, uintptr_t))0xade83du)(pkt, hdr, task);
    uint32_t id = task_id(task);
    const uint16_t *full = (const uint16_t *)(task + 0x234);
    R5AspectGeometry src = {(uint16_t)((full[0] + 127u) & ~127u), full[1], full[0], full[1], 0, 0}, crop;
    if (hdr && custom(id) && crop_geo(id, &src, 0, &crop)) {
        for (int i = 0; i < 4; ++i) {
            hdr[0x14a2c + i] = (uint8_t)(crop.width >> (8 * i));
            hdr[0x14a30 + i] = (uint8_t)(crop.height >> (8 * i));
        }
    }
    return res;
}
