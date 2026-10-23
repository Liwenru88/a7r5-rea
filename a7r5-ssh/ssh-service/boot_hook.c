/* 自启候选：仅原厂bootin、root及明确启用标记匹配时派生后台启动器。 */
#include "../src/ns_abi.h"
#include "config.h"
extern int execve(const char *,char *const[],char *const[]);
extern int fstatfs(int,void *);

static int enabled(void){
    struct stat st;
    if(lstat(INSTALL_DIR "/enabled",&st)||!S_ISREG(st.st_mode)||st.st_uid||(st.st_mode&077))return 0;
    int fd=open(INSTALL_DIR "/enabled",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return 0;
    if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_uid||(st.st_mode&077)){close(fd);return 0;}
    char raw[64];ssize_t n=read(fd,raw,sizeof(raw));close(fd);
    const char expected[]=RUN_ID "\n";
    return n==(ssize_t)sizeof(expected)-1&&!memcmp(raw,expected,sizeof(expected)-1);
}

__attribute__((constructor)) static void start_at_boot(void){
    if(getuid()||geteuid())return;
    char command[512];int fd=open("/proc/self/cmdline",O_RDONLY|O_CLOEXEC);
    if(fd<0)return;ssize_t n=read(fd,command,sizeof(command));close(fd);
    if(n<(ssize_t)sizeof(BOOT_TRIGGER)||memcmp(command,BOOT_TRIGGER,sizeof(BOOT_TRIGGER))||!enabled())return;
    int pid=fork();if(pid!=0)return;
    if(setsid()<0)_exit(80);
    for(int i=3;i<1024;i++)close(i);
    fd=open("/dev/null",O_RDWR|O_CLOEXEC);
    if(fd<0)_exit(81);for(int i=0;i<3;i++)if(dup2(fd,i)<0)_exit(81);if(fd>2)close(fd);
    /* bootin不等待网络或RAM就绪；只有本后台子进程有界等待tmpfs。 */
    for(int i=0;i<300;i++){
        if(!enabled())_exit(82);
        fd=open("/tmp_network",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
        long fs[32];int ready=fd>=0&&!fstatfs(fd,fs)&&fs[0]==0x01021994;
        if(fd>=0)close(fd);
        if(ready){
            char *const argv[]={INSTALL_DIR "/ssh-service.arm64","--launch",0};
            char *const environment[]={"PATH=/bin:/usr/bin:/usr/sbin","LC_ALL=C","HOME=/root",0};
            execve(argv[0],argv,environment);_exit(83);
        }
        usleep(100000);
    }
    _exit(84);
}
