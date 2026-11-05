/* /proc与POSIX为内存服务；执行原目录锚定和原选择记录实现。 */
#include <string.h>
#include <stdint.h>
#include "r5_lut_directory.h"
#include "r5_filter_selection423.h"
static const char *mount_text,*fd_text;
static struct r5_lut_directory directory;
static uint8_t active[25],pending[25];
static size_t active_size,pending_size,positions[32];
static unsigned fault,live,err,rename_count,sync_count,close_count;
static int active_present,pending_present;
enum {WRITE=1,FSYNC=2,CLOSE=4,CORRUPT=8,RENAME=16,DIRSYNC=32,OPEN=64};
static int open_fd(unsigned n){if(live&(1u<<n))return -1;live|=1u<<n;positions[n]=0;return (int)n;}
static int error(int value){err=(unsigned)value;return -1;}
static int fs_open(const char *p,int flags,unsigned mode){
 (void)mode;if(!strcmp(p,"/usr/data/lut")&&flags==0xc000)return open_fd(10);
 if(!strcmp(p,"/proc/self/fdinfo/10"))return open_fd(2);
 if(!strcmp(p,"/proc/self/mountinfo"))return open_fd(3);return error(2);
}
static int fs_openat(int d,const char *p,int flags,unsigned mode){
 if(d!=10)return error(9);
 if(!strcmp(p,R5_FILTER_SELECTION_PENDING)){
  if(flags==0x80c1){if(mode!=0600 || fault&OPEN)return error(5);if(pending_present)return error(17);pending_present=1;pending_size=0;return open_fd(11);}
  return pending_present?open_fd(12):error(2);
 }
 if(!strcmp(p,R5_FILTER_SELECTION_FILE))return active_present?open_fd(13):error(2);
 return error(2);
}
static intptr_t fs_read(int fd,void *out,size_t size){
 const uint8_t *p;size_t n;
 if(fd==2){p=(const void *)fd_text;n=strlen(fd_text);}
 else if(fd==3){p=(const void *)mount_text;n=strlen(mount_text);}
 else if(fd==12){p=pending;n=pending_size;}
 else if(fd==13){p=active;n=active_size;}else return -1;
 n-=positions[fd];if(n>size)n=size;if(n>5)n=5;
 memcpy(out,p+positions[fd],n);positions[fd]+=n;
 if(fd==12 && fault&CORRUPT && n)((uint8_t *)out)[0]^=1;
 return (intptr_t)n;
}
static intptr_t fs_write(int fd,const void *p,size_t n){
 if(fd!=11 || fault&WRITE)return 0;if(n>3)n=3;
 memcpy(pending+pending_size,p,n);pending_size+=n;return (intptr_t)n;
}
static int fs_close(int fd){
 if(!(live&(1u<<fd)))return -1;live&=~(1u<<fd);close_count++;
 return fd==11 && fault&CLOSE?-1:0;
}
static int fs_sync(int fd){sync_count++;return ((fd==11 && fault&FSYNC)||(fd==10 && fault&DIRSYNC))?-1:0;}
static int fs_rename(int d,const char *p,int e,const char *q){
 if(d!=10||e!=10||strcmp(p,R5_FILTER_SELECTION_PENDING)||strcmp(q,R5_FILTER_SELECTION_FILE)||fault&RENAME)return -1;
 memcpy(active,pending,pending_size);active_size=pending_size;active_present=1;pending_present=0;rename_count++;return 0;
}
static int fs_unlink(int d,const char *p,int flags){
 if(d!=10 || strcmp(p,R5_FILTER_SELECTION_PENDING)||flags)return -1;
 if(!pending_present)return error(2);pending_present=0;return 0;
}
static int fs_dup(int fd){return fd==10?open_fd(20):-1;}
static int *fs_errno(void){return (int *)&err;}
int test_acquire(const char *m,const char *f){
 static uint8_t scratch[65537];
 struct r5_lut_directory_api a={fs_open,fs_openat,fs_read,fs_write,fs_close,fs_sync,fs_rename,fs_unlink,fs_dup,fs_errno};
 mount_text=m;fd_text=f;return r5_lut_directory_acquire(&directory,&a,scratch,sizeof scratch);
}
int test_release(void){return r5_lut_directory_release(&directory);}
void test_fault(unsigned value){fault=value;}
void test_corrupt_active(unsigned index){if(index<active_size)active[index]^=1;}
int test_save(unsigned n){return r5_filter_selection_save(&directory,n);}
int test_load(unsigned *n){return r5_filter_selection_load(&directory,n);}
unsigned test_stat(unsigned n){const unsigned v[]={live,rename_count,sync_count,close_count,active_present,pending_present,directory.phase};return n<7?v[n]:~0u;}
