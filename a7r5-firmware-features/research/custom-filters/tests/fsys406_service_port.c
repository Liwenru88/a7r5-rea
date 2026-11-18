/* 仅宿主集成的原Fsys ABI端口；普通临时文件不等于原Fsys或真实SD执行。 */
#include "af_fsys406.h"
static AfFsys406 fsys_service;
static const char *fsys_file_name;
static unsigned fsys_encoding;
static int fsys_policy(void *context){assert(context==&fsys_encoding);return AF_OK;}
static int fsys_snapshot(void *context,uint8_t output[AF_FSYS406_SNAPSHOT_BYTES]){
 assert(context==&fsys_service);memset(output,0,AF_FSYS406_SNAPSHOT_BYTES);
 output[0x19]='A';output[0x1c]=3;return AF_OK;
}
static const char *fsys_name(const char *path){
 static const char prefix[]="A:/Private/Sony/PRO/LUT/";
 assert(!strncmp(path,prefix,sizeof(prefix)-1));return path+sizeof(prefix)-1;
}
static int32_t fsys_first(const char *path,uint8_t flags,void *output){
 assert(flags==0x80);const char *name=fsys_name(path);
 if(strcmp(name,"*.*")&&strcmp(name,fsys_file_name))return 2;
 struct stat status;if(fstatat(media_context.fd,fsys_file_name,&status,AT_SYMLINK_NOFOLLOW))return 2;
 assert(S_ISREG(status.st_mode)&&status.st_size>0);
 uint8_t *p=output;memset(p,0,AF_FSYS406_FIND_BYTES);
 uint64_t pointer=(uint64_t)(uintptr_t)(p+0x5b7),size=(uint64_t)status.st_size;
 memcpy(p,&pointer,8);memcpy(p+8,&size,8);p[0x26]=0x20;
 memcpy(p+0x5b7,fsys_file_name,strlen(fsys_file_name)+1);return 0;
}
static int32_t fsys_next(void *output){assert(output);return 2;}
static int32_t fsys_open(const char *path,uint64_t *token,uint32_t flags){
 assert(flags==1&&!strcmp(fsys_name(path),fsys_file_name));
 int fd=openat(media_context.fd,fsys_file_name,O_RDONLY|O_CLOEXEC);
 if(fd<0)return -1;
 *token=UINT64_C(0xfedcba9800000000)|(uint32_t)fd;return 0;
}
static int fsys_fd(uint64_t token){assert((token>>32)==UINT64_C(0xfedcba98));return (int)(uint32_t)token;}
static int32_t fsys_read(uint64_t token,void *output,int32_t size){
 assert(size>0);return (int32_t)read(fsys_fd(token),output,(size_t)size);
}
static int32_t fsys_close(uint64_t token){return close(fsys_fd(token));}
static void fsys_port_prepare(int fd,const char *name,AfMediaProvider *provider){
 media_context.fd=fd;fsys_file_name=name;
 AfFsys406Binding binding={AF_FSYS406_VERSION,sizeof(binding),0,0,&fsys_service,fsys_snapshot,
  {fsys_open,fsys_read,fsys_close,fsys_first,fsys_next},&fsys_encoding,fsys_policy};
 assert(!af_fsys406_init(&fsys_service,&binding));
 *provider=(AfMediaProvider){1,sizeof(*provider),&media_context,provider_scan,provider_read};
}
