/* 显式介质目录的有界只读入口；不探测、挂载或打开任何设备路径。 */
#ifndef AF_MEDIA_H
#define AF_MEDIA_H
#include "af_grid.h"
#define AF_MEDIA_MAX 64u
#define AF_MEDIA_SCAN_MAX 4096u
#define AF_MEDIA_NAME_BYTES 128u
#define AF_MEDIA_SOURCE_MAX (4u*1024u*1024u)
#define AF_MEDIA_CAPACITY (-9)
enum AfMediaKind { AF_MEDIA_UNKNOWN=0, AF_MEDIA_CUBE=1, AF_MEDIA_PREPARED=2 };
/* 共享后缀契约；仅分类，不代替完整文件名或内容校验。UI不必链接文件I/O模块。 */
static inline unsigned af_media_kind(const char *name,size_t n){
    const char *end;size_t bytes;
    /* 超长候选也须识别后缀，再由各调用方明确拒绝非法名称，不能静默忽略。 */
    if(!name)return AF_MEDIA_UNKNOWN;
    for(unsigned kind=AF_MEDIA_CUBE;kind<=AF_MEDIA_PREPARED;++kind){
        end=kind==AF_MEDIA_CUBE?".cube":".a7filter";bytes=kind==AF_MEDIA_CUBE?5u:9u;
        if(n<=bytes)continue;
        size_t i=0;for(;i<bytes;++i){unsigned c=(uint8_t)name[n-bytes+i];
            if(c>='A'&&c<='Z')c+=32;
            if(c!=(unsigned)(uint8_t)end[i])break;}
        if(i==bytes)return kind;
    }
    return AF_MEDIA_UNKNOWN;
}
typedef struct {
    char name[AF_MEDIA_NAME_BYTES];
    uint64_t device,inode,size;
    int64_t mtime,nanoseconds;
} AfMediaEntry;
typedef struct {
    uint64_t generation,device,inode;
    uint32_t count;
    AfMediaEntry entries[AF_MEDIA_MAX];
} AfMediaList;
typedef struct {uint32_t bytes;uint8_t sha256[32];} AfMediaSource;
/* 原厂Fsys等非POSIX服务保持独立上下文，不将原生句柄转换为fd。
 * context及函数由单一UI拥有者固定到任务结束；版本不表示物理介质代号。 */
#define AF_MEDIA_PROVIDER_VERSION 1u
typedef struct {
    uint32_t version,bytes;
    void *context;
    int (*scan)(void *,uint64_t,AfMediaList *,AfMediaList *);
    int (*read)(void *,const AfMediaList *,uint32_t,void *,size_t,
                AfMediaSource *,AfGridProgress,void *);
} AfMediaProvider;
static inline int af_media_provider_valid(const AfMediaProvider *p){
    return p&&p->version==AF_MEDIA_PROVIDER_VERSION&&p->bytes==sizeof(*p)&&p->context&&p->scan&&p->read;
}
/* work可部分改变；output最后才发布。只列当前目录的普通.cube/.a7filter文件（忽略大小写），
 * 拒绝链接/非法名称/超预算，最多检查4096目录项，排序稳定；generation由单一拥有者单调分配。 */
int af_media_scan(int directory,uint64_t generation,AfMediaList *work,AfMediaList *output);
/* source缓冲为可丢弃工作区，失败可部分写入；metadata仅完整读/关文件/摘要后发布。
 * 列表绑定目录身份及文件身份/大小/纳秒修改时间，再独立打开逐字节复核以保护FAT粗时间戳；
 * 两次完整读取总量最多8MiB，不多分配源副本，之后转换只读这份副本。
 * source、metadata、list须独立，进度回调可取消，不执行任何写入。 */
int af_media_read(int directory,const AfMediaList *,uint32_t index,void *source,size_t capacity,
                  AfMediaSource *metadata,AfGridProgress,void *context);
#endif
