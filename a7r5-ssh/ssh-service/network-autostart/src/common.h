/* 网络自启只使用固定路径；本机测试通过头文件注入受控夹具。 */
#include "ns_abi.h"
#include "ns_sha256.h"
#include "net_config.h"
#ifndef NET_OWNER
#define NET_OWNER 0U
#endif
#ifndef NS_HOST_TEST
extern int fchmod(int,unsigned),unlinkat(int,const char *,int);
#endif
#ifndef NET_FSTATFS
extern int fstatfs(int,void *);
#define NET_FSTATFS fstatfs
#endif
#ifndef NET_SYNCFS
extern int syncfs(int);
#define NET_SYNCFS syncfs
#endif
#ifndef NET_RENAME
#define NET_RENAME renameat
#endif
#ifndef NET_FSYNC
#define NET_FSYNC fsync
#endif
#ifdef NS_HOST_TEST
#define NET_NONBLOCK O_NONBLOCK
#define NET_REMOVEDIR AT_REMOVEDIR
#else
#define NET_NONBLOCK 04000
#define NET_REMOVEDIR 512
#endif
static unsigned char net_buffer[65536];
static void clear_buffer(void){volatile unsigned char *p=net_buffer;for(size_t n=0;n<sizeof(net_buffer);n++)p[n]=0;}
static int root_file(int fd){struct stat st;return fd>=0&&!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_uid==NET_OWNER&&!(st.st_mode&022)&&st.st_nlink==1;}
static int root_dir(int fd,unsigned mode){struct stat st;return fd>=0&&!fstat(fd,&st)&&S_ISDIR(st.st_mode)&&st.st_uid==NET_OWNER&&!(st.st_mode&022)&&(!mode||(st.st_mode&07777)==mode);}
static int ram_dir(int fd){struct stat st;long fs[32];memset(fs,0,sizeof(fs));if(fd<0||fstat(fd,&st)||!S_ISDIR(st.st_mode)||st.st_uid!=NET_OWNER||NET_FSTATFS(fd,fs)||fs[0]!=0x01021994)return 0;unsigned m=st.st_mode&07777;return m==0700||m==0755||m==01777;}
static int bounded(int fd,void *v,size_t cap){size_t used=0;while(used<cap){ssize_t n=read(fd,(char *)v+used,cap-used);if(n<0&&errno==EINTR)continue;if(n<0)return -1;if(!n)return (int)used;used+=(size_t)n;}char extra;return read(fd,&extra,1)==0?(int)used:-1;}
static int get(int dir,const char *name,void *v,size_t cap){int fd=openat(dir,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|NET_NONBLOCK);if(fd<0)return -1;int n=root_file(fd)?bounded(fd,v,cap):-1;if(close(fd))n=-1;return n;}
static int contents(int dir,const char *name,const void *v,size_t bytes){int n=get(dir,name,net_buffer,sizeof(net_buffer));int ok=n==(int)bytes&&!memcmp(net_buffer,v,bytes);clear_buffer();return ok;}
static int hashed(int dir,const char *name,const char *wanted){int n=get(dir,name,net_buffer,sizeof(net_buffer));char sum[65];if(n<1){clear_buffer();return 0;}sha_bytes(net_buffer,(size_t)n,sum);clear_buffer();return !strcmp(sum,wanted);}
static int absent(int dir,const char *name){struct stat st;int fd=openat(dir,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|NET_NONBLOCK);if(fd>=0){fstat(fd,&st);close(fd);return 0;}return errno==ENOENT;}
static int path_absent(const char *path){struct stat st;return lstat(path,&st)<0&&errno==ENOENT;}
static int store(int dir,const char *name,const void *v,size_t bytes){int fd=openat(dir,name,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);if(fd<0)return -1;size_t used=0;int fail=!root_file(fd);while(!fail&&used<bytes){ssize_t n=write(fd,(const char *)v+used,bytes-used);if(n<0&&errno==EINTR)continue;if(n<=0){fail=1;break;}used+=(size_t)n;}if(NET_FSYNC(fd))fail=1;if(close(fd))fail=1;return fail||!contents(dir,name,v,bytes)?-1:0;}
static int marker(void){int dir=open(NET_DIR,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);int ok=root_dir(dir,0)&&contents(dir,"enabled",NET_ID "\n",sizeof(NET_ID));if(dir>=0)close(dir);return ok;}
static int same_namespace(void){char a[96],b[96];ssize_t n=readlink(PROC_SELF_NS,a,sizeof(a)),m=readlink(PROC_INIT_NS,b,sizeof(b));return n>6&&n<(ssize_t)sizeof(a)&&m==n&&!memcmp(a,b,(size_t)n);}
static int verified_helper(void){int dir=open(HELPER_DIR,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(!root_dir(dir,0)){if(dir>=0)close(dir);return -1;}int fd=openat(dir,"ssh-service.arm64",O_RDONLY|O_NOFOLLOW|O_CLOEXEC|NET_NONBLOCK);close(dir);struct stat st;int ok=root_file(fd)&&!fstat(fd,&st)&&(st.st_mode&0100)&&st.st_size==HELPER_BYTES;int n=ok?bounded(fd,net_buffer,sizeof(net_buffer)):-1;char digest[65];if(n==HELPER_BYTES){sha_bytes(net_buffer,(size_t)n,digest);ok=!strcmp(digest,HELPER_SHA);}else ok=0;clear_buffer();if(!ok){if(fd>=0)close(fd);return -1;}return fd;}
