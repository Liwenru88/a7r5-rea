/* 仅用于客体只读导出；使用生产记录／文档解码器，不替换或修复记录。 */
#include "af_target_posix.h"
#include "af_record.h"
#include "af_document.h"
#include "af_joint_asset.h"
extern int printf(const char *,...);
extern void *malloc(size_t);
extern void free(void *);
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start,%function\n_start:\nmov x0,sp\nbl entry\nbrk #0\n");
static int run(int argc,char **argv){
 (void)argv;if(argc!=1)return 2;
 int dir=open("/setting/A7LOOKS1",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(dir<0)return 3;
 uint8_t *data=malloc(AF_DOCUMENT_MAX+AF_RECORD_HEADER);if(!data)return 4;
 unsigned files=0;size_t total=0;
 printf("AF_STORE_BEGIN v=1 root=/setting/A7LOOKS1\n");
 for(unsigned i=0;i<41;++i){
  char name[20];unsigned slot=i?(i-1)/2+1:0;
  if(i)snprintf(name,sizeof(name),"C%02u_%c.rec",slot,(i-1)%2?'B':'A');
  else snprintf(name,sizeof(name),"STORE.ID");
  int fd=openat(dir,name,O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC);
  if(fd<0){if(errno!=ENOENT||!i)return 5;printf("AF_STORE_ABSENT name=%s\n",name);continue;}
  struct stat s;if(fstat(fd,&s)||!S_ISREG(s.st_mode)||s.st_nlink!=1||s.st_uid!=0||
    s.st_size<=0||(uint64_t)s.st_size>AF_DOCUMENT_MAX+AF_RECORD_HEADER)return 6;
  size_t n=(size_t)s.st_size,at=0;
  while(at<n){ssize_t got=read(fd,data+at,n-at);if(got<0&&errno==EINTR)continue;if(got<=0)return 7;at+=(size_t)got;}
  uint8_t extra;if(read(fd,&extra,1)!=0||close(fd))return 8;
  if(i){
   AfRecordView r;AfDocument d;
   if(af_record_decode(data,n,slot,AF_DOCUMENT_MAX,&r)||af_document_decode(r.payload,r.bytes,AF_JOINT_ASSET_SCHEMA,&d))return 9;
   printf("AF_STORE_CHECK name=%s generation=%llu present=%u kind=%u schema=%u converter=%u\n",name,
    (unsigned long long)r.generation,d.present,d.saved.kind,d.schema,d.converter);
  }else if(n!=96)return 10;
  printf("AF_STORE_FILE name=%s bytes=%lu\n",name,(unsigned long)n);
  for(size_t off=0;off<n;off+=64){
   printf("AF_STORE_HEX offset=%08lx data=",(unsigned long)off);
   for(size_t j=off;j<n&&j<off+64;++j)printf("%02x",data[j]);printf("\n");
  }
  printf("AF_STORE_END name=%s bytes=%lu\n",name,(unsigned long)n);++files;total+=n;
 }
 free(data);if(close(dir))return 11;
 printf("AF_STORE_DONE files=%u bytes=%lu status=0\n",files,(unsigned long)total);return 0;
}
__attribute__((noreturn)) void entry(unsigned long *s){__libc_start_main(run,(int)s[0],(char **)(s+1),0,0,0,s);__builtin_trap();}
