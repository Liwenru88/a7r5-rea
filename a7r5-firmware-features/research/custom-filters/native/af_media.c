#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#include "af_media.h"
#include "af_sha256.h"
#include "af_text.h"
#ifdef AF_TARGET_GLIBC225
#include "af_target_posix.h"
#else
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static size_t length(const char *s,size_t limit) {size_t n=0;while(n<limit && s[n])++n;return n;}
static int cube(const char *name,size_t n) {
    return af_media_kind(name,n)!=AF_MEDIA_UNKNOWN;
}
static int file_name(const char *name,size_t n) {
    /* 文件名独立于63B显示名；按UTF-8段验证，拒绝路径与控制字节。 */
    if(!n || n>=128)return 0;
    for(size_t i=0;i<n;++i)if(name[i]=='/' || name[i]=='\\' || (unsigned char)name[i]<32)return 0;
    size_t at=0;
    while(at<n){size_t end=at+63;if(end>n)end=n;while(end<n && ((unsigned char)name[end]&0xc0)==0x80)--end;
        if(end==at || !af_text_name_valid(name+at,end-at))return 0;at=end;}
    return 1;
}
static int less(const char *a,const char *b) {
    for(size_t i=0;i<128;++i){unsigned char x=a[i],y=b[i];if(x!=y)return x<y;if(!x)return 0;}return 0;
}
static int64_t nanos(const struct stat *s) {
#ifdef __APPLE__
    return s->st_mtimespec.tv_nsec;
#else
    return s->st_mtim.tv_nsec;
#endif
}
static int regular(const struct stat *s) {return S_ISREG(s->st_mode) && s->st_nlink==1 && s->st_size>0 && (uint64_t)s->st_size<=AF_MEDIA_SOURCE_MAX;}
static int same(const AfMediaEntry *e,const struct stat *s) {
    return regular(s) && e->device==(uint64_t)s->st_dev && e->inode==(uint64_t)s->st_ino &&
        e->size==(uint64_t)s->st_size && e->mtime==(int64_t)s->st_mtime && e->nanoseconds==nanos(s);
}
static int verify(int directory,const AfMediaEntry *e,const uint8_t *source,AfGridProgress progress,void *context){
    uint8_t block[1024];size_t at=0;struct stat s;int status=AF_OK;
    int fd=openat(directory,e->name,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);if(fd<0)return AF_STALE;
    if(fstat(fd,&s)||!same(e,&s))status=AF_STALE;
    while(!status&&at<e->size){size_t wanted=(size_t)e->size-at;if(wanted>sizeof(block))wanted=sizeof(block);
        ssize_t n=read(fd,block,wanted);if(n<0&&errno==EINTR)continue;if(n<=0){status=AF_IO;break;}
        for(ssize_t i=0;i<n;++i)if(block[i]!=source[at+(size_t)i]){status=AF_STALE;break;}
        at+=(size_t)n;
        if(!status&&progress&&progress(context,(uint32_t)e->size,(uint32_t)e->size))status=AF_GRID_CANCELLED;
    }
    if(!status){uint8_t extra;ssize_t n;do{n=read(fd,&extra,1);}while(n<0&&errno==EINTR);
        if(n!=0||fstat(fd,&s)||!same(e,&s))status=AF_STALE;}
    if(close(fd)&&!status)status=AF_IO;return status;
}
int af_media_scan(int directory,uint64_t generation,AfMediaList *work,AfMediaList *output) {
    struct stat root,s;struct dirent *entry;int fd,status=AF_OK;uint32_t visited=0;
    if(!generation || !apart(work,sizeof(*work),output,sizeof(*output)) || fstat(directory,&root) || !S_ISDIR(root.st_mode))return AF_INVALID;
    fd=openat(directory,".",O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(fd<0)return AF_IO;
    DIR *d=fdopendir(fd);if(!d){(void)close(fd);return AF_IO;}
    for(size_t i=0;i<sizeof(*work);++i)((uint8_t *)work)[i]=0;
    work->generation=generation;work->device=(uint64_t)root.st_dev;work->inode=(uint64_t)root.st_ino;
    for(;;){errno=0;entry=readdir(d);if(!entry){if(errno)status=AF_IO;break;}
        if(++visited>AF_MEDIA_SCAN_MAX){status=AF_MEDIA_CAPACITY;break;}
        size_t n=length(entry->d_name,256);if(!cube(entry->d_name,n))continue;
        if(!file_name(entry->d_name,n) || fstatat(directory,entry->d_name,&s,AT_SYMLINK_NOFOLLOW) || !regular(&s)){status=AF_INVALID;break;}
        if(work->count==AF_MEDIA_MAX){status=AF_MEDIA_CAPACITY;break;}
        AfMediaEntry *v=&work->entries[work->count++];
        for(size_t i=0;i<128;++i)v->name[i]=i<n?entry->d_name[i]:0;
        v->device=s.st_dev;v->inode=s.st_ino;v->size=(uint64_t)s.st_size;v->mtime=s.st_mtime;v->nanoseconds=nanos(&s);
    }
    if(closedir(d))status=AF_IO;
    if(status)return status;
    for(uint32_t i=1;i<work->count;++i){AfMediaEntry v=work->entries[i];uint32_t j=i;while(j && less(v.name,work->entries[j-1].name)){work->entries[j]=work->entries[j-1];--j;}work->entries[j]=v;}
    *output=*work;return AF_OK;
}
int af_media_read(int directory,const AfMediaList *list,uint32_t index,void *source,size_t cap,
                  AfMediaSource *metadata,AfGridProgress progress,void *context) {
    struct stat root,s;AfMediaSource next={0};size_t count=0;int status=AF_OK,fd;
    if(!list || !list->generation || list->count>AF_MEDIA_MAX || index>=list->count ||
       !apart(source,cap,list,sizeof(*list)) || !apart(metadata,sizeof(*metadata),list,sizeof(*list)) ||
       !apart(source,cap,metadata,sizeof(*metadata)))return AF_INVALID;
    const AfMediaEntry *e=&list->entries[index];size_t n=length(e->name,128);
    if(!file_name(e->name,n) || !cube(e->name,n) || !e->size || e->size>AF_MEDIA_SOURCE_MAX)return AF_INVALID;
    if(e->size>cap)return AF_MEDIA_CAPACITY;
    if(fstat(directory,&root) || !S_ISDIR(root.st_mode) || list->device!=(uint64_t)root.st_dev || list->inode!=(uint64_t)root.st_ino)return AF_STALE;
    if(progress && progress(context,0,(uint32_t)e->size))return AF_GRID_CANCELLED;
    fd=openat(directory,e->name,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);if(fd<0)return AF_STALE;
    if(fstat(fd,&s) || !same(e,&s))status=AF_STALE;
    while(!status && count<e->size){size_t wanted=(size_t)e->size-count;if(wanted>16384)wanted=16384;
        ssize_t got=read(fd,(uint8_t *)source+count,wanted);if(got<0 && errno==EINTR)continue;
        if(got<=0){status=AF_IO;break;}count+=(size_t)got;
        if(progress && progress(context,(uint32_t)count,(uint32_t)e->size))status=AF_GRID_CANCELLED;
    }
    if(!status){uint8_t extra;ssize_t got;do{got=read(fd,&extra,1);}while(got<0&&errno==EINTR);
        if(got!=0 || fstat(fd,&s) || !same(e,&s))status=AF_STALE;}
    if(close(fd) && !status)status=AF_IO;
    if(status)return status;
    /* FAT时间粒度较粗，同大小覆盖即使时间戳不变也不能发布混合内容。
     * 第二次独立打开逐字节复核，总I/O不超过8MiB；不增加另一份4MiB缓冲。 */
    uint8_t read_digest[32];
    if(af_sha256(source,count,read_digest))return AF_INVALID;
    status=verify(directory,e,source,progress,context);if(status)return status;
    if(progress && progress(context,(uint32_t)count,(uint32_t)count))return AF_GRID_CANCELLED;
    /* 复核后的进度回调也不能改变已验证区域；最后一次回调后再比较摘要。 */
    if(af_sha256(source,count,next.sha256))return AF_INVALID;
    for(unsigned i=0;i<32;++i)if(read_digest[i]!=next.sha256[i])return AF_STALE;
    next.bytes=(uint32_t)count;*metadata=next;return AF_OK;
}
