/* 仅绑定同版AP导入；不安装入口、不启动通信、不选择存储路径。 */
#ifndef AF_AP_REQUESTS_BINDING_H
#define AF_AP_REQUESTS_BINDING_H
#include "af_slots.h"
#define AF_AP_REQUESTS_SPAN 0x8e84000u
#define AF_AP_REQUESTS_IMPORTS 11u
#define AF_AP_REQUESTS_EXITS 4u
typedef struct {
    uint32_t version,bytes;
    uintptr_t base,mapped_bytes,application_init;
    uint8_t ap_sha256[32];
} AfApRequestsBinding;
typedef struct { uint32_t offset,words[4]; } AfApRequestsCheck;
extern const AfApRequestsCheck af_ap_requests_checks[16];
extern const uint32_t af_ap_requests_exit_offsets[AF_AP_REQUESTS_EXITS];
/* 纯准备只读取已映射的AP；来源全文摘要须由外层独立核验。失败不发布。 */
int af_ap_requests_resolve(const AfApRequestsBinding *,uintptr_t output[AF_AP_REQUESTS_IMPORTS]);
/* 装载者先完成4个单B出口、RELATIVE与RX恢复，再调用一次bind。 */
int af_ap_requests_bind(const AfApRequestsBinding *);
#endif
