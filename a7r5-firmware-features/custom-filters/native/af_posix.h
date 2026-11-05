/* 本地普通目录适配器。未安装到机身，不自行查找或打开任何路径。 */
#ifndef AF_POSIX_H
#define AF_POSIX_H
#include "af_store.h"
typedef struct {
    int directory,stage_fd,owned;
    uint32_t slot,bank;
} AfPosix;
size_t af_posix_bytes(void);
/* 复制调用者的目录fd；不接受普通文件/设备fd，拒绝非私有目录。
 * 只支持唯一拥有者；不提供多进程同步。close不删除遗留暂存文件。 */
int af_posix_init(AfPosix *,int directory_fd,AfStoreIo *);
int af_posix_close(AfPosix *);
#endif
