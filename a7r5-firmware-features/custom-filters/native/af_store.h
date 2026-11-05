/* 串行双副本事务。只通过显式回调访问后端，不假设机身路径或持久化能力。 */
#ifndef AF_STORE_H
#define AF_STORE_H
#include "af_document.h"
#include "af_record.h"
enum AfStoreResult {
    AF_STORE_OK=0, AF_STORE_MISSING=1, AF_STORE_INVALID=-1,
    AF_STORE_IO=-2, AF_STORE_CORRUPT=-3, AF_STORE_UNSUPPORTED=-4,
    AF_STORE_CONFLICT=-5, AF_STORE_STALE=-6, AF_STORE_UNCERTAIN=-7,
    AF_STORE_EXHAUSTED=-8, AF_STORE_CAPACITY=-9
};
/* read：0完整读取；1不存在；2容量不足；负数I/O错误。其他阶段仅0成功。
 * stage不得发布；sync_data须同时确认同步和关闭；publish失败也可能已发布。
 * discard仅清理本事务创建且尚未发布的暂存文件，不碰既有残留文件。 */
typedef struct {
    void *context;
    int (*read)(void *,uint32_t,uint32_t,void *,size_t,size_t *);
    int (*stage)(void *,uint32_t,uint32_t,const void *,size_t);
    int (*sync_data)(void *,uint32_t,uint32_t);
    int (*publish)(void *,uint32_t,uint32_t);
    int (*sync_directory)(void *,uint32_t,uint32_t);
    int (*discard)(void *,uint32_t,uint32_t);
} AfStoreIo;
typedef struct { uint8_t *a,*b,*next;size_t capacity; } AfStoreBuffers;
typedef struct {
    uint32_t slot,schema,bank,ready,uncertain;
    size_t max_payload;
    uint64_t generation;
    uint8_t digest[32];
} AfStore;
size_t af_store_bytes(void);
int af_store_init(AfStore *,uint32_t slot,uint32_t schema,size_t max_payload);
uint64_t af_store_generation(const AfStore *);
/* 只有两份都不存在且allow_empty=1才允许创建；不自动初始化坏槽。
 * output借用a/b内存，下次事务之前使用；失败不发布output。
 * 恢复失败将冻结后续提交，直到一次成功恢复；UNCERTAIN也只能恢复解除。 */
int af_store_recover(AfStore *,const AfStoreIo *,const AfStoreBuffers *,int allow_empty,AfDocument *);
/* document可借用当前恢复缓冲：先完整编码到next，再执行读前像。
 * 提交成功只更新AfStore，不确认目录编辑或CP生效，调用方分别处理。
 * 此模块不提供跨进程/线程锁，必须由唯一拥有者串行调用。 */
int af_store_commit(AfStore *,const AfStoreIo *,const AfStoreBuffers *,const AfDocument *);
/* 从最近成功恢复/提交的已验证缓冲取得文档，不执行新I/O。
 * 重新核对记录摘要/代号和完整格式；缓冲复用、未就绪或不确定均拒绝。
 * name/image借用a/b/next直到下一次I/O；不代表文件此后未被外部修改。
 * output须与store、缓冲描述符及三个缓冲独立，失败不发布。 */
int af_store_snapshot(const AfStore *,const AfStoreBuffers *,AfDocument *output);
#endif
