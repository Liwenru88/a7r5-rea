/* 对同一原生清理核心执行普通文件测试；仅转换Linux系统调用ABI。 */
#include <dirent.h>
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
#define NOFOLLOW 32768
#define CLOEXEC 524288
#undef AT_FDCWD
#define AT_FDCWD -100
static char *root_path;
static int fault,deletions,write_opens;
static s64 sc(s64 n,s64 a,s64 b,s64 c,s64 d,s64 e,s64 f);
static int same(const char *a,const char *b,u64 n){return memcmp(a,b,n)==0;}
static s64 close_fd(s64 fd){return close((int)fd);}
static int native_flags(int flags){
    if(flags&3)write_opens++;
    return (flags&3)|O_NOFOLLOW|O_CLOEXEC|((flags&16384)?O_DIRECTORY:0);
}
static s64 open_file(const char *path,int flags){int fd=open(path,native_flags(flags));return fd<0?-errno:fd;}
static int write_all(s64 fd,const char *raw,u64 n){return write((int)fd,raw,n)==(ssize_t)n?0:-1;}
static s64 bounded(const char *path,char *raw,u64 cap){
    if(!strcmp(path,"/etc/ld.so.preload")&&cap>=512){memset(raw,'\n',512);return 512;}return -ENOENT;
}
static u64 append(char *out,u64 at,const char *s){while(*s)out[at++]=*s++;return at;}
static u64 number(char *out,u64 at,s64 v){return at+(u64)sprintf(out+at,"%ld",v);}
#undef memcpy
#include "capture_cleanup.c"
static void convert_stat(struct cleanup_stat *st,struct stat *native){
    memset(st,0,sizeof(*st));st->dev=native->st_dev;st->ino=native->st_ino;st->mode=native->st_mode;
    st->uid=0;st->nlink=native->st_nlink;st->size=native->st_size;
    if(fault==2&&(st->mode&0170000)==0100000)st->uid=501;
}
static s64 sc(s64 n,s64 a,s64 b,s64 c,s64 d,s64 e,s64 f){
    (void)e;(void)f;
    if(n==174||n==175)return 0;
    if(n==78){memcpy((void *)c,"mnt:[1]",7);return 7;}
    if(n==44){s64 *fs=(void *)b;memset(fs,0,15*sizeof(*fs));fs[0]=fault==1?0x4d44:0x01021994;return 0;}
    if(n==80){struct stat st;if(fstat((int)a,&st))return -errno;convert_stat((void *)b,&st);return 0;}
    if(n==79){struct stat st;
        if(fstatat((int)a,(char *)b,&st,AT_SYMLINK_NOFOLLOW))return -errno;
        convert_stat((void *)c,&st);return 0;}
    if(n==56){int fd=openat((int)a,(char *)b,native_flags((int)c));return fd<0?-errno:fd;}
    if(n==67){ssize_t got=pread((int)a,(void *)b,(size_t)c,(off_t)d);return got<0?-errno:got;}
    if(n==35){
        if(fault==3&&deletions==5)return -EIO;
        if(unlinkat((int)a,(char *)b,c?AT_REMOVEDIR:0))return -errno;
        deletions++;return 0;
    }
    if(n==61){
        DIR *dir=fdopendir(dup((int)a));if(!dir)return -errno;
        unsigned char *out=(void *)b;u64 used=0;struct dirent *entry;
        while((entry=readdir(dir))){
            size_t size=strlen(entry->d_name);unsigned len=(unsigned)((19+size+1+7)&~7UL);
            if(used+len>(u64)c){closedir(dir);return -EOVERFLOW;}
            memset(out+used,0,len);out[used+16]=len&255;out[used+17]=len>>8;
            memcpy(out+used+19,entry->d_name,size+1);used+=len;
        }
        closedir(dir);return (s64)used;
    }
    return -ENOSYS;
}
int main(int argc,char **argv){
    if(argc!=3)return 2;
    root_path=argv[1];fault=atoi(argv[2]);int code=native_task(1);
    printf("code=%d deletions=%d write_opens=%d\n",code,deletions,write_opens);return 0;
}
