/* 仅网络程序的新一次加载触发；已有实例和失败残留均不自动重试。 */
#include "common.h"
#ifndef NET_FORK
#define NET_FORK fork
#endif
static int trigger(void){char raw[512];int fd=open(PROC_CMDLINE,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return 0;ssize_t n=read(fd,raw,sizeof(raw));close(fd);if(n<(ssize_t)sizeof(NET_TRIGGER)||memcmp(raw,NET_TRIGGER,sizeof(NET_TRIGGER)))return 0;n=readlink(PROC_EXE,raw,sizeof(raw));return n==(ssize_t)sizeof(NET_TRIGGER)-1&&!memcmp(raw,NET_TRIGGER,sizeof(NET_TRIGGER)-1);}
static int port_free(void){
    int fd=open(PROC_TCP,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return 0;
    int n=bounded(fd,net_buffer,sizeof(net_buffer)-1);close(fd);if(n<1){clear_buffer();return 0;}net_buffer[n]=0;
    char *line=strchr((char *)net_buffer,'\n');if(!line||!strstr((char *)net_buffer,"local_address")){clear_buffer();return 0;}
    while(*++line){char *end=strchr(line,'\n');if(!end){clear_buffer();return 0;}char *p=strchr(line,':');if(!p||p>end){clear_buffer();return 0;}p++;while(p<end&&*p==' ')p++;char *local=p;while(p<end&&*p!=' ')p++;if(p-local!=13||local[8]!=':'){clear_buffer();return 0;}while(p<end&&*p==' ')p++;while(p<end&&*p!=' ')p++;while(p<end&&*p==' ')p++;if(end-p<2){clear_buffer();return 0;}
        if(local[9]=='0'&&local[10]=='8'&&(local[11]=='A'||local[11]=='a')&&(local[12]=='E'||local[12]=='e')&&p[0]=='0'&&(p[1]=='A'||p[1]=='a')){clear_buffer();return 0;}line=end;
    }
    clear_buffer();return 1;
}
static int detach_fds(void){DIR *d=opendir("/proc/self/fd");if(!d)return -1;int own=dirfd(d),fds[256],count=0;struct dirent *entry;while((entry=readdir(d))){char *end;unsigned long long fd=strtoull(entry->d_name,&end,10);if(end==entry->d_name||*end||fd<=2||fd==(unsigned)own)continue;if(fd>1048576||count==256){closedir(d);return -1;}fds[count++]=(int)fd;}closedir(d);for(int i=0;i<count;i++)close(fds[i]);int fd=open("/dev/null",O_RDWR|O_CLOEXEC);if(fd<0)return -1;for(int i=0;i<3;i++)if(dup2(fd,i)<0)return -1;if(fd>2)close(fd);return 0;}
#ifndef NET_DETACH
#define NET_DETACH detach_fds
#endif
static void finish(int claim,const char *text,int code){store(claim,"result",text,strlen(text));close(claim);_exit(code);}
static void worker(void){
    if(setsid()<0||NET_DETACH())_exit(70);
    /* 只重置派生子进程，避免网络宿主忽略SIGCHLD导致启动器无法waitpid。 */
#ifndef SIGCHLD
#define SIGCHLD 17
#endif
    signal(SIGCHLD,0);
    int root=open(RAM_PARENT,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(!ram_dir(root)||!same_namespace()||!marker()){if(root>=0)close(root);_exit(71);}
    if(mkdirat(root,CLAIM_NAME,0700)){close(root);_exit(72);}
    int claim=openat(root,CLAIM_NAME,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);close(root);
    if(!root_dir(claim,0700))_exit(73);
    if(store(claim,"attempt",NET_ID "\n",sizeof(NET_ID)))_exit(74);
    /* 无论是健康实例、陈旧PID、失败结果还是空目录，均保留现有RAM现场。 */
    if(!path_absent(SERVICE_RAM))finish(claim,"EXISTING_RAM_REFUSED\n",75);
    if(!port_free())finish(claim,"PORT_OR_TABLE_REFUSED\n",76);
    int fd=verified_helper();if(fd<0)finish(claim,"HELPER_REFUSED\n",77);
#ifdef NET_BEFORE_FINAL
    NET_BEFORE_FINAL();
#endif
    if(!marker()||!same_namespace()||!path_absent(SERVICE_RAM)){close(fd);finish(claim,"FINAL_GATE_REFUSED\n",78);}
    if(store(claim,"launch-approved",HELPER_SHA "\n",sizeof(HELPER_SHA))){close(fd);_exit(79);}
    char *const argv[]={HELPER_PATH,"--launch",0};
    char *const env[]={"PATH=/bin:/usr/bin:/usr/sbin","LC_ALL=C","HOME=/root",0};
#ifdef NET_TEST_LAUNCH
    NET_TEST_LAUNCH(fd,argv,env);
#else
    syscall(281L,fd,"",argv,env,4096);
#endif
    close(fd);finish(claim,"EXEC_FAILED\n",80);
}
static void entry(void){
    int saved=errno;
    if(getuid()==NET_OWNER&&geteuid()==NET_OWNER&&trigger()&&same_namespace()&&marker()&&path_absent(CLAIM_PATH)){
        int root=open(RAM_PARENT,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
        int okay=ram_dir(root);if(root>=0)close(root);
        if(okay){int pid=NET_FORK();if(pid==0)worker();}
    }
    errno=saved;
}
#ifdef NET_TEST_ENTRY
int main(void){entry();return 0;}
#else
__attribute__((constructor)) static void init(void){entry();}
#endif
