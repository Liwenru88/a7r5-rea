/* 由libJit固定只读任务调用：只生成RAM证明，不启动后台进程。 */
#include "proof.h"
int main(int argc,char **argv){
    (void)argv;if(argc!=1||getuid()||geteuid())return 64;
    DIR *d=opendir("/proc");struct dirent *item;int holder=0,count=0;
    if(!d)return 65;
    while((item=readdir(d))){char *end,path[96],exe[512];unsigned long long pid=strtoull(item->d_name,&end,10);
        if(end==item->d_name||*end||pid<=1||pid>2147483647)continue;
        snprintf(path,sizeof(path),"/proc/%d/exe",(int)pid);ssize_t n=readlink(path,exe,sizeof(exe)-1);
        if(n<=0||n>=(ssize_t)sizeof(exe)-1)continue;exe[n]=0;
        if(!strcmp(exe,ORIGIN_HOLDER_EXE)){holder=(int)pid;count++;}
    }closedir(d);if(count!=1)return 66;
    struct stat st;long fs[32];
    if(lstat("/tmp_network",&st)||!S_ISDIR(st.st_mode))return 67;
    int base=open("/tmp_network",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(base<0||fstat(base,&st)||st.st_uid||fstatfs(base,fs)||fs[0]!=0x01021994)return 67;
    if(mkdirat(base,RAM_NAME "-bootstrap",0700))return 68;
    int dir=openat(base,RAM_NAME "-bootstrap",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);close(base);
    if(dir<0||fchmod(dir,0700)||origin_capture_for(dir,holder))return 69;
    close(dir);const char ok[]="A7R5_ORIGIN_ANCHOR " RUN_ID " SEALED original_view_matched=1 daemon_started=0\n";
    return write(1,ok,sizeof(ok)-1)==(ssize_t)sizeof(ok)-1?0:70;
}
