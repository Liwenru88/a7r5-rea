#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#include "af_storage406.h"
#include "af_repository.h"
#ifdef AF_TARGET_GLIBC225
#include "af_target_posix.h"
extern unsigned int gnu_dev_major(uint64_t);
extern unsigned int gnu_dev_minor(uint64_t);
#else
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#ifdef __linux__
#include <sys/sysmacros.h>
#endif
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#endif

/* 只有宿主测试构建可以替换固定入口；生产构建不接受任何路径参数。 */
#ifdef AF_STORAGE406_TEST
extern int af_storage406_test_open(const char *,int);
extern int af_storage406_test_openat(int,const char *,int);
extern int af_storage406_test_fstatat(int,const char *,struct stat *,int);
extern int af_storage406_test_fstatvfs(int,struct statvfs *);
#define io_open af_storage406_test_open
#define io_openat af_storage406_test_openat
#define io_fstatat af_storage406_test_fstatat
#define io_fstatvfs af_storage406_test_fstatvfs
#else
#define io_open open
#define io_openat openat
#define io_fstatat fstatat
#define io_fstatvfs fstatvfs
#endif

enum { DIR_FLAGS=O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC,
       PROC_FLAGS=O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC,
       TEXT_MAX=262144, LINE_MAX406=1024 };
typedef struct {int fd;size_t at,end,total,limit;uint8_t block[512];} Reader;
typedef struct {uint32_t id,major,minor;} Mount;

static int same(const char *a,const char *b){
    for(size_t i=0;i<LINE_MAX406;++i){if(a[i]!=b[i])return 0;if(!a[i])return 1;}return 0;
}
static uint32_t dev_major(uint64_t d){
#ifdef AF_TARGET_GLIBC225
    return gnu_dev_major(d);
#else
    return (uint32_t)major((dev_t)d);
#endif
}
static uint32_t dev_minor(uint64_t d){
#ifdef AF_TARGET_GLIBC225
    return gnu_dev_minor(d);
#else
    return (uint32_t)minor((dev_t)d);
#endif
}
static int number(const char *p,uint32_t *out){
    uint32_t x=0;if(!*p)return 0;
    for(size_t n=0;p[n];++n){unsigned v=(unsigned)(uint8_t)p[n]-'0';
        if(v>9 || x>(UINT32_MAX-v)/10u)return 0;x=x*10u+v;}
    *out=x;return 1;
}
static int octets(Reader *r,char out[LINE_MAX406]){
    size_t n=0;
    for(;;){
        if(r->at==r->end){ssize_t got;
            do{got=read(r->fd,r->block,sizeof(r->block));}while(got<0&&errno==EINTR);
            if(got<0)return AF_STORAGE406_IO;
            if(!got)return n?AF_STORAGE406_FORMAT:0;
            if((size_t)got>r->limit-r->total)return AF_STORAGE406_FORMAT;
            r->total+=(size_t)got;r->at=0;r->end=(size_t)got;
        }
        uint8_t c=r->block[r->at++];
        if(c=='\n'){out[n]=0;return 1;}
        if(!c||c=='\r'||n+1==LINE_MAX406)return AF_STORAGE406_FORMAT;
        out[n++]=(char)c;
    }
}
static int proc_open(const char *path){
    int fd=io_open(path,PROC_FLAGS);struct stat st;
    if(fd<0)return -1;
    if(fstat(fd,&st)||!S_ISREG(st.st_mode)){(void)close(fd);return -1;}
    return fd;
}
static int fd_mount(int fd,uint32_t *id){
    char path[64],line[LINE_MAX406];
    int n=snprintf(path,sizeof(path),"/proc/self/fdinfo/%d",fd);
    if(n<0||(size_t)n>=sizeof(path))return AF_STORAGE406_INVALID;
    int input=proc_open(path);if(input<0)return AF_STORAGE406_IO;
    Reader r={0};r.fd=input;r.limit=8192;int status=0,found=0;
    while((status=octets(&r,line))==1){
        static const char key[]="mnt_id:";size_t k=0;
        while(k<sizeof(key)-1&&line[k]==key[k])++k;
        if(k!=sizeof(key)-1)continue;
        if(found){status=AF_STORAGE406_FORMAT;break;}
        const char *value=line+k;while(*value==' '||*value=='\t')++value;
        if(!number(value,id)||!*id){status=AF_STORAGE406_FORMAT;break;}found=1;
    }
    if(close(input)&&status>=0)status=AF_STORAGE406_IO;
    if(status<0)return status;
    return found?AF_STORAGE406_OK:AF_STORAGE406_FORMAT;
}
static int option(const char *s,const char *wanted){
    size_t begin=0;
    for(size_t i=0;;++i){if(s[i]!=','&&s[i])continue;
        size_t k=0;while(begin+k<i&&wanted[k]&&s[begin+k]==wanted[k])++k;
        if(begin+k==i&&!wanted[k])return 1;
        if(!s[i])return 0;begin=i+1;}
}
static int mount_line(char *line,uint32_t wanted,Mount *out){
    char *fields[64];size_t count=0;char *p=line;
    while(*p){if(count==64)return AF_STORAGE406_FORMAT;
        fields[count++]=p;while(*p&&*p!=' ')++p;
        if(*p){*p++=0;while(*p==' ')++p;}}
    if(count<10)return AF_STORAGE406_FORMAT;
    uint32_t id;if(!number(fields[0],&id))return AF_STORAGE406_FORMAT;
    if(id!=wanted)return 0;
    size_t sep=6;while(sep<count&&!same(fields[sep],"-"))++sep;
    if(sep+4!=count||!same(fields[3],"/")||!same(fields[4],"/setting")||
       !same(fields[sep+1],"vfat")||!same(fields[sep+2],"/dev/nflasha2"))return AF_STORAGE406_IDENTITY;
    if(!option(fields[5],"rw")||option(fields[5],"ro")||
       !option(fields[sep+3],"rw")||option(fields[sep+3],"ro"))return AF_STORAGE406_READONLY;
    char *colon=fields[2];while(*colon&&*colon!=':')++colon;
    if(!*colon)return AF_STORAGE406_FORMAT;*colon++=0;
    Mount next={id,0,0};
    if(!number(fields[2],&next.major)||!number(colon,&next.minor))return AF_STORAGE406_FORMAT;
    *out=next;return 1;
}
static int mount_info(uint32_t id,Mount *out){
    int fd=proc_open("/proc/self/mountinfo");if(fd<0)return AF_STORAGE406_IO;
    Reader r={0};r.fd=fd;r.limit=TEXT_MAX;
    char line[LINE_MAX406];int status=0,found=0;
    while((status=octets(&r,line))==1){
        int match=mount_line(line,id,out);if(match<0){status=match;break;}
        if(match&&found){status=AF_STORAGE406_FORMAT;break;}if(match)found=1;
    }
    if(close(fd)&&status>=0)status=AF_STORAGE406_IO;
    if(status<0)return status;
    return found?AF_STORAGE406_OK:AF_STORAGE406_IDENTITY;
}
static int private_dir(int fd,struct stat *st){
    return !fstat(fd,st)&&S_ISDIR(st->st_mode)&&st->st_uid==geteuid()&&!(st->st_mode&0022);
}
static int space(int fd){
    struct statvfs s;
    if(io_fstatvfs(fd,&s))return AF_STORAGE406_IO;
    if(s.f_flag&ST_RDONLY)return AF_STORAGE406_READONLY;
    uint64_t unit=s.f_frsize,blocks=s.f_bavail;
    uint64_t need=(uint64_t)AF_REPOSITORY_RESERVE+AF_DOCUMENT_MAX+AF_RECORD_HEADER;
    if(!unit||blocks>UINT64_MAX/unit)return AF_STORAGE406_INVALID;
    return blocks*unit>=need?AF_STORAGE406_OK:AF_STORAGE406_CAPACITY;
}
int af_storage406_open(int *out){
    if(!out)return AF_STORAGE406_INVALID;
    int root=-1,parent=-1,dev=-1,status=AF_STORAGE406_IO;
    struct stat initial,device,now;uint32_t id=0,id_now=0;Mount first={0},last={0};
    root=io_open("/",DIR_FLAGS);if(root<0)goto finish;
    parent=io_openat(root,"setting",DIR_FLAGS);if(parent<0)goto finish;
    if(!private_dir(parent,&initial)){status=AF_STORAGE406_IDENTITY;goto finish;}
    dev=io_openat(root,"dev",DIR_FLAGS);if(dev<0)goto finish;
    if(io_fstatat(dev,"nflasha2",&device,AT_SYMLINK_NOFOLLOW)||
       (device.st_mode&0170000u)!=0060000u){status=AF_STORAGE406_IDENTITY;goto finish;}
    if((status=fd_mount(parent,&id))||(status=mount_info(id,&first)))goto finish;
    if(first.major!=dev_major(initial.st_dev)||first.minor!=dev_minor(initial.st_dev)||
       first.major!=dev_major(device.st_rdev)||first.minor!=dev_minor(device.st_rdev)){
        status=AF_STORAGE406_IDENTITY;goto finish;}
    if((status=space(parent)))goto finish;
    /* 同一打开fd再核身份与挂载；不重新解析其他候选路径。 */
    if(!private_dir(parent,&now)||initial.st_dev!=now.st_dev||initial.st_ino!=now.st_ino){status=AF_STORAGE406_IDENTITY;goto finish;}
    if((status=fd_mount(parent,&id_now))||(status=mount_info(id_now,&last)))goto finish;
    if(id!=id_now||first.major!=last.major||first.minor!=last.minor){status=AF_STORAGE406_IDENTITY;goto finish;}
    if((status=space(parent)))goto finish;
    status=AF_STORAGE406_OK;
finish:
    if(dev>=0&&close(dev)&&!status)status=AF_STORAGE406_IO;
    if(root>=0&&close(root)&&!status)status=AF_STORAGE406_IO;
    if(!status){*out=parent;return AF_STORAGE406_OK;}
    if(parent>=0)(void)close(parent);
    return status;
}
