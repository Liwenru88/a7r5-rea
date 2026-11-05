/* 编辑目录与存储事务的联动；保存回执与成像回执始终分开。 */
#ifndef AF_PERSIST_H
#define AF_PERSIST_H
#include "af_store.h"
enum AfPersistResult { AF_PERSIST_BUSY=-10, AF_PERSIST_EXISTS=-11, AF_PERSIST_EMPTY=-12 };
/* 调用方串行持有catalog和store。除save期间允许af_edit外，后端不得重入目录操作。
 * replace/copy需调用方明确overwrite；load显式丢弃工作值，不能作为自动重试。
 * 本模块不更新原厂显示，也不确认CP应用；实际菜单须分别等待两类回执。 */
int af_persist_load(AfCatalog *,AfStore *,const AfStoreIo *,const AfStoreBuffers *,int allow_empty);
int af_persist_replace(AfCatalog *,AfStore *,const AfStoreIo *,const AfStoreBuffers *,const AfDocument *,int overwrite);
int af_persist_save(AfCatalog *,AfStore *,const AfStoreIo *,const AfStoreBuffers *);
int af_persist_clear(AfCatalog *,AfStore *,const AfStoreIo *,const AfStoreBuffers *);
/* 重命名只改变名称/保存代号，保留initial/saved和未保存working。
 * name须为独立外部输入，不能借用会被本次恢复覆盖的存储缓冲。 */
int af_persist_rename(AfCatalog *,AfStore *,const AfStoreIo *,const AfStoreBuffers *,const char *,size_t);
/* working=0导出已保存参数，=1导出工作值；始终包含完整成像副本。
 * 只返回AFD1字节，不写SD；输出/计数须与全部目录/存储输入独立。
 * 容量不足返回AF_STORE_CAPACITY；失败不发布输出/计数。 */
int af_persist_export(AfCatalog *,AfStore *,const AfStoreIo *,const AfStoreBuffers *,
                       int working,void *,size_t,size_t *);
/* 另存保留源initial及报告基准，将源working存为目标saved；源目录不变。 */
int af_persist_copy(AfCatalog *,AfStore *source,AfStore *target,
                    const AfStoreIo *source_io,const AfStoreIo *target_io,
                    const AfStoreBuffers *,const char *name,size_t name_bytes,int overwrite);
#endif
