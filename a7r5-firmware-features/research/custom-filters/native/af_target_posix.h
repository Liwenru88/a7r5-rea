/* glibc 2.25／AArch64 LP64的最小存储ABI；只供显式目标构建，不使用宿主头布局。
 * 结构/常量依据bminor/glibc glibc-2.25的Linux generic stat/typesizes、
 * dirent、statvfs及aarch64 fcntl；来源缓存与实际导出见独立目标验证回执。 */
#ifndef AF_TARGET_POSIX_H
#define AF_TARGET_POSIX_H
#include <stddef.h>
#include <stdint.h>
#if !defined(__aarch64__) || !defined(__linux__) || __SIZEOF_LONG__!=8 || __SIZEOF_POINTER__!=8
#error "AF_TARGET_GLIBC225 requires Linux AArch64 LP64"
#endif
typedef long ssize_t;
typedef uint32_t uid_t;
struct timespec {long tv_sec,tv_nsec;};
struct stat {
    uint64_t st_dev,st_ino;
    uint32_t st_mode,st_nlink,st_uid,st_gid;
    uint64_t st_rdev,__pad1;
    int64_t st_size;
    int32_t st_blksize,__pad2;
    int64_t st_blocks;
    struct timespec st_atim,st_mtim,st_ctim;
    int32_t __reserved[2];
};
#define st_mtime st_mtim.tv_sec
struct dirent {
    uint64_t d_ino;
    int64_t d_off;
    uint16_t d_reclen;
    uint8_t d_type;
    char d_name[256];
};
typedef struct AfTargetDir DIR;
struct statvfs {
    unsigned long f_bsize,f_frsize,f_blocks,f_bfree,f_bavail,f_files,f_ffree,f_favail,
                  f_fsid,f_flag,f_namemax;
    int f_spare[6];
};
_Static_assert(sizeof(struct stat)==128 && offsetof(struct stat,st_mode)==16 &&
    offsetof(struct stat,st_size)==48 && offsetof(struct stat,st_blksize)==56 &&
    offsetof(struct stat,st_blocks)==64 && offsetof(struct stat,st_mtim)==88,"glibc225 stat ABI");
_Static_assert(sizeof(struct dirent)==280 && offsetof(struct dirent,d_name)==19,"glibc225 dirent ABI");
_Static_assert(sizeof(struct statvfs)==112 && offsetof(struct statvfs,f_bavail)==32 &&
    offsetof(struct statvfs,f_flag)==72,"glibc225 statvfs ABI");
#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2
#define O_CREAT 0100
#define O_EXCL 0200
#define O_TRUNC 01000
#define O_NONBLOCK 04000
#define O_DIRECTORY 040000
#define O_NOFOLLOW 0100000
#define O_CLOEXEC 02000000
#define F_DUPFD_CLOEXEC 1030
#define F_GETFD 1
#define FD_CLOEXEC 1
#define LOCK_EX 2
#define LOCK_NB 4
#define AT_FDCWD (-100)
#define AT_SYMLINK_NOFOLLOW 0x100
#define AT_REMOVEDIR 0x200
#define ST_RDONLY 1u
#define S_ISREG(mode) (((mode)&0170000u)==0100000u)
#define S_ISDIR(mode) (((mode)&0170000u)==0040000u)
#define ENOENT 2
#define EINTR 4
#define EEXIST 17
extern int *__errno_location(void);
#define errno (*__errno_location())
extern int __fxstat(int,int,struct stat *);
extern int __fxstatat(int,int,const char *,struct stat *,int);
/* 2.25没有现代fstat/fstatat动态符号；显式调用原版本0入口。 */
static inline int fstat(int fd,struct stat *st) {return __fxstat(0,fd,st);}
static inline int fstatat(int fd,const char *path,struct stat *st,int flags) {
    return __fxstatat(0,fd,path,st,flags);
}
extern int fstatvfs(int,struct statvfs *);
extern int open(const char *,int,...);
extern int openat(int,const char *,int,...);
extern int close(int);
extern ssize_t read(int,void *,size_t);
extern ssize_t write(int,const void *,size_t);
extern int fsync(int);
extern int fcntl(int,int,...);
extern int flock(int,int);
extern uid_t geteuid(void);
extern int renameat(int,const char *,int,const char *);
extern int unlinkat(int,const char *,int);
extern int mkdirat(int,const char *,uint32_t);
extern int symlinkat(const char *,int,const char *);
extern DIR *fdopendir(int);
extern struct dirent *readdir(DIR *);
extern int closedir(DIR *);
extern int snprintf(char *,size_t,const char *,...);
#endif
