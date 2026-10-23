/* 只在已验证的私有tmpfs目录创建密钥副本；不改变持久源文件权限。 */
#ifndef A7R5_PRIVATE_HOSTKEY_H
#define A7R5_PRIVATE_HOSTKEY_H
#ifndef HK_OWNER
#define HK_OWNER 0U
#endif
#ifndef HK_READ
#define HK_READ read
#endif
#ifndef HK_WRITE
#define HK_WRITE write
#endif
#ifndef HK_FCHMOD
#define HK_FCHMOD fchmod
#endif
#ifndef HK_FSTAT
#define HK_FSTAT fstat
#endif
#ifndef NS_HOST_TEST
extern int fchmod(int,unsigned),unlinkat(int,const char *,int);
extern long lseek(int,long,int);
#endif

#ifdef NS_HOST_TEST
#define HK_NONBLOCK O_NONBLOCK
#else
#define HK_NONBLOCK 04000
#endif
#define HK_MAX_BYTES 8192
struct hostkey_copy {
    struct stat source,destination;
    int stage,error,created,removed,verified;
};
/* 只写数字和固定字段；不得输出密钥字节或私钥摘要。 */
static int hostkey_report(char *raw,size_t cap,const char *run,const struct hostkey_copy *r){
    return snprintf(raw,cap,"A7R5_RAM_HOSTKEY1 %s stage=%d errno=%d verified=%d source_mode=%o source_uid=%u source_gid=%u source_bytes=%lld dest_mode=%o dest_uid=%u dest_gid=%u dest_bytes=%lld dest_tmpfs=%d source_unchanged=%d partial_removed=%d private_key_logged=0\n",
        run,r->stage,r->error,r->verified,(unsigned)r->source.st_mode,(unsigned)r->source.st_uid,(unsigned)r->source.st_gid,(long long)r->source.st_size,
        (unsigned)r->destination.st_mode,(unsigned)r->destination.st_uid,(unsigned)r->destination.st_gid,(long long)r->destination.st_size,
        r->verified,r->verified,r->removed);
}
static void hostkey_wipe(void *raw,size_t n){volatile unsigned char *p=raw;while(n--)*p++=0;}
static int hostkey_same_source(const struct stat *a,const struct stat *b){
    if(a->st_dev!=b->st_dev||a->st_ino!=b->st_ino||a->st_mode!=b->st_mode||a->st_uid!=b->st_uid||a->st_gid!=b->st_gid||a->st_size!=b->st_size||a->st_nlink!=b->st_nlink)return 0;
#ifdef NS_HOST_TEST
#ifdef __APPLE__
    return a->st_mtimespec.tv_sec==b->st_mtimespec.tv_sec&&a->st_mtimespec.tv_nsec==b->st_mtimespec.tv_nsec&&a->st_ctimespec.tv_sec==b->st_ctimespec.tv_sec&&a->st_ctimespec.tv_nsec==b->st_ctimespec.tv_nsec;
#else
    return a->st_mtim.tv_sec==b->st_mtim.tv_sec&&a->st_mtim.tv_nsec==b->st_mtim.tv_nsec&&a->st_ctim.tv_sec==b->st_ctim.tv_sec&&a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;
#endif
#else
    return a->mtime_s==b->mtime_s&&a->mtime_ns==b->mtime_ns&&a->ctime_s==b->ctime_s&&a->ctime_ns==b->ctime_ns;
#endif
}
#ifndef HK_TMPFS
static int hostkey_tmpfs(int fd){extern int fstatfs(int,void *);long fs[32];memset(fs,0,sizeof(fs));return !fstatfs(fd,fs)&&fs[0]==0x01021994;}
#define HK_TMPFS hostkey_tmpfs
#endif
/* stage：1目录、2源打开、3源属性、4目标文件系统、5独占创建、6权限、7复制、8源竞态、9回读、10落盘/关闭。 */
static int private_hostkey_copy(int source_directory,int private_directory,struct hostkey_copy *result){
    char key[HK_MAX_BYTES],verify[HK_MAX_BYTES],extra;
    struct stat directory,after;
    int source=-1,destination=-1,success=0;size_t used=0;
    memset(result,0,sizeof(*result));memset(key,0,sizeof(key));memset(verify,0,sizeof(verify));
    result->stage=1;errno=0;
    if(HK_FSTAT(source_directory,&directory)||!S_ISDIR(directory.st_mode)||directory.st_uid!=HK_OWNER||(directory.st_mode&022))goto failure;
    if(HK_FSTAT(private_directory,&directory)||!S_ISDIR(directory.st_mode)||directory.st_uid!=HK_OWNER||(directory.st_mode&07777)!=0700)goto failure;
    result->stage=2;errno=0;
    /* O_NONBLOCK防止FIFO在fstat之前阻塞；普通文件不受影响。 */
    source=openat(source_directory,"host_ecdsa",O_RDONLY|O_NOFOLLOW|O_CLOEXEC|HK_NONBLOCK);
    if(source<0)goto failure;
    result->stage=3;errno=0;
    if(HK_FSTAT(source,&result->source)||!S_ISREG(result->source.st_mode)||result->source.st_uid!=HK_OWNER||(result->source.st_mode&022)||result->source.st_nlink!=1||result->source.st_size<=0||result->source.st_size>HK_MAX_BYTES)goto failure;
    result->stage=4;errno=0;
    if(!HK_TMPFS(private_directory))goto failure;
    result->stage=5;errno=0;
    destination=openat(private_directory,"host_ecdsa",O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if(destination<0)goto failure;
    result->created=1;result->stage=6;errno=0;
    if(!HK_TMPFS(destination)||HK_FCHMOD(destination,0600)||HK_FSTAT(destination,&result->destination)||!S_ISREG(result->destination.st_mode)||result->destination.st_uid!=HK_OWNER||(result->destination.st_mode&07777)!=0600||result->destination.st_nlink!=1)goto failure;
    result->stage=7;errno=0;
    while(used<(size_t)result->source.st_size){ssize_t n=HK_READ(source,key+used,(size_t)result->source.st_size-used);if(n<0&&errno==EINTR)continue;if(n<=0)goto failure;used+=(size_t)n;}
    {ssize_t n;do{n=HK_READ(source,&extra,1);}while(n<0&&errno==EINTR);if(n!=0)goto failure;}
    {size_t offset=0;while(offset<used){ssize_t n=HK_WRITE(destination,key+offset,used-offset);if(n<0&&errno==EINTR)continue;if(n<=0)goto failure;offset+=(size_t)n;}}
    result->stage=8;errno=0;
    if(HK_FSTAT(source,&after)||!hostkey_same_source(&result->source,&after))goto failure;
    result->stage=9;errno=0;
    if(fsync(destination)||lseek(destination,0,0)!=0)goto failure;
    {size_t offset=0;while(offset<used){ssize_t n=HK_READ(destination,verify+offset,used-offset);if(n<0&&errno==EINTR)continue;if(n<=0)goto failure;offset+=(size_t)n;}}
    {ssize_t n;do{n=HK_READ(destination,&extra,1);}while(n<0&&errno==EINTR);if(n!=0)goto failure;}
    if(memcmp(key,verify,used)||HK_FSTAT(destination,&result->destination)||result->destination.st_size!=(long)used||!S_ISREG(result->destination.st_mode)||result->destination.st_uid!=HK_OWNER||(result->destination.st_mode&07777)!=0600||result->destination.st_nlink!=1||!HK_TMPFS(destination))goto failure;
    result->stage=10;errno=0;
    if(close(source)){source=-1;goto failure;}source=-1;
    if(close(destination)){destination=-1;goto failure;}destination=-1;
    result->stage=0;errno=0;result->verified=1;success=1;
    goto finish;
failure:
    /* 属性拒绝使用明确EPERM，避免继承之前EROFS等无关errno。 */
    result->error=errno?errno:1;
finish:
    hostkey_wipe(key,sizeof(key));hostkey_wipe(verify,sizeof(verify));
    if(source>=0)close(source);if(destination>=0)close(destination);
    if(!success&&result->created)result->removed=unlinkat(private_directory,"host_ecdsa",0)==0;
    errno=result->error;
    return success?0:-1;
}
#endif
