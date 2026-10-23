/* 只绑定启动监督器持有的原始挂载视图；不接受外部传入PID。 */
#ifndef A7R5_ORIGIN_PROOF_H
#define A7R5_ORIGIN_PROOF_H
#include "ns_abi.h"
#include "config.h"
extern int fchmod(int,unsigned),fstatfs(int,void *),getgroups(int,unsigned *);
extern unsigned getgid(void),getegid(void),umask(unsigned);
extern int setgroups(unsigned long,const unsigned *);
extern int setns(int,int),fchdir(int),chroot(const char *),chdir(const char *),ioctl(int,unsigned long,...);
extern char *getenv(const char *);
static int origin_mount_fd(int fd){long fs[32];return fd>=0&&!fstatfs(fd,fs)&&fs[0]==0x6e736673;}
struct origin_proof {
    unsigned long magic; int pid,groups_count; unsigned creation_mask;
    unsigned long long start,mnt_dev,mnt_ino,root_dev,root_ino,caps[5];
    unsigned groups[64]; char run[33];
};
static int origin_ns=-1,origin_root=-1,origin_failure=0,origin_error=0;
static __attribute__((unused)) int exact_read(int fd,void *raw,size_t count){
    char *p=raw;size_t used=0;while(used<count){ssize_t n=read(fd,p+used,count-used);if(n<0&&errno==EINTR)continue;if(n<=0)return -1;used+=(size_t)n;}return 0;
}
static __attribute__((unused)) int origin_text(const char *path,char *raw,size_t count){
    int fd=open(path,O_RDONLY|O_CLOEXEC);if(fd<0)return -1;
    ssize_t n=read(fd,raw,count-1);char more;int ok=n>0&&read(fd,&more,1)==0;close(fd);if(!ok)return -1;raw[n]=0;return 0;
}
static __attribute__((unused)) unsigned long long process_start(int pid){
    char path[80],raw[4096];snprintf(path,sizeof(path),"/proc/%d/stat",pid);
    if(origin_text(path,raw,sizeof(raw)))return 0;
    char *p=strrchr(raw,')');if(!p||p[1]!=' '||p[2]=='Z'||p[2]=='X')return 0;p+=2;
    /* p从第3字段起；comm允许包含空格和右括号。 */
    for(int i=3;i<22;i++){p=strchr(p,' ');if(!p)return 0;while(*p==' ')p++;}
    char *end;unsigned long long value=strtoull(p,&end,10);return end==p||(*end!=' '&&*end!='\n')?0:value;
}
static __attribute__((unused)) int current_caps(unsigned long long out[5]){
    char raw[8192];const char *keys[]={"\nCapInh:\t","\nCapPrm:\t","\nCapEff:\t","\nCapBnd:\t","\nCapAmb:\t"};
    if(origin_text("/proc/self/status",raw,sizeof(raw)))return -1;
    for(int i=0;i<5;i++){char *p=strstr(raw,keys[i]),*end;if(!p)return -1;p+=strlen(keys[i]);out[i]=strtoull(p,&end,16);if(end==p||*end!='\n')return -1;}return 0;
}
static __attribute__((unused)) int origin_capture_for(int directory,int holder){
    struct origin_proof p;struct stat ns,root;memset(&p,0,sizeof(p));
    if(getuid()||geteuid()||getgid()||getegid())return -1;
    origin_ns=open("/proc/self/ns/mnt",O_RDONLY|O_CLOEXEC);origin_root=open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    if(origin_ns<0||origin_root<0||!origin_mount_fd(origin_ns)||fstat(origin_ns,&ns)||fstat(origin_root,&root))return -1;
    p.magic=0x413752354f524731UL;p.pid=holder;p.start=process_start(p.pid);
    if(holder!=getpid()){
        char path[96];struct stat other;int fd;snprintf(path,sizeof(path),"/proc/%d/ns/mnt",holder);fd=open(path,O_RDONLY|O_CLOEXEC);
        if(fd<0)return -1;int bad=fstat(fd,&other)||other.st_dev!=ns.st_dev||other.st_ino!=ns.st_ino;close(fd);if(bad)return -1;
        snprintf(path,sizeof(path),"/proc/%d/root",holder);fd=open(path,O_RDONLY|O_DIRECTORY|O_CLOEXEC);
        if(fd<0)return -1;bad=fstat(fd,&other)||other.st_dev!=root.st_dev||other.st_ino!=root.st_ino;close(fd);if(bad||process_start(holder)!=p.start)return -1;
    }
    p.mnt_dev=ns.st_dev;p.mnt_ino=ns.st_ino;p.root_dev=root.st_dev;p.root_ino=root.st_ino;
    p.creation_mask=umask(0);umask(p.creation_mask);p.groups_count=getgroups(64,p.groups);memcpy(p.run,RUN_ID,sizeof(RUN_ID));
    if(!p.start||p.groups_count<0||current_caps(p.caps))return -1;
    int fd=openat(directory,"origin.bin",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0400);
    if(fd<0)return -1;
    int failed=fchmod(fd,0400)||write(fd,&p,sizeof(p))!=(ssize_t)sizeof(p)||fsync(fd);if(close(fd))failed=1;return failed?-1:0;
}
static __attribute__((unused)) int origin_capture(int directory){return origin_capture_for(directory,getpid());}
static __attribute__((unused)) int origin_enter_from(const char *name){
    struct stat st;struct origin_proof p;long fs[32];unsigned groups[64];unsigned long long caps[5];
    int base=-1,dir=-1,fd=-1,ns=-1,root=-1,ok=0;char path[96];
    origin_failure=1;errno=0;
    if(getuid()||geteuid()||getgid()||getegid()||lstat("/tmp_network",&st)||!S_ISDIR(st.st_mode))goto done;
    origin_failure=2;errno=0;
    base=open("/tmp_network",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(base<0)goto done;
    dir=openat(base,name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(dir<0||fstat(dir,&st)||st.st_uid||(st.st_mode&07777)!=0700||fstatfs(dir,fs)||fs[0]!=0x01021994)goto done;
    origin_failure=3;errno=0;
    fd=openat(dir,"origin.bin",O_RDONLY|O_NOFOLLOW|O_CLOEXEC|04000);
    if(fd<0||fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_uid||(st.st_mode&07777)!=0400||st.st_nlink!=1||st.st_size!=(long)sizeof(p)||exact_read(fd,&p,sizeof(p)))goto done;
    origin_failure=4;errno=0;
    if(p.magic!=0x413752354f524731UL||memcmp(p.run,RUN_ID,sizeof(RUN_ID))||p.pid<=1||p.groups_count<0||p.groups_count>64||p.creation_mask>0777||!p.start||process_start(p.pid)!=p.start)goto done;
    origin_failure=5;errno=0;
    if(current_caps(caps)||memcmp(caps,p.caps,sizeof(caps)))goto done;
    /* 明确验证mount-only所需能力，不能在失败后退回认证视图执行。 */
    if((caps[2]&((1ULL<<21)|(1ULL<<18)))!=((1ULL<<21)|(1ULL<<18)))goto done;
    origin_failure=6;errno=0;
    snprintf(path,sizeof(path),"/proc/%d/ns/mnt",p.pid);ns=open(path,O_RDONLY|O_CLOEXEC);
    if(ns<0||!origin_mount_fd(ns)||fstat(ns,&st)||st.st_dev!=p.mnt_dev||st.st_ino!=p.mnt_ino)goto done;
    origin_failure=7;errno=0;
    snprintf(path,sizeof(path),"/proc/%d/root",p.pid);root=open(path,O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    if(root<0||fstat(root,&st)||st.st_dev!=p.root_dev||st.st_ino!=p.root_ino||process_start(p.pid)!=p.start)goto done;
    origin_failure=8;errno=0;
    if(setns(ns,NEWNS)||fchdir(root)||chroot(".")||chdir("/"))goto done;
    origin_failure=9;errno=0;
    close(ns);ns=open("/proc/self/ns/mnt",O_RDONLY|O_CLOEXEC);
    if(ns<0||fstat(ns,&st)||st.st_dev!=p.mnt_dev||st.st_ino!=p.mnt_ino)goto done;
    close(root);root=open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    if(root<0||fstat(root,&st)||st.st_dev!=p.root_dev||st.st_ino!=p.root_ino||process_start(p.pid)!=p.start||current_caps(caps)||memcmp(caps,p.caps,sizeof(caps)))goto done;
    origin_failure=10;errno=0;
    /* sshd的initgroups会增加主组；按可信原始任务记录恢复附加组，再逐字节核对。 */
    if(setgroups((unsigned long)p.groups_count,p.groups)||getgroups(64,groups)!=p.groups_count||memcmp(groups,p.groups,(size_t)p.groups_count*sizeof(unsigned)))goto done;
    umask(p.creation_mask);
    ok=1;origin_failure=0;
done:
    origin_error=errno;
    if(ns>=0)close(ns);if(root>=0)close(root);if(fd>=0)close(fd);if(dir>=0)close(dir);if(base>=0)close(base);return ok?0:-1;
}
static __attribute__((unused)) int origin_enter(void){return origin_enter_from(RAM_NAME);}
#endif
