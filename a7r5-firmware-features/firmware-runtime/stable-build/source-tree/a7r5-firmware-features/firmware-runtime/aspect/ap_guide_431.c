/* 4.29 拍摄页 guide 控件适配：
 * 1. 从 view+8 读取真实 layer（修复原误把 W1 Scene ID 当成 layer 的缺陷）；
 * 2. 纯整数计算（配合 -mgeneral-regs-only，绝不污染取景线程浮点/NEON 寄存器）；
 * 3. 非自定义模式下始终调用原厂 stock_draw，绝不跳过原厂绘制。
 */
#include "geometry.h"
#include "ap_state.h"
#include <stddef.h>

enum {
    GUIDE_KIND = 0x3d, PARAMETER = 0x1d8, LAYERS = 6,
    PHOTO_MODE = 2, SOURCE_WIDTH = 640, SOURCE_HEIGHT = 480,
};

struct control_row { uint32_t type, fields[12]; };
struct view_row { uint32_t type, reserved; void *parameter; };
struct rect { int32_t x, y, width, height; };
struct guide_slot {
    void *widget;
    uint64_t generation;
    uint32_t completed;
    uint8_t forced;
    uint8_t custom;
};

_Static_assert(sizeof(struct control_row) == 0x34, "control row ABI");
_Static_assert(sizeof(struct view_row) == 0x10, "view row ABI");
_Static_assert(sizeof(struct guide_slot) == 24, "guide state ABI");

extern uint32_t aspect_selection;
extern struct guide_slot aspect_guide_slots[2 * LAYERS];
extern const char stock_view_vtable[], stock_guide_vtable[];
extern const struct control_row stock_descriptors_a[], stock_descriptors_a_alt[];
extern const struct control_row stock_descriptors_b[], stock_descriptors_b_alt[];
extern void stock_guide_produce(void *, void *, void *, const void *);
extern void r5_aspect_guide_body(void *, void *, void *, const void *);
extern unsigned r5_aspect_stock_cap_a(void *, unsigned);
extern unsigned r5_aspect_stock_cap_b(void *, unsigned);
extern void r5_aspect_stock_draw(void *);
extern void r5_aspect_stock_destroy(void *);
extern void stock_guide_portrait_viewport(void *, struct rect *);
extern void stock_guide_rect_draw(void *, unsigned, unsigned, const struct rect *, unsigned);

/* 四份固定描述表用到的构造成本。单位为 128 字节，列分别为完整和禁用控件。 */
static const uint16_t costs[141][2] = {
    [0] = {7, 1}, [1] = {7, 1}, [2] = {21, 13}, [10] = {12, 1},
    [13] = {12, 1}, [14] = {12, 1}, [15] = {23, 1}, [20] = {12, 1},
    [22] = {46, 1}, [25] = {11, 1}, [28] = {5120, 27}, [35] = {18, 1},
    [38] = {12, 1}, [39] = {25, 1}, [41] = {18, 1}, [47] = {32, 1},
    [48] = {18, 1}, [49] = {66, 1}, [51] = {19, 3}, [56] = {23, 1},
    [58] = {84, 2}, [61] = {54, 1}, [63] = {148, 1}, [64] = {127, 1},
    [66] = {6, 2}, [73] = {94, 1}, [76] = {98, 1}, [77] = {85, 1},
    [78] = {52, 1}, [79] = {52, 1}, [88] = {60, 1}, [89] = {263, 1},
    [92] = {248, 2}, [97] = {197, 8}, [98] = {39, 7}, [99] = {19, 1},
    [100] = {116, 7}, [101] = {33, 7}, [102] = {6, 1}, [103] = {6, 1},
    [104] = {6, 1}, [105] = {6, 1}, [106] = {6, 1}, [107] = {6, 1},
    [108] = {6, 1}, [114] = {94, 1}, [118] = {53, 1}, [122] = {11, 1},
    [123] = {32, 1}, [124] = {32, 1}, [125] = {39, 1}, [126] = {32, 1},
    [127] = {32, 1}, [128] = {53, 1}, [133] = {12, 1}, [137] = {46, 1},
    [140] = {2073, 5},
};

static unsigned photo_selection(uint32_t token, const void *snapshot) {
    const uint32_t *values = snapshot;
    unsigned id = token & 0xffu;
    if (id - R5_ASPECT_NATIVE_COUNT >= R5_ASPECT_COUNT - R5_ASPECT_NATIVE_COUNT ||
        !values || values[0x24d8 / 4] != PHOTO_MODE || values[0x24b0 / 4] != 0)
        return 0;
    return id;
}

static void clear_slot(struct guide_slot *slot) {
    slot->completed = 0;
    slot->custom = 0;
    slot->widget = NULL;
    ++slot->generation;
}

static struct guide_slot *find_slot(const void *widget) {
    for (unsigned i = 0; i < 2 * LAYERS; ++i)
        if (aspect_guide_slots[i].widget == widget)
            return &aspect_guide_slots[i];
    return NULL;
}

int r5_aspect_guide_fits(const struct control_row *table, size_t count, const uint8_t *flags,
                        size_t row, uint32_t capacity) {
    uint32_t used = 0;
    if (!table || !flags || row >= count || table[row].type != GUIDE_KIND)
        return 0;
    for (size_t i = 0; i < count; ++i) {
        unsigned type = table[i].type;
        if (type >= sizeof(costs) / sizeof(*costs))
            return 0;
        uint32_t bytes = (uint32_t)costs[type][i != row && flags[i] != 0] * 128u;
        if (!bytes || bytes >= capacity - used)
            return 0;
        used += bytes;
    }
    return 1;
}

uint32_t r5_aspect_guide_before_create(void *view, unsigned scene, const struct control_row *table,
                                       size_t count, unsigned direction, uint8_t *flags) {
    (void)scene;
    (void)direction;
    r5_aspect_restore_once();
    if (!view || !table || !flags)
        return 0;
    unsigned layer = *(const uint32_t *)((const uint8_t *)view + 8);
    if (layer >= LAYERS)
        return 0;
    unsigned family = count == 442u;
    unsigned row = family ? 3u : 4u;
    int layout = (count == 585u && (table == stock_descriptors_a || table == stock_descriptors_a_alt)) ||
                 (family && (table == stock_descriptors_b || table == stock_descriptors_b_alt));
    if (!layout || *(const void **)view != stock_view_vtable || table[row].type != GUIDE_KIND)
        return 0;

    struct guide_slot *slot = &aspect_guide_slots[family * LAYERS + layer];
    clear_slot(slot);
    uint8_t old_flag = flags[row];
    uint32_t capacity = *(const uint32_t *)((const uint8_t *)view + 0x3ea0);
    int forced = old_flag && r5_aspect_guide_fits(table, count, flags, row, capacity);
    if (old_flag && !forced)
        return 0;
    if (forced)
        flags[row] = 0;
    return 0x80000000u | (family << 24) | (layer << 16) | ((uint32_t)forced << 8) | old_flag;
}

void r5_aspect_guide_after_create(void *view, uint8_t *flags, uint32_t token) {
    if (!(token >> 31) || !view || !flags)
        return;
    unsigned family = (token >> 24) & 1u;
    unsigned layer = (token >> 16) & 7u;
    unsigned forced = (token >> 8) & 1u;
    uint8_t old_flag = (uint8_t)token;
    if (layer >= LAYERS)
        return;
    unsigned row = family ? 3u : 4u;
    if (forced)
        flags[row] = old_flag;

    const uint8_t *base = view;
    uint32_t capacity = *(const uint32_t *)(base + 0x3ea0);
    const struct view_row *result = (const struct view_row *)(base + 0x10) + row;
    void *widget = ((void *const *)(base + 0x3ec8))[row];
    uintptr_t arena = *(const uintptr_t *)(base + 0x3e98);
    uintptr_t offset = (uintptr_t)widget - arena;
    if (result->type == GUIDE_KIND && arena && widget && offset < capacity &&
        capacity - offset >= 0x1b00 && result->parameter == (const uint8_t *)widget + PARAMETER &&
        *(const void **)widget == stock_guide_vtable) {
        struct guide_slot *slot = &aspect_guide_slots[family * LAYERS + layer];
        slot->forced = (uint8_t)forced;
        slot->widget = widget;
    }
}

static unsigned capable(const uint8_t *presenter, unsigned row, unsigned family) {
    if (row != (family ? 3u : 4u))
        return 0;
    uint32_t token = __atomic_load_n(&aspect_selection, __ATOMIC_ACQUIRE);
    if (!photo_selection(token, presenter + (family ? 0x15b0 : 0x1780)))
        return 0;
    const struct view_row *rows = *(const struct view_row *const *)(presenter + (family ? 0x1e0 : 0x270));
    return rows && rows[row].type == GUIDE_KIND && rows[row].parameter &&
           find_slot((uint8_t *)rows[row].parameter - PARAMETER);
}

unsigned r5_aspect_guide_cap_a(void *presenter, unsigned row) {
    unsigned allowed = r5_aspect_stock_cap_a(presenter, row);
    if (allowed || *(const uint32_t *)((const uint8_t *)presenter + 0x4ff14) != 16)
        return allowed;
    return capable(presenter, row, 0) ? 1u : 0u;
}

unsigned r5_aspect_guide_cap_b(void *presenter, unsigned row) {
    unsigned allowed = r5_aspect_stock_cap_b(presenter, row);
    if (allowed || *(const uint32_t *)((const uint8_t *)presenter + 0x478c0) != 16)
        return allowed;
    return capable(presenter, row, 1) ? 1u : 0u;
}

void r5_aspect_guide_produce(void *context, void *parameter, void *args, const void *snapshot) {
    struct guide_slot *slot = parameter ? find_slot((uint8_t *)parameter - PARAMETER) : NULL;
    if (!slot) {
        stock_guide_produce(context, parameter, args, snapshot);
        return;
    }
    slot->completed = 0;
    slot->custom = 0;
    uint64_t generation = slot->generation;
    uint32_t token = __atomic_load_n(&aspect_selection, __ATOMIC_ACQUIRE);
    if (photo_selection(token, snapshot) && *(uint32_t *)((uint8_t *)parameter + 0x40) <= 3) {
        slot->custom = 1;
        r5_aspect_guide_body(context, parameter, args, snapshot);
        if (generation == slot->generation &&
            token == __atomic_load_n(&aspect_selection, __ATOMIC_ACQUIRE))
            slot->completed = token;
        return;
    }
    stock_guide_produce(context, parameter, args, snapshot);
}

static void visibility(void *widget, unsigned action) {
    typedef void (*set_visibility)(void *, unsigned);
    (*(const set_visibility *const *)widget)[0x30 / 8](widget, action);
}

/* 纯整数计算两条取景黑边遮罩（无浮点/NEON 指令），避免破坏取景线程上下文。 */
static int compute_mask_bars(uint32_t id, const struct rect *view, int portrait, struct rect bars[2]) {
    if (id >= R5_ASPECT_COUNT || !view || view->width <= 0 || view->height <= 0)
        return 0;
    R5AspectRatio r = r5_aspect_ratios[id];
    uint32_t p = portrait ? r.denominator : r.numerator;
    uint32_t q = portrait ? r.numerator : r.denominator;
    uint32_t vw = (uint32_t)view->width, vh = (uint32_t)view->height;
    uint32_t a = vw * q, b = vh * p;
    if (a > b) {
        uint32_t t = (a - b + q) / (2u * q);
        if (!t || 2u * t >= vw) return 0;
        bars[0] = (struct rect){view->x, view->y, (int32_t)t, view->height};
        bars[1] = (struct rect){view->x + view->width - (int32_t)t, view->y, (int32_t)t, view->height};
    } else {
        uint32_t t = (b - a + p) / (2u * p);
        if (!t || 2u * t >= vh) return 0;
        bars[0] = (struct rect){view->x, view->y, view->width, (int32_t)t};
        bars[1] = (struct rect){view->x, view->y + view->height - (int32_t)t, view->width, (int32_t)t};
    }
    return 1;
}

void r5_aspect_guide_draw(void *widget) {
    struct guide_slot *slot = find_slot(widget);
    uint32_t token = __atomic_load_n(&aspect_selection, __ATOMIC_ACQUIRE);
    unsigned id = token & 0xffu;
    int custom = id - R5_ASPECT_NATIVE_COUNT < R5_ASPECT_COUNT - R5_ASPECT_NATIVE_COUNT;
    if (!slot || !custom || (!slot->custom && !slot->forced)) {
        r5_aspect_stock_draw(widget);
        return;
    }

    uint8_t *p = widget;
    struct rect source = *(const struct rect *)(p + 0x208);
    if (token != slot->completed || !p[0x204] || !p[0x21c] ||
        *(uint32_t *)(p + 0x218) > 3 || source.x < 0 || source.y < 0 ||
        source.width <= 0 || source.height <= 0 ||
        (int64_t)source.x + source.width > SOURCE_WIDTH ||
        (int64_t)source.y + source.height > SOURCE_HEIGHT) {
        visibility(widget, 3);
        return;
    }

    int portrait = p[0x21d] != 0;
    if (portrait)
        stock_guide_portrait_viewport(widget, &source);
    struct rect bars[2], zero = {0, 0, 0, 0};
    if (!compute_mask_bars(id, &source, portrait, bars)) {
        visibility(widget, 3);
        return;
    }
    visibility(widget, 2);
    uint32_t *style = (uint32_t *)(p + 0x224);
    uint32_t old = *style;
    *style = 15;
    for (unsigned i = 0; i < 8; ++i)
        stock_guide_rect_draw(widget, i, i < 2 ? 1u : 0u, i < 2 ? &bars[i] : &zero, i < 2 ? 0x02094052u : ~0u);
    *style = old;
}

void r5_aspect_guide_destroy(void *widget) {
    struct guide_slot *slot = find_slot(widget);
    if (slot)
        clear_slot(slot);
    r5_aspect_stock_destroy(widget);
}
