/* 原生Fsys只读提供者；句柄不是POSIX fd，不生成介质epoch或inode。 */
#ifndef AF_FSYS406_H
#define AF_FSYS406_H
#include "af_media.h"
#define AF_FSYS406_VERSION 1u
#define AF_FSYS406_SNAPSHOT_BYTES 0x150u
#define AF_FSYS406_RECORD_BYTES 0x70u
#define AF_FSYS406_FIND_BYTES 0xc28u
#define AF_FSYS406_LIBRARY_SPAN 0x1606e8u
/* 同包libInfraFsys真实ABI；绑定者须先核完整库SHA和真实导出来源。 */
typedef struct {
    int32_t (*open)(const char *,uint64_t *,uint32_t);
    int32_t (*read)(uint64_t,void *,int32_t);
    int32_t (*close)(uint64_t);
    int32_t (*find_first)(const char *,uint8_t,void *);
    int32_t (*find_next)(void *);
} AfFsys406Functions;
typedef int (*AfFsys406Snapshot)(void *,uint8_t output[AF_FSYS406_SNAPSHOT_BYTES]);
typedef struct {
    uint32_t version,bytes,slot,reserved;
    void *snapshot_context;
    AfFsys406Snapshot snapshot;
    AfFsys406Functions fsys;
    void *encoding_context;
    int (*utf8_policy)(void *);
} AfFsys406Binding;
typedef struct {
    uint8_t dates[22],attributes,reserved;
    /* 原短名卷的实际Open路径；空值表示沿用展示名称，不持外部指针。 */
    char alias[13];
} AfFsys406Details;
typedef struct {
    uint32_t initialized,busy;
    AfFsys406Binding binding;
    uint8_t record[AF_FSYS406_RECORD_BYTES];
    AfMediaList listing;
    AfFsys406Details details[AF_MEDIA_MAX];
} AfFsys406;
/* 调用者须先清零并保持驻留；已初始化状态不接受再次init，活动选择不得搬移。 */
size_t af_fsys406_bytes(void);
int af_fsys406_init(AfFsys406 *,const AfFsys406Binding *);
/* scan/read与AfMediaProvider接口相同；scan使用原PRO/LUT库根，仅槽0/1。
 * Find为调用者所有的私有状态，没有虚构FindClose。
 * 无utf8_policy时保留ASCII限制；有policy且每次操作前后通过时接受严格UTF-8。
 * policy只读核对原固定转换器，不改全局codepage；失败不发布列表或源信息。
 * generation是UI列表代号。device/inode/mtime/nanoseconds为0（不适用），
 * 原Find日期/属性只在context同代缓存比较，不转换成Unix时间或卡身份。 */
int af_fsys406_scan(void *,uint64_t,AfMediaList *,AfMediaList *);
int af_fsys406_read(void *,const AfMediaList *,uint32_t,void *,size_t,
                    AfMediaSource *,AfGridProgress,void *);
int af_fsys406_provider(AfFsys406 *,AfMediaProvider *);
/* 外层须先核同包完整库SHA/原ELF范围，证明本helper实际读取区权限和DSO驻留。
 * span必须是原ELF完整虚拟范围0x1606e8（不是708568B文件长度）。
 * 实际只读8个code窗口(RX)、GOT b9e68/8B(R)和module d4418/0x48(RW)。
 * 不声称遍历整个module或每个LOAD字节；不执行固件或写编码设置。 */
int af_fsys406_utf8_policy(uintptr_t lib_base,size_t exact_span);
#endif
