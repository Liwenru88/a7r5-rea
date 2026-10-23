/* 只供静态控制工具使用的Linux AArch64微型运行时，不依赖动态加载器。 */
#include <stddef.h>
#include <stdint.h>
static int saved_errno;
int *__errno_location(void){return &saved_errno;}
static long call(long n,long a,long b,long c,long d,long e,long f){register long x8 __asm__("x8")=n;register long x0 __asm__("x0")=a;register long x1 __asm__("x1")=b;register long x2 __asm__("x2")=c;register long x3 __asm__("x3")=d;register long x4 __asm__("x4")=e;register long x5 __asm__("x5")=f;__asm__ volatile("svc #0":"+r"(x0):"r"(x8),"r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5):"memory","cc");if(x0<0&&x0>=-4095){saved_errno=(int)-x0;return -1;}return x0;}
void *memset(void *p,int c,size_t n){unsigned char *q=p;while(n--)*q++=(unsigned char)c;return p;}
void *memcpy(void *p,const void *v,size_t n){unsigned char *q=p;const unsigned char *s=v;while(n--)*q++=*s++;return p;}
int memcmp(const void *a,const void *b,size_t n){const unsigned char *x=a,*y=b;while(n--){if(*x!=*y)return (int)*x-*y;x++;y++;}return 0;}
size_t strlen(const char *p){size_t n=0;while(p[n])n++;return n;}
int strcmp(const char *a,const char *b){while(*a&&*a==*b){a++;b++;}return (unsigned char)*a-(unsigned char)*b;}
int openat(int fd,const char *p,int flags,...){return (int)call(56,fd,(long)p,flags,0600,0,0);}
int open(const char *p,int flags,...){return openat(-100,p,flags,0600);}
int close(int fd){return (int)call(57,fd,0,0,0,0,0);}
long read(int fd,void *p,size_t n){return call(63,fd,(long)p,(long)n,0,0,0);}
long write(int fd,const void *p,size_t n){return call(64,fd,(long)p,(long)n,0,0,0);}
long syscall(long n,...){__builtin_va_list ap;__builtin_va_start(ap,n);long a=__builtin_va_arg(ap,int);void *b=__builtin_va_arg(ap,void *);long c=0,d=0;if(n==79){c=(long)__builtin_va_arg(ap,void *);d=__builtin_va_arg(ap,int);}__builtin_va_end(ap);if(n!=79&&n!=80){saved_errno=38;return -1;}return call(n,a,(long)b,c,d,0,0);}

int mkdirat(int fd,const char *p,unsigned mode){return (int)call(34,fd,(long)p,mode,0,0,0);}
int renameat(int a,const char *p,int b,const char *q){return (int)call(38,a,(long)p,b,(long)q,0,0);}
int unlinkat(int fd,const char *p,int flag){return (int)call(35,fd,(long)p,flag,0,0,0);}
int fsync(int fd){return (int)call(82,fd,0,0,0,0,0);}
int fchmod(int fd,unsigned mode){return (int)call(52,fd,mode,0,0,0,0);}
int syncfs(int fd){return (int)call(267,fd,0,0,0,0,0);}
int fstatfs(int fd,void *st){return (int)call(44,fd,(long)st,0,0,0,0);}
long readlink(const char *p,char *v,size_t n){return call(78,-100,(long)p,(long)v,(long)n,0,0);}
unsigned getuid(void){return (unsigned)call(174,0,0,0,0,0,0);}
unsigned geteuid(void){return (unsigned)call(175,0,0,0,0,0,0);}
int kill(int p,int sig){return (int)call(129,p,sig,0,0,0,0);}
