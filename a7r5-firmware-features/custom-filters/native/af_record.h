/* 记录封装与双副本恢复，无文件I/O。载荷语义与真实机内存储适配另行接入。 */
#ifndef AF_RECORD_H
#define AF_RECORD_H

#include <stddef.h>
#include <stdint.h>

#define AF_RECORD_HEADER 32u
#define AF_RECORD_VERSION 1u

enum AfRecordResult {
    AF_RECORD_OK = 0, AF_RECORD_INVALID = -1, AF_RECORD_CAPACITY = -2,
    AF_RECORD_UNSUPPORTED = -3, AF_RECORD_AMBIGUOUS = -4,
    AF_RECORD_EXHAUSTED = -5
};

typedef struct {
    uint32_t slot;
    uint64_t generation;
    const uint8_t *payload;
    size_t bytes;
} AfRecordView;

typedef struct {
    AfRecordView view;
    uint32_t bank;
} AfRecordChoice;

/* 所有输入、输出对象均须独立，禁止内存重叠。失败时不改变输出对象。
 * max_payload是调用者已批准的预算，不表示机内实际可用容量。
 * CRC仅用于意外损坏检测，不提供来源认证。 */
int af_record_encode(uint32_t slot, uint64_t generation, const void *payload,
                     size_t bytes, size_t max_payload, void *output,
                     size_t capacity, size_t *written);
/* 成功输出借用raw内存的视图；消费结束前必须保持raw有效且不可变。 */
int af_record_decode(const void *raw, size_t bytes, uint32_t expected_slot,
                     size_t max_payload, AfRecordView *output);
/* NULL且长度为0表示缺失副本。未知版本保守阻止回退，避免覆盖未来格式。
 * 同代不同载荷拒绝选主；两份均无效时不会自动初始化或宣布恢复成功。 */
int af_record_choose(const void *a, size_t a_bytes, const void *b, size_t b_bytes,
                     uint32_t slot, size_t max_payload, AfRecordChoice *output);
/* 只为已选有效记录计算另一副本和下一代号，不执行写入或确认持久化。
 * 调用者必须串行化同一槽位的读取、计划、写入及回读流程。 */
int af_record_plan_next(const AfRecordChoice *selected, uint32_t *bank,
                        uint64_t *generation);

#endif
