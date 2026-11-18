#include "af_record.h"

/* 逐字节编解码，避免主机对齐、端序和C结构填充进入持久化格式。 */
static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t get64(const uint8_t *p) {
    return (uint64_t)get32(p) | ((uint64_t)get32(p + 4) << 32);
}

static void put32(uint8_t *p, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i));
}

static void put64(uint8_t *p, uint64_t v) {
    put32(p, (uint32_t)v);
    put32(p + 4, (uint32_t)(v >> 32));
}

static uint32_t crc_step(uint32_t crc, uint8_t value) {
    crc ^= value;
    for (unsigned i = 0; i < 8; ++i)
        crc = (crc >> 1) ^ (UINT32_C(0xedb88320) & (0u - (crc & 1u)));
    return crc;
}

static uint32_t crc_payload(const uint8_t *p, size_t bytes) {
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < bytes; ++i) crc = crc_step(crc, p[i]);
    return ~crc;
}

static uint32_t crc_header(const uint8_t *p) {
    uint32_t crc = UINT32_MAX;
    /* 校验字段自身在计算时置零，包含所有保留字段。 */
    for (size_t i = 0; i < AF_RECORD_HEADER; ++i)
        crc = crc_step(crc, (i >= 24 && i < 28) ? 0 : p[i]);
    return ~crc;
}

static int valid_slot(uint32_t slot) { return slot >= 1 && slot <= 20; }

int af_record_encode(uint32_t slot, uint64_t generation, const void *payload,
                     size_t bytes, size_t max_payload, void *output,
                     size_t capacity, size_t *written) {
    if (!valid_slot(slot) || !generation || !payload || !bytes || !output || !written)
        return AF_RECORD_INVALID;
    if (bytes > max_payload || bytes > UINT32_MAX ||
        bytes > SIZE_MAX - AF_RECORD_HEADER || capacity < bytes + AF_RECORD_HEADER)
        return AF_RECORD_CAPACITY;
    const uint8_t *src = (const uint8_t *)payload;
    uint8_t *dst = (uint8_t *)output;
    uint32_t crc = crc_payload(src, bytes);
    for (size_t i = 0; i < AF_RECORD_HEADER; ++i) dst[i] = 0;
    dst[0] = 'A'; dst[1] = '7'; dst[2] = 'F'; dst[3] = '1';
    dst[4] = AF_RECORD_VERSION;
    dst[6] = (uint8_t)slot;
    put64(dst + 8, generation);
    put32(dst + 16, (uint32_t)bytes);
    put32(dst + 20, crc);
    put32(dst + 24, crc_header(dst));
    for (size_t i = 0; i < bytes; ++i) dst[AF_RECORD_HEADER + i] = src[i];
    *written = bytes + AF_RECORD_HEADER;
    return AF_RECORD_OK;
}

int af_record_decode(const void *raw, size_t bytes, uint32_t expected_slot,
                     size_t max_payload, AfRecordView *output) {
    if (!raw || bytes < AF_RECORD_HEADER || !valid_slot(expected_slot) || !output)
        return AF_RECORD_INVALID;
    const uint8_t *src = (const uint8_t *)raw;
    if (src[0] != 'A' || src[1] != '7' || src[2] != 'F' || src[3] != '1')
        return AF_RECORD_INVALID;
    /* 未知版本不按当前格式解释，避免把未来记录当坏文件覆盖。 */
    if (src[4] != AF_RECORD_VERSION || src[5] != 0) return AF_RECORD_UNSUPPORTED;
    if (src[6] != expected_slot || src[7] || get32(src + 28) ||
        get32(src + 24) != crc_header(src) || !get64(src + 8))
        return AF_RECORD_INVALID;
    uint32_t payload_bytes = get32(src + 16);
    if (!payload_bytes || payload_bytes > max_payload ||
        (size_t)payload_bytes != bytes - AF_RECORD_HEADER)
        return AF_RECORD_INVALID;
    if (get32(src + 20) != crc_payload(src + AF_RECORD_HEADER, payload_bytes))
        return AF_RECORD_INVALID;
    AfRecordView view = {0};
    view.slot = expected_slot;
    view.generation = get64(src + 8);
    view.payload = src + AF_RECORD_HEADER;
    view.bytes = payload_bytes;
    *output = view;
    return AF_RECORD_OK;
}

static int same_payload(const AfRecordView *a, const AfRecordView *b) {
    if (a->bytes != b->bytes) return 0;
    for (size_t i = 0; i < a->bytes; ++i)
        if (a->payload[i] != b->payload[i]) return 0;
    return 1;
}

int af_record_choose(const void *a, size_t a_bytes, const void *b, size_t b_bytes,
                     uint32_t slot, size_t max_payload, AfRecordChoice *output) {
    if (!output || !valid_slot(slot) || (!a && a_bytes) || (!b && b_bytes))
        return AF_RECORD_INVALID;
    AfRecordView av = {0}, bv = {0};
    int ar = af_record_decode(a, a_bytes, slot, max_payload, &av);
    int br = af_record_decode(b, b_bytes, slot, max_payload, &bv);
    if (ar == AF_RECORD_UNSUPPORTED || br == AF_RECORD_UNSUPPORTED)
        return AF_RECORD_UNSUPPORTED;
    if (ar != AF_RECORD_OK && br != AF_RECORD_OK) return AF_RECORD_INVALID;
    if (ar == AF_RECORD_OK && br == AF_RECORD_OK &&
        av.generation == bv.generation && !same_payload(&av, &bv))
        return AF_RECORD_AMBIGUOUS;
    AfRecordChoice choice = {0};
    if (ar == AF_RECORD_OK && (br != AF_RECORD_OK || av.generation >= bv.generation)) {
        choice.view = av;
        choice.bank = 0;
    } else {
        choice.view = bv;
        choice.bank = 1;
    }
    *output = choice;
    return AF_RECORD_OK;
}

int af_record_plan_next(const AfRecordChoice *selected, uint32_t *bank,
                        uint64_t *generation) {
    if (!selected || !bank || !generation || selected->bank > 1 ||
        !valid_slot(selected->view.slot) || !selected->view.generation ||
        !selected->view.payload || !selected->view.bytes)
        return AF_RECORD_INVALID;
    if (selected->view.generation == UINT64_MAX) return AF_RECORD_EXHAUSTED;
    *bank = selected->bank ^ 1u;
    *generation = selected->view.generation + 1;
    return AF_RECORD_OK;
}
