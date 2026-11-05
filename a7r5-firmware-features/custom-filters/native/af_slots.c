/* 可在AP/CP目标编译的有界状态核心；实际机身挂钩仍须通过研究门槛。 */
#include "af_slots.h"

static int same_preset(const AfPreset *a, const AfPreset *b) {
    size_t i;
    if (a->base != b->base || a->kind != b->kind) return 0;
    for (i = 0; i < AF_PARAMETERS; ++i)
        if (a->params[i] != b->params[i]) return 0;
    for (i = 0; i < 32; ++i)
        if (a->payload_sha256[i] != b->payload_sha256[i] ||
            a->lut_sha256[i] != b->lut_sha256[i]) return 0;
    return 1;
}

static int valid_slot(uint32_t slot) { return slot >= 1 && slot <= AF_USERS; }

static int valid_parameter(uint32_t parameter, int value) {
    static const int low[8] = {-9,-9,-9,0,-9,0,1,0};
    static const int high[8] = {9,9,9,9,9,9,5,9};
    return parameter < AF_PARAMETERS && value >= low[parameter] && value <= high[parameter];
}

static int any_byte(const uint8_t *value, size_t size) {
    size_t i;
    int result = 0;
    for (i = 0; i < size; ++i) result |= value[i];
    return result != 0;
}

size_t af_catalog_bytes(void) { return sizeof(AfCatalog); }

void af_catalog_init(AfCatalog *catalog) {
    size_t i;
    uint8_t *bytes = (uint8_t *)catalog;
    if (!catalog) return;
    for (i = 0; i < sizeof(*catalog); ++i) bytes[i] = 0;
}

int af_builtin_selector(uint32_t index) {
    static const int selectors[AF_BUILTINS] = {0,1,2,3,4,5,17,18,6,7,8,9};
    return index < AF_BUILTINS ? selectors[index] : -1;
}

int af_validate(const AfPreset *preset) {
    uint32_t i;
    int payload, lut;
    if (!preset || !((preset->base <= 9) || preset->base == 17 || preset->base == 18)) return AF_INVALID;
    if (preset->kind > 1) return AF_INVALID;
    for (i = 0; i < AF_PARAMETERS; ++i)
        if (!valid_parameter(i, preset->params[i])) return AF_INVALID;
    payload = any_byte(preset->payload_sha256, 32);
    lut = any_byte(preset->lut_sha256, 32);
    if (preset->kind == 0 ? (payload || lut) : !(payload && lut)) return AF_INVALID;
    return AF_OK;
}

int af_install(AfCatalog *catalog, uint32_t slot, const AfPreset *preset, int overwrite) {
    AfSlot *target;
    AfPreset copy;
    if (!catalog || !valid_slot(slot) || af_validate(preset) != AF_OK ||
        (overwrite != 0 && overwrite != 1)) return AF_INVALID;
    target = &catalog->slots[slot-1];
    if (target->pending.request) return AF_BUSY;
    if (target->present && !overwrite) return AF_EXISTS;
    if (target->saved_revision == UINT64_MAX) return AF_EXHAUSTED;
    copy = *preset;
    target->initial = copy;
    target->saved = copy;
    target->working = copy;
    ++target->saved_revision;
    target->present = 1;
    return AF_OK;
}

int af_read(const AfCatalog *catalog, uint32_t slot, int saved, AfPreset *output) {
    const AfSlot *target;
    if (!catalog || !valid_slot(slot) || !output || (saved != 0 && saved != 1)) return AF_INVALID;
    target = &catalog->slots[slot-1];
    if (!target->present) return AF_EMPTY;
    *output = saved ? target->saved : target->working;
    return AF_OK;
}

int af_catalog_load(AfCatalog *catalog, uint32_t slot, const AfPreset *initial,
                     const AfPreset *saved, uint64_t generation) {
    AfSlot next = {0};
    if (!catalog || !valid_slot(slot) || !generation ||
        af_validate(initial) != AF_OK || af_validate(saved) != AF_OK ||
        initial->kind != saved->kind || (initial->kind && initial->base != saved->base))
        return AF_INVALID;
    for (unsigned i = 0; i < 32; ++i)
        if (initial->payload_sha256[i] != saved->payload_sha256[i] ||
            initial->lut_sha256[i] != saved->lut_sha256[i]) return AF_INVALID;
    if (catalog->slots[slot-1].pending.request) return AF_BUSY;
    next.initial = *initial;next.saved = *saved;next.working = *saved;
    next.saved_revision = generation;next.present = 1;
    catalog->slots[slot-1] = next;
    return AF_OK;
}

int af_edit(AfCatalog *catalog, uint32_t slot, uint32_t parameter, int value) {
    AfSlot *target;
    if (!catalog || !valid_slot(slot) || !valid_parameter(parameter, value)) return AF_INVALID;
    target = &catalog->slots[slot-1];
    if (!target->present) return AF_EMPTY;
    target->working.params[parameter] = (int8_t)value;
    return AF_OK;
}

int af_edit_base(AfCatalog *catalog, uint32_t slot, uint32_t base) {
    AfSlot *target;
    if (!catalog || !valid_slot(slot) || !(base<=9 || base==17 || base==18)) return AF_INVALID;
    target=&catalog->slots[slot-1];
    if (!target->present) return AF_EMPTY;
    /* LUT载荷和误差报告绑定原基底，不能只改编号沿用旧结果。 */
    if (target->working.kind) return AF_INVALID;
    target->working.base=(uint8_t)base;
    return AF_OK;
}

int af_dirty(const AfCatalog *catalog, uint32_t slot) {
    const AfSlot *target;
    if (!catalog || !valid_slot(slot)) return AF_INVALID;
    target = &catalog->slots[slot-1];
    if (!target->present) return AF_EMPTY;
    return !same_preset(&target->working, &target->saved);
}

int af_restore(AfCatalog *catalog, uint32_t slot, int initial) {
    AfSlot *target;
    if (!catalog || !valid_slot(slot) || (initial != 0 && initial != 1)) return AF_INVALID;
    target = &catalog->slots[slot-1];
    if (!target->present) return AF_EMPTY;
    target->working = initial ? target->initial : target->saved;
    return AF_OK;
}

int af_begin_save(AfCatalog *catalog, uint32_t slot, AfSave *save) {
    AfSlot *target;
    if (!catalog || !valid_slot(slot) || !save) return AF_INVALID;
    target = &catalog->slots[slot-1];
    if (!target->present) return AF_EMPTY;
    if (target->pending.request) return AF_BUSY;
    if (target->saved_revision == UINT64_MAX || catalog->next_request == UINT64_MAX) return AF_EXHAUSTED;
    target->pending.snapshot = target->working;
    target->pending.expected_revision = target->saved_revision;
    target->pending.request = ++catalog->next_request;
    target->pending.slot = slot;
    *save = target->pending;
    return AF_OK;
}

int af_finish_save(AfCatalog *catalog, const AfSave *save, int write_succeeded) {
    AfSlot *target;
    if (!catalog || !save || !valid_slot(save->slot) || (write_succeeded != 0 && write_succeeded != 1)) return AF_INVALID;
    target = &catalog->slots[save->slot-1];
    if (!save->request || target->pending.request != save->request ||
        target->saved_revision != save->expected_revision ||
        !same_preset(&target->pending.snapshot, &save->snapshot)) return AF_STALE;
    if (write_succeeded) {
        target->saved = target->pending.snapshot;
        ++target->saved_revision;
    }
    target->pending.request = 0;
    return write_succeeded ? AF_OK : AF_IO;
}
