#include "requests.h"

enum {
    GFW = 0x157aa10, MANAGER = 0x163f3c8, POOL = 0x1112c54,
    GFW_ASPECT = 0xcc, SNAPSHOT = MANAGER + 0x28, SNAPSHOT_BYTES = 0xdbc,
    TASK_STRIDE = 0x6688, TASK_COUNT = 490, TASK_ASPECT = 0x24,
    TASK_REQUEST = 0x5ae8, TASK_PRIMARY = 0x5980, TASK_SECONDARY = 0x5988,
    MAIN_ROI = 0x5f78, SCN_ROI = 0x5fdc, ENCODE_UNION = 0x5b3c
};

typedef struct {
    uint32_t selection, sequence, frozen_id, request;
    uint8_t tasks[TASK_COUNT];
} AspectState;

#define state (*(AspectState *)0x1a3ad80u)
_Static_assert(sizeof(AspectState) <= 512, "CP 比例状态超出映射窗口");

static uint32_t read32(uintptr_t address)
{
    return *(const volatile uint32_t *)address;
}

static int custom(uint32_t id)
{
    return id >= R5_ASPECT_NATIVE_COUNT && id < R5_ASPECT_COUNT;
}

static uint8_t *slot(uintptr_t task)
{
    uint32_t base = read32(POOL + 0x10);
    uint32_t count = read32(POOL + 4);
    if (!base || count > TASK_COUNT || task < base)
        return 0;
    uint32_t offset = task - base;
    uint32_t index = offset / TASK_STRIDE;
    if (index >= count || index * TASK_STRIDE != offset)
        return 0;
    return &state.tasks[index];
}

static uint32_t task_id(uintptr_t task)
{
    uint8_t *entry = slot(task);
    if (!entry || read32(task + TASK_ASPECT) != 2)
        return 0;
    return __atomic_load_n(entry, __ATOMIC_ACQUIRE);
}

static int jpeg(uintptr_t task)
{
    return read32(task + TASK_PRIMARY) == 1 || read32(task + TASK_SECONDARY) == 1;
}

static int jpeg_main_crop(uintptr_t task, uint32_t id, R5AspectGeometry *result)
{
    return r5_aspect_crop(id, (const R5AspectGeometry *)(task + MAIN_ROI), 0, 0, result);
}

void r5_cp_select(uintptr_t gfw, uint32_t wire)
{
    uint32_t id = wire - R5_ASPECT_WIRE_FIRST + R5_ASPECT_NATIVE_COUNT;
    uint32_t token = (__atomic_load_n(&state.selection, __ATOMIC_RELAXED) & ~15u) + 16u;
    __atomic_store_n(&state.selection, token, __ATOMIC_SEQ_CST);
    *(volatile uint32_t *)(gfw + GFW_ASPECT) = custom(id) ? 2 : wire;
    __atomic_store_n(&state.selection, custom(id) ? token | id : token, __ATOMIC_RELEASE);
}

void *r5_cp_snapshot(void *destination, const void *source, uint32_t bytes, uint32_t caller)
{
    uint32_t selected = __atomic_load_n(&state.selection, __ATOMIC_ACQUIRE);
    uint32_t request = read32(MANAGER);
    void *result = ((void *(*)(void *, const void *, uint32_t))0x5f51bcu)(destination, source, bytes);
    if ((uintptr_t)destination != SNAPSHOT)
        return result;
    uint32_t id = selected & 15u;
    if (caller != 0xaf153bu || (uintptr_t)source != GFW || bytes != SNAPSHOT_BYTES ||
        !custom(id) || read32(SNAPSHOT + GFW_ASPECT) != 2 ||
        request != read32(MANAGER) ||
        selected != __atomic_load_n(&state.selection, __ATOMIC_ACQUIRE))
        id = 0;
    uint32_t sequence = __atomic_load_n(&state.sequence, __ATOMIC_RELAXED) + 2u;
    __atomic_store_n(&state.sequence, sequence | 1u, __ATOMIC_SEQ_CST);
    __atomic_store_n(&state.request, request, __ATOMIC_RELAXED);
    __atomic_store_n(&state.frozen_id, id, __ATOMIC_RELAXED);
    __atomic_store_n(&state.sequence, sequence, __ATOMIC_RELEASE);
    return result;
}

void r5_cp_capture_copy(void *destination, const void *source)
{
    uintptr_t task = (uintptr_t)destination - 0x20u;
    uint8_t *entry = slot(task);
    if (entry)
        __atomic_store_n(entry, 0, __ATOMIC_RELEASE);
    ((void (*)(void *, const void *))0x4596f5u)(destination, source);
    if (!entry || (uintptr_t)source != SNAPSHOT || read32(task + TASK_ASPECT) != 2)
        return;
    uint32_t seq = __atomic_load_n(&state.sequence, __ATOMIC_ACQUIRE);
    uint32_t request = __atomic_load_n(&state.request, __ATOMIC_RELAXED);
    uint32_t id = __atomic_load_n(&state.frozen_id, __ATOMIC_RELAXED);
    __atomic_thread_fence(__ATOMIC_ACQ_REL);
    if (!(seq & 1u) && seq == __atomic_load_n(&state.sequence, __ATOMIC_RELAXED) &&
        request == read32(task + TASK_REQUEST) && request == read32(MANAGER) && custom(id))
        __atomic_store_n(entry, (uint8_t)id, __ATOMIC_RELEASE);
}

void r5_cp_pool_reset(uintptr_t pool)
{
    if (pool == POOL)
        ((void (*)(void *, uint32_t))0x5f58b0u)(state.tasks, TASK_COUNT);
}

void r5_cp_pool_release(uintptr_t pool, uintptr_t task)
{
    if (pool == POOL) {
        uint8_t *entry = slot(task);
        if (entry)
            __atomic_store_n(entry, 0, __ATOMIC_RELEASE);
    }
    ((void (*)(uintptr_t, uintptr_t))0xae0993u)(pool, task);
}

void *r5_cp_jpeg_copy(void *destination, const void *source, uint32_t bytes, uintptr_t task)
{
    void *result = ((void *(*)(void *, const void *, uint32_t))0x5f51bcu)(destination, source, bytes);
    uint32_t id = task_id(task);
    uintptr_t offset = (uintptr_t)source - task;
    if (custom(id) && jpeg(task) && bytes == sizeof(R5AspectGeometry)) {
        if (offset == MAIN_ROI)
            jpeg_main_crop(task, id, destination);
        else if (offset == SCN_ROI) {
            R5AspectGeometry main;
            if (jpeg_main_crop(task, id, &main))
                r5_aspect_crop(id, source, 1, 0, destination);
        }
    }
    return result;
}

void r5_cp_thumbnail_clear(uint8_t *destination, uint32_t bytes, uintptr_t task)
{
    ((void (*)(void *, uint32_t))0x5f58b0u)(destination, bytes);
    uint32_t id = task_id(task);
    R5AspectGeometry main;
    if (custom(id) && jpeg(task) && bytes == 0x20 && !(read32(task + 0x3c) & 4u) &&
        jpeg_main_crop(task, id, &main))
        r5_aspect_thumbnail(id, (uint16_t *)(destination - 0xbc), (uint16_t *)(destination - 0x34));
}

void r5_cp_notify_jpeg(uint16_t *dimensions, uintptr_t task, uint32_t format)
{
    uint32_t id = task_id(task);
    if (!custom(id) || format != 1)
        return;
    R5AspectGeometry result;
    const R5AspectGeometry *source = (const R5AspectGeometry *)(task + MAIN_ROI);
    if (source->width == dimensions[0] && source->height == dimensions[1] &&
        jpeg_main_crop(task, id, &result)) {
        dimensions[0] = result.width;
        dimensions[1] = result.height;
    }
}

void *r5_cp_heif_copy(uint8_t *destination, const void *source, uint32_t bytes, uintptr_t task)
{
    void *result = ((void *(*)(void *, const void *, uint32_t))0x5f53fcu)(destination, source, bytes);
    uint32_t id = task_id(task);
    if (custom(id) && bytes == 0x25c && (uintptr_t)source == task + ENCODE_UNION)
        r5_aspect_heif_request(id, destination - 0x1e8, R5_ASPECT_NOTIFY_BYTES);
    return result;
}
