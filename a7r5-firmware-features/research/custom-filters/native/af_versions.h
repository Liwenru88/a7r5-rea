/* 不可变版本/引用核心。串行事件线程使用；没有真实CP或拍摄确认。 */
#ifndef AF_VERSIONS_H
#define AF_VERSIONS_H
#include "af_document.h"
#define AF_VERSION_BANKS 3u
#define AF_VERSION_LEASES 64u
typedef struct { uint64_t version;uint32_t bank; } AfVersionToken;
typedef struct { uint64_t version,lease;uint32_t bank; } AfVersionLease;
typedef struct {
    uint8_t *raw;
    size_t used;
    uint64_t version;
    uint32_t references;
} AfVersionBank;
typedef struct {
    AfVersionBank banks[AF_VERSION_BANKS];
    AfVersionLease leases[AF_VERSION_LEASES];
    AfVersionToken pending;
    uint64_t next_version,next_lease;
    size_t capacity;
    uint32_t schema,active,initialized;
} AfVersions;
size_t af_versions_bytes(void);
/* 三块内存各至少capacity且互不重叠；生命周期长于所有引用；不得重初始化在用对象。 */
int af_versions_init(AfVersions *,void *,void *,void *,size_t,uint32_t schema);
int af_versions_stage(AfVersions *,const void *,size_t,AfVersionToken *);
/* 只有调用方实际收到成像侧对应版本回执后才能传succeeded=1。 */
int af_versions_finish(AfVersions *,const AfVersionToken *,int succeeded);
int af_versions_acquire(AfVersions *,AfVersionLease *);
int af_versions_view(const AfVersions *,const AfVersionLease *,const void **,size_t *);
int af_versions_release(AfVersions *,const AfVersionLease *);
#endif
