/* 固定路径的一次性自启控制器。目标构建为静态ELF，不执行任何相机应用。 */
#include "ns_abi.h"
#include "ns_sha256.h"
#include "auto_config.h"
#ifndef AS_OWNER
#define AS_OWNER 0U
#endif
#ifndef AS_SYNCFS
extern int syncfs(int);
#define AS_SYNCFS syncfs
#endif
#ifndef AS_FSTATFS
extern int fstatfs(int,void *);
#define AS_FSTATFS fstatfs
#endif
#ifndef AS_FSYNC
#define AS_FSYNC fsync
#endif
#ifndef AS_RENAME
#define AS_RENAME renameat
#endif
extern int unlinkat(int,const char *,int);
#ifndef NS_HOST_TEST
extern int fchmod(int,unsigned);
#endif
#ifdef NS_HOST_TEST
#define AS_NONBLOCK O_NONBLOCK
#define AS_REMOVEDIR AT_REMOVEDIR
#else
#define AS_NONBLOCK 04000
#define AS_REMOVEDIR 512
#endif
static unsigned char buffer[131072];
static int stage,dir=-1,etc=-1,stagefd=-1;
static const char neutral[512]={[0 ... 511]='\n'};
static void clear(void){volatile unsigned char *p=buffer;for(size_t i=0;i<sizeof(buffer);i++)p[i]=0;}
static int say(const char *s){size_t n=strlen(s);return write(1,s,n)==(ssize_t)n?0:-1;}
static int reject(void){char b[4];unsigned n=(unsigned)stage;int k=0;if(n>=100)b[k++]=(char)('0'+n/100);if(n>=10)b[k++]=(char)('0'+n/10%10);b[k++]=(char)('0'+n%10);say("A7R5_AUTO_REFUSED1 " AUTO_ID " stage=");write(1,b,(size_t)k);say("\n");clear();return stage?stage:99;}
static int root_file(int fd){struct stat st;return !fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_uid==AS_OWNER&&!(st.st_mode&022)&&st.st_nlink==1;}
static int directory(int fd,unsigned exact){struct stat st;return fd>=0&&!fstat(fd,&st)&&S_ISDIR(st.st_mode)&&st.st_uid==AS_OWNER&&!(st.st_mode&022)&&(!exact||(st.st_mode&07777)==exact);}
static int network_directory(int fd){struct stat st;if(fd<0||fstat(fd,&st)||!S_ISDIR(st.st_mode)||st.st_uid!=AS_OWNER)return 0;unsigned mode=st.st_mode&07777;return mode==0700||mode==0755||mode==01777;}
static int bounded(int fd,void *out,size_t cap){size_t n=0;while(n<cap){ssize_t k=read(fd,(char *)out+n,cap-n);if(k<0&&errno==EINTR)continue;if(k<0)return -1;if(!k)break;n+=(size_t)k;}char extra;ssize_t more=read(fd,&extra,1);return more==0?(int)n:-1;}
static int get(int parent,const char *name,void *raw,size_t cap){int fd=openat(parent,name,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|AS_NONBLOCK);if(fd<0)return -1;int n=root_file(fd)?bounded(fd,raw,cap):-1;if(close(fd))n=-1;return n;}
static int contents(int parent,const char *name,const void *raw,size_t n){int k=get(parent,name,buffer,sizeof(buffer));int ok=k==(int)n&&!memcmp(buffer,raw,n);clear();return ok;}
static int hashed(int parent,const char *name,const char *expected){int n=get(parent,name,buffer,sizeof(buffer));char sha[65];if(n<1){clear();return 0;}sha_bytes(buffer,(size_t)n,sha);clear();return !strcmp(sha,expected);}
static int absent(int parent,const char *name){int fd=openat(parent,name,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|AS_NONBLOCK);if(fd>=0){close(fd);return 0;}return errno==ENOENT;}
/* VFAT可能回报0755，仍要求owner可执行且禁止组/其他用户写入。 */
static int executable(int parent,const char *name){int fd=openat(parent,name,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);struct stat st;int ok=fd>=0&&!fchmod(fd,0700)&&root_file(fd)&&!fstat(fd,&st)&&(st.st_mode&0100);if(fd>=0)close(fd);return ok;}
static int readable_hook(void){int fd=openat(dir,"boot.so",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);struct stat st;int ok=fd>=0&&!fchmod(fd,0644)&&root_file(fd)&&!fstat(fd,&st)&&(st.st_mode&0004);if(fd>=0)close(fd);return ok;}
static int store(int parent,const char *name,const void *raw,size_t n){int fd=openat(parent,name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(fd<0)return -1;size_t used=0;int failed=!root_file(fd);while(!failed&&used<n){ssize_t k=write(fd,(const char *)raw+used,n-used);if(k<0&&errno==EINTR)continue;if(k<=0){failed=1;break;}used+=(size_t)k;}if(AS_FSYNC(fd))failed=1;if(close(fd))failed=1;return failed||!contents(parent,name,raw,n)?-1:0;}
static int copy(int from,const char *name,int to,const char *dest,const char *expected,size_t max){int n=get(from,name,buffer,sizeof(buffer));char sha[65];if(n<1||(size_t)n>max){clear();return -1;}if(expected){sha_bytes(buffer,(size_t)n,sha);if(strcmp(sha,expected)){clear();return -1;}}
 /* store的回读使用同一缓冲区，因此先用独立副本保存本次字节。 */
 unsigned char local[65536];if((size_t)n>sizeof(local)){clear();return -1;}memcpy(local,buffer,(size_t)n);clear();int rc=store(to,dest,local,(size_t)n);volatile unsigned char *p=local;for(size_t i=0;i<sizeof(local);i++)p[i]=0;return rc;}
static int pointer(void){int n=get(etc,"ld.so.preload",buffer,sizeof(buffer));int kind=n==512&&!memcmp(buffer,neutral,512)?0:n==(int)sizeof(PRELOAD_LINE)-1&&!memcmp(buffer,PRELOAD_LINE,sizeof(PRELOAD_LINE)-1)?1:-1;clear();return kind;}
static int open_private_source(void){int fd=open(PRIVATE_SOURCE,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);long fs[32];struct stat st;memset(fs,0,sizeof(fs));if(!directory(fd,0700)||AS_FSTATFS(fd,fs)||fs[0]!=0x01021994){if(fd>=0)close(fd);return -1;}int key=openat(fd,"host_ecdsa",O_RDONLY|O_NOFOLLOW|O_CLOEXEC|AS_NONBLOCK);int ok=key>=0&&!fstat(key,&st)&&root_file(key)&&(st.st_mode&07777)==0600&&st.st_size==505;if(key>=0)close(key);if(!ok){close(fd);return -1;}return fd;}
static int lock(void){return mkdirat(etc,".a7r5-preload-edit.lock",0700);}
static int unlock(void){return unlinkat(etc,".a7r5-preload-edit.lock",AS_REMOVEDIR);}
static int enable(void){
 stage=10;if(pointer()!=0||!absent(etc,AUTO_NAME))return reject();
 stage=11;stagefd=open(STAGE_DIR,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);long fs[32];memset(fs,0,sizeof(fs));if(!directory(stagefd,0700)||AS_FSTATFS(stagefd,fs)||fs[0]!=0x01021994)return reject();
 stage=12;if(!hashed(stagefd,"boot.so",HOOK_SHA)||!hashed(stagefd,"ssh-service.arm64",HELPER_SHA))return reject();
 stage=13;int ram=open(RAM_ROOT,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(!directory(ram,0)||!hashed(ram,"host-public-key",PUBLIC_SHA)||!hashed(ram,"ready",READY_SHA)){if(ram>=0)close(ram);return reject();}
 stage=14;char ns[96];ssize_t length=readlink(PROC_NS,ns,sizeof(ns));if(length!=(ssize_t)sizeof(ACTIVE_NS)-1||memcmp(ns,ACTIVE_NS,sizeof(ACTIVE_NS)-1)){close(ram);return reject();}
 stage=15;int key=open_private_source();if(key<0){close(ram);return reject();}
 stage=16;memset(fs,0,sizeof(fs));if(AS_FSTATFS(etc,fs)||fs[1]<=0||fs[1]>1048576||fs[4]<262144/fs[1]+1||lock()){close(key);close(ram);return reject();}
 stage=17;if(mkdirat(etc,AUTO_NAME,0755)){close(key);close(ram);return reject();}dir=openat(etc,AUTO_NAME,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(!directory(dir,0)||fchmod(dir,0755)){close(key);close(ram);return reject();}
 stage=18;if(copy(stagefd,"boot.so",dir,"boot.so",HOOK_SHA,65536)||copy(stagefd,"ssh-service.arm64",dir,"ssh-service.arm64",HELPER_SHA,65536)||copy(key,"host_ecdsa",dir,"host_ecdsa",0,8192)||copy(ram,"host-public-key",dir,"host_ecdsa.pub",PUBLIC_SHA,512)||store(dir,"preload.baseline",neutral,512)){close(key);close(ram);return reject();}close(key);close(ram);
 stage=19;int self=open(SELF_EXE,O_RDONLY|O_CLOEXEC);unsigned char code[65536];int n=self>=0&&root_file(self)?bounded(self,code,sizeof(code)):-1;if(self>=0)close(self);if(n<1||store(dir,"control.static",code,(size_t)n)){memset(code,0,sizeof(code));return reject();}memset(code,0,sizeof(code));if(!executable(dir,"control.static")||!executable(dir,"ssh-service.arm64")||!readable_hook())return reject();
 stage=20;int network=open(RAM_PARENT,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);memset(fs,0,sizeof(fs));if(!network_directory(network)||AS_FSTATFS(network,fs)||fs[0]!=0x01021994||mkdirat(network,CLAIM_NAME,0700)){if(network>=0)close(network);return reject();}int claim=openat(network,CLAIM_NAME,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);close(network);if(!directory(claim,0700)||store(claim,"current-boot-suppressed",AUTO_ID "\n",sizeof(AUTO_ID))){if(claim>=0)close(claim);return reject();}close(claim);
 stage=21;if(store(dir,"enabled",AUTO_ID "\n",sizeof(AUTO_ID))||store(etc,PRELOAD_NEW,PRELOAD_LINE,sizeof(PRELOAD_LINE)-1)||AS_SYNCFS(etc))return reject();
 stage=22;if(pointer()!=0||!contents(dir,"enabled",AUTO_ID "\n",sizeof(AUTO_ID))||!hashed(dir,"boot.so",HOOK_SHA)||!hashed(dir,"ssh-service.arm64",HELPER_SHA))return reject();
 stage=23;if(AS_RENAME(etc,PRELOAD_NEW,etc,"ld.so.preload")||AS_SYNCFS(etc)||pointer()!=1)return reject();
 stage=24;if(unlock())return reject();
 return say("A7R5_AUTO_ENABLED1 " AUTO_ID " current_boot_suppressed=1 service_preserved=1 rebooted=0\n");
}
static int disable(int recover){
 stage=30;int current=pointer();if(current<0)return reject();if(current==0)return say("A7R5_AUTO_NEUTRAL1 " AUTO_ID " service_preserved=1\n");
 stage=31;if(lock())return reject();
 if(!recover){stage=32;dir=openat(etc,AUTO_NAME,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(!directory(dir,0))return reject();
   int on=contents(dir,"enabled",AUTO_ID "\n",sizeof(AUTO_ID));int off=contents(dir,"disabled",AUTO_ID "\n",sizeof(AUTO_ID));
   if(on&&absent(dir,"disabled")){if(AS_RENAME(dir,"enabled",dir,"disabled"))return reject();}else if(!(off&&absent(dir,"enabled")))return reject();
 }
 stage=33;if(store(etc,PRELOAD_RESTORE,neutral,512))return reject();
 stage=34;if(pointer()!=1||AS_RENAME(etc,PRELOAD_RESTORE,etc,"ld.so.preload")||AS_SYNCFS(etc)||pointer()!=0)return reject();
 stage=35;if(unlock())return reject();
 return say(recover?"A7R5_AUTO_RECOVERED1 " AUTO_ID " service_preserved=1\n":"A7R5_AUTO_DISABLED1 " AUTO_ID " service_preserved=1\n");
}
int main(int argc,char **argv){stage=1;if(argc!=2||getuid()!=AS_OWNER||geteuid()!=AS_OWNER)return reject();etc=open(ETC_ROOT,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);stage=2;if(!directory(etc,0))return reject();
 if(!strcmp(argv[1],"enable"))return enable();if(!strcmp(argv[1],"disable"))return disable(0);if(!strcmp(argv[1],"recover"))return disable(1);
 if(!strcmp(argv[1],"inspect")){stage=3;int kind=pointer();return kind<0?reject():say(kind?"A7R5_AUTO_INSPECT1 " AUTO_ID " preload=active\n":"A7R5_AUTO_INSPECT1 " AUTO_ID " preload=neutral\n");}return reject();}
