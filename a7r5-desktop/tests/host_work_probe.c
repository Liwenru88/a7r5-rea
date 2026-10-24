/* 用普通文件运行同一工作区诊断核心；所有源写入请求都被拒绝并计数。 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
typedef long s64;typedef unsigned long u64;
#define P(x) ((s64)(x))
#define RDONLY 0
#define WRONLY 1
#define CREATE 64
#define EXCL 128
#define NOFOLLOW 32768
#define CLOEXEC 524288
#undef AT_FDCWD
#define AT_FDCWD -100
static const char *source_path,*snapshot_path,*parent_path;
static int fault,source_fd=-1,source_writes,source_reads;
#define CAPTURE_CONTROL_PARENT parent_path
#define CAPTURE_CONTROL_DIR parent_path
static int same(const char *a,const char *b,u64 n){return !memcmp(a,b,n);}
static s64 open_file(const char *path,int flags){
    int is_source=!strcmp(path,source_path);
    if(is_source&&(flags&3)!=RDONLY){source_writes++;return -EPERM;}
    if(!strcmp(path,"/tmp/jiritsu"))path=parent_path;
    int native=(flags&3)==WRONLY?O_WRONLY:O_RDONLY;
    if(flags&CREATE)native|=O_CREAT;if(flags&EXCL)native|=O_EXCL;if(flags&16384)native|=O_DIRECTORY;
    int fd=open(path,native|O_NOFOLLOW|O_CLOEXEC,0600);
    if(is_source)source_fd=fd;return fd<0?-errno:fd;
}
static s64 close_fd(s64 fd){return close((int)fd);}
static int write_all(s64 fd,const char *raw,u64 n){
    while(n){ssize_t k=write((int)fd,raw,n);if(k<0&&errno==EINTR)continue;if(k<=0)return -1;raw+=k;n-=k;}return 0;
}
static s64 bounded(const char *path,char *raw,u64 cap){
    if(strcmp(path,"/proc/meminfo"))return -ENOENT;
    const char *text="MemAvailable: 65536 kB\n";size_t n=strlen(text);if(n>cap)return -EIO;memcpy(raw,text,n);return (s64)n;
}
static u64 append(char *out,u64 at,const char *s){while(*s)out[at++]=*s++;return at;}
static u64 number(char *out,u64 at,s64 n){return at+(u64)sprintf(out+at,"%ld",n);}
static s64 sc(s64,s64,s64,s64,s64,s64,s64);
#include "capture_control.h"
#define WORK_PROBE_FIXTURE 1
#undef memcpy
#include "work_probe.c"
static s64 sc(s64 n,s64 a,s64 b,s64 c,s64 d,s64 e,s64 f){
    (void)e;(void)f;
    if(n==44){s64 *fs=(void *)b;memset(fs,0,15*sizeof(*fs));fs[0]=fault==5?0x01021994:0x4d44;
        fs[1]=16384;fs[4]=321;fs[10]=fault==1?1:0;return 0;}
    if(n==80){struct stat raw;struct control_stat *st=(void *)b;if(fstat((int)a,&raw))return -errno;
        memset(st,0,sizeof(*st));st->mode=raw.st_mode;st->size=raw.st_size;return 0;}
    if(n==67){if(a!=source_fd)return -EPERM;source_reads++;
        ssize_t got=pread((int)a,(void *)b,(size_t)c,(off_t)d);
        if(got<0)return -errno;
        if(fault==2&&c==16384)return got-1;
        if((fault==3&&source_reads==3)||(fault==6&&source_reads==1))((char *)b)[0]^=1;
        if(fault==6&&source_reads==1)((char *)b)[13]=0;
        return got;}
    if(n==82)return fsync((int)a)?-errno:0;
    return -ENOSYS;
}
int main(int argc,char **argv){
    if(argc!=5)return 2;source_path=argv[1];snapshot_path=argv[2];parent_path=argv[3];fault=atoi(argv[4]);
    int code=native_task(1);printf("code=%d source_writes=%d source_reads=%d\n",code,source_writes,source_reads);return 0;
}
