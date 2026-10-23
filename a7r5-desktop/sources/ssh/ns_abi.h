/* 目标为 Linux AArch64 / glibc 2.25；本机测试使用系统头。 */
#ifdef NS_HOST_TEST
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <signal.h>
#include <errno.h>
#include <time.h>
#include <dirent.h>
#include <sys/statvfs.h>
#include <poll.h>
#else
#include <stddef.h>
#include <stdint.h>
typedef long ssize_t;
struct timespec { long tv_sec,tv_nsec; };
struct pollfd { int fd; short events,revents; };
struct stat { unsigned long st_dev,st_ino; unsigned st_mode,st_nlink,st_uid,st_gid;
    unsigned long st_rdev,__pad1; long st_size; int st_blksize,__pad2; long st_blocks;
    long atime_s,atime_ns,mtime_s,mtime_ns,ctime_s,ctime_ns; unsigned unused[2]; };
_Static_assert(sizeof(struct stat)==128,"AArch64 stat 布局错误");
struct statvfs { unsigned long bsize,frsize,blocks,bfree,bavail,files,ffree,favail,fsid,flag,namemax; int spare[6]; };
struct dirent { unsigned long ino; long offset; unsigned short reclen; unsigned char type; char d_name[256]; };
typedef void DIR;
extern DIR *opendir(const char *);
extern struct dirent *readdir(DIR *);
extern int dirfd(DIR *),closedir(DIR *);
extern int open(const char *,int,...),close(int);
extern int openat(int,const char *,int,...),mkdirat(int,const char *,unsigned),renameat(int,const char *,int,const char *);
extern long syscall(long,...);
/* Linux 4.9 asm-generic：80=fstat，79=newfstatat；避免依赖glibc的内联stat包装。 */
static int fstat(int fd,struct stat *out){return (int)syscall(80L,fd,out);}
static int lstat(const char *path,struct stat *out){return (int)syscall(79L,-100,path,out,256);}
extern int mkdir(const char *,unsigned),fsync(int),rename(const char *,const char *),dup2(int,int),pipe(int *);
extern int fork(void),setsid(void),getpid(void),getppid(void),setpgid(int,int),waitpid(int,int *,int),kill(int,int);
extern unsigned getuid(void),geteuid(void);
extern ssize_t read(int,void *,size_t),write(int,const void *,size_t),readlink(const char *,char *,size_t);
extern int snprintf(char *,size_t,const char *,...),memcmp(const void *,const void *,size_t);
extern size_t strlen(const char *);
extern char *strstr(const char *,const char *),*strchr(const char *,int),*strrchr(const char *,int);
extern void *memcpy(void *,const void *,size_t),*memset(void *,int,size_t);
extern int strcmp(const char *,const char *),strncmp(const char *,const char *,size_t);
extern unsigned long long strtoull(const char *,char **,int);
extern int clock_gettime(int,struct timespec *),usleep(unsigned),poll(struct pollfd *,unsigned long,int);
extern int unshare(int),mount(const char *,const char *,const char *,unsigned long,const void *),prctl(int,...);
extern int statvfs(const char *,struct statvfs *);
extern void _exit(int);
extern int *__errno_location(void);
extern void (*signal(int,void (*)(int)))(int);
#define errno (*__errno_location())
#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2
#define O_CREAT 64
#define O_EXCL 128
#define O_NOFOLLOW 0100000
#define O_CLOEXEC 524288
#define O_DIRECTORY 040000
#define CLOCK_MONOTONIC 1
#define POLLIN 1
#define POLLHUP 16
#define WNOHANG 1
#define SIGTERM 15
#define SIGKILL 9
#define EINTR 4
#define ENOENT 2
#define ESRCH 3
#define S_ISREG(m) (((m)&0170000)==0100000)
#define S_ISDIR(m) (((m)&0170000)==0040000)
#endif
#include <stdint.h>
#define NEWNS 0x00020000
#define MS_RDONLY_P 1UL
#define MS_NOSUID_P 2UL
#define MS_NODEV_P 4UL
#define MS_BIND_P 4096UL
#define MS_REC_P 16384UL
#define MS_PRIVATE_P (1UL<<18)
#define MS_REMOUNT_P 32UL
