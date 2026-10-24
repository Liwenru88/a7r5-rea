/* 在普通文件中执行同一捕获核心；只替换Linux系统调用和主机不存在的身份元数据。 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
typedef long s64;
typedef unsigned long u64;
#define P(x) ((s64)(x))
#define RDONLY 0
#define WRONLY 1
#define RDWR 2
#define CREATE 64
#define EXCL 128
#define NOFOLLOW 32768
#define CLOEXEC 524288
#undef AT_FDCWD
#define AT_FDCWD -100
static char *capture_target, *capture_parent, capture_directory[4096], capture_path[4096];
static int fault, source_writes, source_reads;
static s64 sc(s64 n,s64 a,s64 b,s64 c,s64 d,s64 e,s64 f);
static int same(const char *a,const char *b,u64 n){return memcmp(a,b,n)==0;}
static s64 close_fd(s64 fd){return close((int)fd);}
static s64 open_file(const char *path,int flags){
    if(!strcmp(path,capture_target)&&(flags&3)!=RDONLY){source_writes++;return -EPERM;}
    int native=(flags&3)==WRONLY?O_WRONLY:(flags&3)==RDWR?O_RDWR:O_RDONLY;
    if(flags&CREATE)native|=O_CREAT;
    if(flags&EXCL)native|=O_EXCL;
    int fd=open(path,native|O_NOFOLLOW|O_CLOEXEC,0600);
    return fd<0?-errno:fd;
}
static int write_all(s64 fd,const char *raw,u64 n){
    while(n){ssize_t k=write((int)fd,raw,n);if(k<0&&errno==EINTR)continue;
        if(k<=0)return -1;raw+=k;n-=k;}return 0;
}
static s64 bounded(const char *path,char *raw,u64 cap){
    if(!strcmp(path,"/etc/ld.so.preload")&&cap>=512){memset(raw,'\n',512);return 512;}
    if(!strcmp(path,"/proc/meminfo")){
        const char *info="MemTotal: 280000 kB\nMemAvailable: 131072 kB\n";
        if(fault==2)info="MemAvailable: 65535 kB\n";
        if(fault==3)return -EIO;
        if(fault==4)info="MemTotal: 280000 kB\n";
        if(fault==5)info="MemAvailable: 131072 MB\n";
        if(fault==6)info="MemAvailable: 999999999999999999999999 kB\n";
        if(fault==7)info="MemAvailable: 65536 kB\n";
        size_t n=strlen(info);if(n>cap)return -EIO;memcpy(raw,info,n);return (s64)n;
    }
    return -ENOENT;
}
static u64 append(char *out,u64 at,const char *s){while(*s)out[at++]=*s++;return at;}
static u64 number(char *out,u64 at,s64 v){return at+(u64)sprintf(out+at,"%ld",v);}
#define CAPTURE_FIXTURE 1
#undef memcpy
#include "capture_gate.c"
static s64 sc(s64 n,s64 a,s64 b,s64 c,s64 d,s64 e,s64 f){
    (void)e;(void)f;
    if(n==174||n==175)return 0;
    if(n==78){memcpy((void *)c,"mnt:[1]",7);return 7;}
    if(n==44){s64 *fs=(s64 *)b;memset(fs,0,15*sizeof(*fs));fs[0]=0x01021994;fs[1]=4096;fs[4]=65536;return 0;}
    if(n==163){((u64 *)b)[0]=~0UL;return 0;}
    if(n==80){struct stat native;struct capture_stat *st=(void *)b;
        if(fstat((int)a,&native))return -errno;memset(st,0,sizeof(*st));st->mode=native.st_mode;st->size=native.st_size;return 0;}
    if(n==67){source_reads++;ssize_t k=pread((int)a,(void *)b,(size_t)c,(off_t)d);return k<0?-errno:k;}
    if(n==82)return fsync((int)a)?-errno:0;
    if(n==34){if(mkdir((char *)b,(mode_t)c))return -errno;
        if(fault==1){char path[8192];snprintf(path,sizeof(path),"%s.part-0",capture_path);
            int fd=open(path,O_CREAT|O_EXCL|O_WRONLY,0600);if(fd<0)return -errno;
            if(write_all(fd,"sentinel",8)||close(fd))return -EIO;}
        return 0;}
    return -ENOSYS;
}
int main(int argc,char **argv){
    if(argc<3)return 2;
    capture_target=argv[1];capture_parent=argv[2];fault=argc>3?atoi(argv[3]):0;
    snprintf(capture_directory,sizeof(capture_directory),"%s/capture",capture_parent);
    snprintf(capture_path,sizeof(capture_path),"%s/partition.bin",capture_directory);
    int code=native_task(1);printf("code=%d source_writes=%d source_reads=%d\n",code,source_writes,source_reads);return 0;
}
