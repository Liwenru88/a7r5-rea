#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#include "af_posix.h"
#ifdef AF_TARGET_GLIBC225
#include "af_target_posix.h"
#else
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdio.h>
#endif

size_t af_posix_bytes(void) { return sizeof(AfPosix); }
static int name(char out[20],uint32_t slot,uint32_t bank,int temp) {
    if (!slot || slot>AF_USERS || bank>1) return -1;
    return snprintf(out,20,"C%02u_%c.%s",slot,bank?'B':'A',temp?"new":"rec")<0?-1:0;
}
static int read_record(void *context,uint32_t slot,uint32_t bank,void *raw,size_t cap,size_t *bytes) {
    AfPosix *p=context;
    char path[20];
    struct stat st;
    size_t count=0;
    int fd,result=0;
    if (!p || p->directory<0 || !raw || !bytes || name(path,slot,bank,0)) return -1;
    fd=openat(p->directory,path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
    if (fd<0) return errno==ENOENT?1:-1;
    if (fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_nlink!=1 || st.st_size<0) result=-1;
    else if ((uintmax_t)st.st_size>cap) result=2;
    else {
        while (count<(size_t)st.st_size) {
            ssize_t n=read(fd,(uint8_t *)raw+count,(size_t)st.st_size-count);
            if (n<0 && errno==EINTR) continue;
            if (n<=0) { result=-1;break; }
            count+=(size_t)n;
        }
        if (!result) {
            uint8_t extra;
            ssize_t n;
            do { n=read(fd,&extra,1); } while (n<0 && errno==EINTR);
            if (n!=0) result=-1;
        }
    }
    if (close(fd)) result=-1;
    if (!result) *bytes=count;
    return result;
}
static int stage_record(void *context,uint32_t slot,uint32_t bank,const void *raw,size_t bytes) {
    AfPosix *p=context;
    char path[20];
    size_t count=0;
    if (!p || p->directory<0 || p->owned || !raw || !bytes || name(path,slot,bank,1)) return -1;
    p->stage_fd=openat(p->directory,path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if (p->stage_fd<0) return -1;
    p->owned=1;p->slot=slot;p->bank=bank;
    while (count<bytes) {
        ssize_t n=write(p->stage_fd,(const uint8_t *)raw+count,bytes-count);
        if (n<0 && errno==EINTR) continue;
        if (n<=0) return -1;
        count+=(size_t)n;
    }
    return 0;
}
static int owns(AfPosix *p,uint32_t slot,uint32_t bank) {
    return p && p->directory>=0 && p->owned && p->slot==slot && p->bank==bank;
}
static int sync_data(void *context,uint32_t slot,uint32_t bank) {
    AfPosix *p=context;
    int result;
    if (!owns(p,slot,bank) || p->stage_fd<0) return -1;
    result=fsync(p->stage_fd);
    if (close(p->stage_fd)) result=-1;
    p->stage_fd=-1;
    return result;
}
static int publish(void *context,uint32_t slot,uint32_t bank) {
    AfPosix *p=context;
    char from[20],to[20];
    struct stat st;
    if (!owns(p,slot,bank) || p->stage_fd>=0 || name(from,slot,bank,1) || name(to,slot,bank,0)) return -1;
    if (!fstatat(p->directory,to,&st,AT_SYMLINK_NOFOLLOW)) {
        if (!S_ISREG(st.st_mode) || st.st_nlink!=1) return -1;
    } else if (errno!=ENOENT) return -1;
    if (renameat(p->directory,from,p->directory,to)) return -1;
    p->owned=0;
    return 0;
}
static int sync_directory(void *context,uint32_t slot,uint32_t bank) {
    AfPosix *p=context;
    if (!p || p->directory<0 || !slot || slot>AF_USERS || bank>1) return -1;
    return fsync(p->directory);
}
static int discard(void *context,uint32_t slot,uint32_t bank) {
    AfPosix *p=context;
    char path[20];
    int result=0;
    if (!p || name(path,slot,bank,1)) return -1;
    if (!owns(p,slot,bank)) return 0;
    if (p->stage_fd>=0 && close(p->stage_fd)) result=-1;
    p->stage_fd=-1;
    if (unlinkat(p->directory,path,0)) result=-1;
    else p->owned=0;
    return result;
}
int af_posix_init(AfPosix *p,int fd,AfStoreIo *output) {
    struct stat st;
    AfPosix next;
    AfStoreIo io;
    if (!p || !output || fstat(fd,&st) || !S_ISDIR(st.st_mode) ||
        st.st_uid!=geteuid() || (st.st_mode&0022)) return -1;
    next.directory=fcntl(fd,F_DUPFD_CLOEXEC,0);
    if (next.directory<0) return -1;
    next.stage_fd=-1;next.owned=0;next.slot=0;next.bank=0;
    io.context=p;io.read=read_record;io.stage=stage_record;io.sync_data=sync_data;
    io.publish=publish;io.sync_directory=sync_directory;io.discard=discard;
    *p=next;*output=io;
    return 0;
}
int af_posix_close(AfPosix *p) {
    int result=0;
    if (!p || p->directory<0) return -1;
    if (p->stage_fd>=0 && close(p->stage_fd)) result=-1;
    p->stage_fd=-1;
    if (close(p->directory)) result=-1;
    p->directory=-1;
    return result;
}
