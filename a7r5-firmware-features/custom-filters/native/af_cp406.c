/* 来源：锁定4.06 AP基底转换表与CP原通知/消费窗口。 */
#include "af_cp406.h"

static const size_t fields[AF_PARAMETERS] = {
    0xa44u, 0xa46u, 0xa45u, 0xa47u, 0xa48u, 0xd2eu, 0xd2fu, 0xd30u
};

static int wire(const AfPreset *preset) {
    static const uint8_t ordinary[10] = {0,3,2,1,16,15,17,18,5,13};
    if (af_validate(preset) != AF_OK || preset->kind != 0) return -1;
    return preset->base <= 9 ? ordinary[preset->base] :
           preset->base == 17 ? 19 : 20;
}

static int range(const void *pointer, size_t size) {
    return pointer && size >= AF_CP406_PREFIX_BYTES &&
           (uintptr_t)pointer <= UINTPTR_MAX - size;
}

int af_cp406_overlay(const AfPreset *preset, const void *source, void *destination,
                     size_t size) {
    int8_t parameters[AF_PARAMETERS];
    const uint8_t *input = source;
    uint8_t *output = destination;
    int base = wire(preset);
    if (base < 0 || !range(source, size) || !range(destination, size)) return AF_INVALID;
    if ((uintptr_t)source < (uintptr_t)destination + size &&
        (uintptr_t)destination < (uintptr_t)source + size) return AF_INVALID;
    for (size_t i = 0; i < AF_PARAMETERS; ++i) parameters[i] = preset->params[i];
    for (size_t i = 0; i < AF_CP406_PREFIX_BYTES; ++i) output[i] = input[i];
    output[0xa40] = (uint8_t)base;
    output[0xa41] = output[0xa42] = output[0xa43] = 0;
    for (size_t i = 0; i < AF_PARAMETERS; ++i) output[fields[i]] = (uint8_t)parameters[i];
    return AF_OK;
}

int af_cp406_matches(const AfPreset *preset, const void *snapshot, size_t size) {
    const uint8_t *bytes = snapshot;
    int base = wire(preset);
    if (base < 0 || !range(snapshot, size)) return AF_INVALID;
    if (bytes[0xa40] != base || bytes[0xa41] || bytes[0xa42] || bytes[0xa43]) return AF_STALE;
    for (size_t i = 0; i < AF_PARAMETERS; ++i)
        if (bytes[fields[i]] != (uint8_t)preset->params[i]) return AF_STALE;
    return AF_OK;
}
