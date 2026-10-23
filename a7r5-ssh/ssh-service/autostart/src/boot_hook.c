/* 仅固定bootin的root进程触发；父进程不等待RAM、网络或SSH。 */
#include "ns_abi.h"
#include "ns_sha256.h"
#include "auto_config.h"
extern int fstatfs(int,void *);
#ifndef AS_OWNER
#define AS_OWNER 0U
#endif
#ifndef AS_FSTATFS
#define AS_FSTATFS fstatfs
#endif
#ifndef AS_WAIT_ROUNDS
#define AS_WAIT_ROUNDS 300
#endif
static int owned(int fd,int regular){struct stat st;return fd>=0&&!fstat(fd,&st)&&st.st_uid==AS_OWNER&&!(st.st_mode&022)&&(regular?(S_ISREG(st.st_mode)&&st.st_nlink==1):S_ISDIR(st.st_mode));}
static int network_root(int fd){struct stat st;if(fd<0||fstat(fd,&st)||!S_ISDIR(st.st_mode)||st.st_uid!=AS_OWNER)return 0;unsigned mode=st.st_mode&07777;return mode==0700||mode==0755||mode==01777;}
static int marked(void){int fd=open(AUTO_DIR "/enabled",O_RDONLY|O_NOFOLLOW|O_CLOEXEC
#ifndef NS_HOST_TEST
|04000
#else
|O_NONBLOCK
#endif
);if(fd<0)return 0;char data[64];ssize_t n=owned(fd,1)?read(fd,data,sizeof(data)):-1;close(fd);return n==(ssize_t)sizeof(AUTO_ID)&&!memcmp(data,AUTO_ID "\n",sizeof(AUTO_ID));}
static int trigger(void){char data[512];int fd=open(PROC_CMDLINE,O_RDONLY|O_CLOEXEC);if(fd<0)return 0;ssize_t n=read(fd,data,sizeof(data));close(fd);if(n<(ssize_t)sizeof(BOOT_TRIGGER)||memcmp(data,BOOT_TRIGGER,sizeof(BOOT_TRIGGER)))return 0;n=readlink(PROC_EXE,data,sizeof(data));return n==(ssize_t)sizeof(BOOT_TRIGGER)-1&&!memcmp(data,BOOT_TRIGGER,sizeof(BOOT_TRIGGER)-1);}
static int detach_fds(void){DIR *d=opendir("/proc/self/fd");if(!d)return -1;int own=dirfd(d),fds[256],count=0;struct dirent *entry;while((entry=readdir(d))){char *end;unsigned long long value=strtoull(entry->d_name,&end,10);if(end==entry->d_name||*end||value<=2||value==(unsigned)own)continue;if(value>1048576||count==256){closedir(d);return -1;}fds[count++]=(int)value;}closedir(d);for(int i=0;i<count;i++)close(fds[i]);int fd=open("/dev/null",O_RDWR|O_CLOEXEC);if(fd<0)return -1;for(int i=0;i<3;i++)if(dup2(fd,i)<0)return -1;if(fd>2)close(fd);return 0;}
static void worker(void){if(setsid()<0||detach_fds())_exit(70);int root=-1,claim=-1;
 for(int i=0;i<AS_WAIT_ROUNDS;i++){if(!marked())_exit(71);root=open(RAM_PARENT,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);long fs[32];memset(fs,0,sizeof(fs));int okay=network_root(root)&&!AS_FSTATFS(root,fs)&&fs[0]==0x01021994;if(okay)break;if(root>=0)close(root);root=-1;usleep(100000);}
 if(root<0)_exit(72);
 /* O_EXCL目录是本开机的唯一尝试凭证，失败也不删除或重试。 */
 if(mkdirat(root,CLAIM_NAME,0700)){close(root);_exit(73);}claim=openat(root,CLAIM_NAME,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);close(root);if(!owned(claim,0))_exit(74);
 int fd=open(AUTO_DIR "/ssh-service.arm64",O_RDONLY|O_NOFOLLOW|O_CLOEXEC
#ifndef NS_HOST_TEST
|04000
#else
|O_NONBLOCK
#endif
);struct stat st;char raw[65536],digest[65];int used=0,okay=owned(fd,1)&&!fstat(fd,&st)&&(st.st_mode&0100)&&st.st_size>0&&st.st_size<(long)sizeof(raw);
 while(okay&&used<(int)sizeof(raw)){ssize_t n=read(fd,raw+used,sizeof(raw)-(size_t)used);if(n<0&&errno==EINTR)continue;if(n<0){okay=0;break;}if(!n)break;used+=(int)n;}
 if(okay){sha_bytes(raw,(size_t)used,digest);okay=!strcmp(digest,HELPER_SHA)&&marked();}memset(raw,0,sizeof(raw));
 const char *event=okay?"helper-verified\n":"helper-refused\n";int log=openat(claim,"attempt",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(log<0||write(log,event,strlen(event))!=(ssize_t)strlen(event)||fsync(log))_exit(75);close(log);close(claim);if(!okay){if(fd>=0)close(fd);_exit(76);}
 char *const argv[]={AUTO_DIR "/ssh-service.arm64","--launch",0};char *const env[]={"PATH=/bin:/usr/bin:/usr/sbin","LC_ALL=C","HOME=/root",0};
 /* Linux execveat从已校验的描述符执行，避免再次按路径打开。 */
 syscall(281L,fd,"",argv,env,4096);_exit(77);
}
__attribute__((constructor)) static void boot(void){int saved=errno;if(getuid()==AS_OWNER&&geteuid()==AS_OWNER&&trigger()&&marked()){int pid=fork();if(pid==0)worker();}errno=saved;}
