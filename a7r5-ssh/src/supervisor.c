/* 有限寿命的前台 sshd 子进程管理；不修改账户、不设置开机自启。 */
#ifdef HOST_TEST
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>
#else
typedef unsigned long size_t;
typedef long ssize_t;
extern int fork(void),setpgid(int,int),waitpid(int,int *,int),kill(int,int),getpid(void);
extern int open(const char *,int,...),close(int),usleep(unsigned int),execve(const char *,char *const[],char *const[]);
extern ssize_t read(int,void *,size_t),write(int,const void *,size_t);
extern int prctl(int,...),snprintf(char *,size_t,const char *,...);
struct a7r5_statvfs { unsigned long bsize,frsize,blocks,bfree,bavail,files,ffree,favail,fsid,flag,namemax; int spare[6]; };
extern int statvfs(const char *,struct a7r5_statvfs *);
extern unsigned int getuid(void),geteuid(void);
extern void _exit(int);
extern void (*signal(int,void (*)(int)))(int);
extern int *__errno_location(void);
#define errno (*__errno_location())
#define O_RDONLY 0
#define O_NOFOLLOW 131072
#endif
#ifndef SSHD_EXE
#define SSHD_EXE "/usr/sbin/sshd"
#endif
static volatile int stopping;
static void stop_signal(int ignored) { (void)ignored; stopping=1; }
static int note(const char *text) { size_t n=0; while(text[n])n++; return write(1,text,n)==(ssize_t)n?0:-1; }
static int children(int terminate) {
#ifdef HOST_TEST
    (void)terminate; return 0;
#else
    char path[128],raw[2048];
    snprintf(path,sizeof(path),"/proc/self/task/%d/children",getpid());
    int fd=open(path,O_RDONLY|O_NOFOLLOW); if(fd<0)return -1;
    ssize_t n=read(fd,raw,sizeof(raw)-1); close(fd);
    if(n<0 || n==(ssize_t)sizeof(raw)-1)return -1;
    raw[n]=0; int count=0;
    for(long i=0;i<n;) {
        if(raw[i]==' ' || raw[i]=='\n'){i++;continue;}
        int pid=0;
        while(i<n && raw[i]>='0' && raw[i]<='9') {
            if(pid>100000000)return -1;
            pid=pid*10+raw[i++]-'0';
        }
        if(pid<=1 || (i<n && raw[i]!=' ' && raw[i]!='\n'))return -1;
        count++;
        /* 尚未 wait 的直属子进程不会在这里被系统复用 PID。 */
        if(terminate && kill(pid,terminate) && errno!=3)return -1;
    }
    return count;
#endif
}
int main(int argc,char **argv) {
#ifndef HOST_TEST
    if(argc==2) {
        const char *expected="--check-runtime"; int i=0;
        while(expected[i] && argv[1][i]==expected[i])i++;
        if(expected[i] || argv[1][i])return 64;
        struct a7r5_statvfs st;
        if(getuid()||geteuid()||statvfs("/tmp_network",&st)||st.bavail*st.frsize<1048576)return 65;
        if(prctl(36,1UL,0UL,0UL,0UL)||children(0)!=0)return 66;
        return note("RUNTIME_ROOT_SPACE_SUBREAPER_OK\n")?75:0;
    }
#endif
    if(argc!=3)return 64;
    int seconds=0;
    for(int i=0;argv[2][i];i++) {
        if(argv[2][i]<'0'||argv[2][i]>'9'||i>1)return 64;
        seconds=seconds*10+argv[2][i]-'0';
    }
    if(seconds<5||seconds>30)return 64;
#ifndef HOST_TEST
    if(getuid()||geteuid())return 65;
    if(prctl(36,1UL,0UL,0UL,0UL) || children(0)!=0)return 66;
#endif
    signal(15,stop_signal); signal(2,stop_signal); signal(1,stop_signal);
    int pid=fork(); if(pid<0)return 67;
    if(!pid) {
        if(setpgid(0,0))_exit(68);
        char *const args[]={SSHD_EXE,"-D","-e","-f",argv[1],0};
        char *const env[]={"PATH=/bin:/usr/bin:/usr/sbin","LC_ALL=C",0};
        execve(SSHD_EXE,args,env); _exit(69);
    }
    (void)setpgid(pid,pid);
    note("SUPERVISOR_SPAWNED\n");
    int status=0,reaped=0,unexpected=0;
    for(int i=0;i<seconds*10 && !stopping;i++) {
        int got=waitpid(pid,&status,1);
        if(got==pid){reaped=1;unexpected=1;break;}
        if(got<0){unexpected=1;break;}
        usleep(100000);
    }
    if(!reaped) {
        /* pid 是未回收的本次直接子进程，不按名字搜索或使用历史 PID。 */
        if(kill(-pid,15) && errno!=3)return 70;
        for(int i=0;i<20;i++) {
            int got=waitpid(pid,&status,1);
            if(got==pid){reaped=1;break;}
            usleep(100000);
        }
        if(!reaped) {
            if(kill(-pid,9)&&errno!=3)return 70;
            for(int i=0;i<20;i++) {
                if(waitpid(pid,&status,1)==pid){reaped=1;break;}
                usleep(100000);
            }
            if(!reaped)return 71;
        }
    }
    /* Linux 子收割器接管脱离原进程组的会话，逐个回收其直属后代。 */
    for(int i=0;i<40;i++) {
        int signal_no=i<20?15:9;
        if(children(signal_no)<0)return 72;
        while(waitpid(-1,&status,1)>0){}
        int remain=children(0); if(remain<0)return 72;
        if(!remain){note("SUPERVISOR_STOPPED_NO_OWNED_CHILDREN\n");return unexpected?73:0;}
        usleep(100000);
    }
    note("SUPERVISOR_CLEANUP_UNCONFIRMED\n"); return 74;
}
