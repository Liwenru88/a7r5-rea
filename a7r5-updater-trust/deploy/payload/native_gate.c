/* 仅供本次固定一号逻辑分区事务；全部目标写入由 trust_apply_fd 完成。 */
#include <stddef.h>
#include <stdint.h>
typedef long ssize_t;
struct target_stat {
    u64 dev,ino; unsigned mode,nlink,uid,gid; u64 rdev,pad;
    s64 size; unsigned blksize,pad2; u64 blocks,rest[7];
};
_Static_assert(sizeof(struct target_stat)==128,"AArch64 stat ABI");
static unsigned char inspection[65536];
static int cmp(const void *aa,const void *bb,size_t n)
{ const unsigned char *a=aa,*b=bb;for(size_t i=0;i<n;i++)if(a[i]!=b[i])return 1;return 0; }
static void *copy(void *aa,const void *bb,size_t n)
{ unsigned char *a=aa;const unsigned char *b=bb;for(size_t i=0;i<n;i++)a[i]=b[i];return aa; }
static long t_pread(int f,void *p,size_t n,long off){return sc(67,f,P(p),n,off,0,0);}
static long t_pwrite(int f,const void *p,size_t n,long off){return sc(68,f,P(p),n,off,0,0);}
static long t_write(int f,const void *p,size_t n){return sc(64,f,P(p),n,0,0,0);}
static int t_sync(int f){return (int)sc(82,f,0,0,0,0,0);}
#define pread t_pread
#define pwrite t_pwrite
#define write t_write
#define fsync t_sync
#define memcmp cmp
#define memcpy copy
#include "sha256.h"
#include "trust_config.h"
static int note(int fd,const char *phase,unsigned count,long offset,int code)
{
    char row[256];u64 n=append(row,0,"A7R5_TRUST " RUN_ID " ");
    n=append(row,n,phase);n=append(row,n," completed=");n=number(row,n,count);
    n=append(row,n," offset=");n=number(row,n,offset);
    n=append(row,n," code=");n=number(row,n,code);row[n++]='\n';
    return write(fd,row,n)!=(long)n||fsync(fd)?-1:0;
}
#include "sector_core.inc"

static int numeric(const char *s)
{if(!*s)return 0;for(;*s;s++)if(*s<'0'||*s>'9')return 0;return 1;}
static int terminated(const char *s,unsigned n)
{for(unsigned i=0;i<n;i++)if(!s[i])return 1;return 0;}
static int protected_dev(u64 d)
{return d==((252UL<<8)|129)||d==((252UL<<8)|1)||d==(252UL<<8);}
static int target_identity(int fd)
{
    struct target_stat st;u64 capacity=0;
    if(sc(80,fd,P(&st),0,0,0,0)<0)return 1;
#ifdef TRUST_FIXTURE
    /* 此分支只生成模拟夹具；实机包不定义该宏，并绑定另一份库的摘要。 */
    (void)capacity;
    return (st.mode&0170000)==0100000&&st.size==PARTITION_BYTES?0:2;
#else
    if((st.mode&0170000)!=0060000||st.rdev!=((252UL<<8)|129))return 2;
    if(sc(29,fd,0x80081272UL,P(&capacity),0,0,0)<0||capacity!=PARTITION_BYTES)return 3;
    return 0;
#endif
}
static int same_original_namespace(void)
{
    char a[128],b[128];
    s64 n=sc(78,AT_FDCWD,P("/proc/self/ns/mnt"),P(a),sizeof(a),0,0);
    s64 m=sc(78,AT_FDCWD,P("/proc/1/ns/mnt"),P(b),sizeof(b),0,0);
    return n>0&&n<(s64)sizeof(a)&&n==m&&!cmp(a,b,n);
}
static int mounts_clear(const char *path)
{
    s64 n=bounded(path,(char *)inspection,sizeof(inspection));if(n<0)return 0;
    for(s64 at=0;at<n;){
        s64 end=at;while(end<n&&inspection[end]!='\n')end++;
        s64 p=at;for(int k=0;k<2;k++){while(p<end&&inspection[p]!=' ')p++;p++;}
        s64 q=p;while(q<end&&inspection[q]!=' ')q++;
        if((q-p==7&&!cmp(inspection+p,"252:129",7))||
           (q-p==5&&!cmp(inspection+p,"252:1",5))||
           (q-p==5&&!cmp(inspection+p,"252:0",5)))return 0;
        at=end+1;
    }
    return 1;
}
/* proc 中消失的进程或 FD 允许忽略；其他枚举/权限/截断错误均拒绝写入。 */
static int process_users_clear(void)
{
    int proc=(int)open_file("/proc",RDONLY|16384|NOFOLLOW|CLOEXEC);
    if(proc<0)return 0;
    unsigned char dirs[16384],fds[16384];int ok=1;
    s64 own=sc(172,0,0,0,0,0,0);
    for(;;){
        s64 n=sc(61,proc,P(dirs),sizeof(dirs),0,0,0);if(n<0){ok=0;break;}if(!n)break;
        for(s64 at=0;at<n;){
            unsigned len=dirs[at+16]|((unsigned)dirs[at+17]<<8);
            if(len<20||at+len>n){ok=0;break;}
            char *pid=(char *)dirs+at+19;
            if(!terminated(pid,len-19)){ok=0;break;}
            at+=len;if(!numeric(pid))continue;
            char path[160];u64 pos=append(path,0,"/proc/");pos=append(path,pos,pid);
            pos=append(path,pos,"/mountinfo");path[pos]=0;
            if(!mounts_clear(path)){
                int exists=(int)open_file(path,RDONLY|NOFOLLOW|CLOEXEC);
                if(exists!=-2&&exists!=-3){if(exists>=0)close_fd(exists);ok=0;break;}
            }
            pos=append(path,0,"/proc/");pos=append(path,pos,pid);pos=append(path,pos,"/fd");path[pos]=0;
            int dir=(int)open_file(path,RDONLY|16384|NOFOLLOW|CLOEXEC);
            if(dir<0){if(dir!=-2&&dir!=-3)ok=0;if(!ok)break;continue;}
            for(;;){
                s64 count=sc(61,dir,P(fds),sizeof(fds),0,0,0);if(count<0){ok=0;break;}if(!count)break;
                for(s64 off=0;off<count;){
                    unsigned bytes=fds[off+16]|((unsigned)fds[off+17]<<8);
                    if(bytes<20||off+bytes>count){ok=0;break;}
                    char *name=(char *)fds+off+19;
                    if(!terminated(name,bytes-19)){ok=0;break;}
                    off+=bytes;if(!numeric(name))continue;
                    s64 id=0;for(char *s=pid;*s;s++)id=id*10+*s-'0';if(id==own)continue;
                    struct target_stat st;
                    s64 r=sc(79,dir,P(name),P(&st),0,0,0);
                    if(r<0){if(r!=-2&&r!=-3)ok=0;}
                    else if((st.mode&0170000)==0060000&&protected_dev(st.rdev))ok=0;
                    if(!ok)break;
                }
                if(!ok)break;
            }
            if(close_fd(dir)<0)ok=0;if(!ok)break;
        }
        if(!ok)break;
    }
    if(close_fd(proc)<0)ok=0;return ok;
}
static int capture_reopened(int journal)
{
    int fd=(int)open_file(TARGET_PATH,RDONLY|EXCL|NOFOLLOW|CLOEXEC);
    if(fd<0||target_identity(fd)){if(fd>=0)close_fd(fd);return 62;}
    int output=(int)open_file(READBACK_PATH,WRONLY|CREATE|EXCL|NOFOLLOW|CLOEXEC);
    if(output<0){close_fd(fd);return 63;}
    struct sha_ctx h;sha_init(&h);char digest[65];int code=0;
    for(u64 at=0;at<PARTITION_BYTES;at+=sizeof(inspection)){
        u64 n=PARTITION_BYTES-at;if(n>sizeof(inspection))n=sizeof(inspection);
        if(pread(fd,inspection,n,at)!=(long)n||write(output,inspection,n)!=(long)n){code=64;break;}
        sha_add(&h,inspection,n);
    }
    if(!code){sha_end(&h,digest);if(cmp(digest,CANDIDATE_SHA,65)||fsync(output))code=65;}
    if(close_fd(output)<0)code=66;if(close_fd(fd)<0)code=67;
    if(!code&&note(journal,"REOPENED_FULL_CAPTURE_MATCH",PATCH_COUNT,-1,0))code=68;
    return code;
}
static int native_task(int output)
{
    char preload[4096],size[32];
    if(sc(174,0,0,0,0,0,0)||sc(175,0,0,0,0,0,0)||!same_original_namespace())return 40;
    s64 n=bounded("/etc/ld.so.preload",preload,sizeof(preload));
    if(n!=(s64)sizeof(EXPECTED_PRELOAD)-1||cmp(preload,EXPECTED_PRELOAD,sizeof(EXPECTED_PRELOAD)-1))return 41;
#ifndef TRUST_FIXTURE
    n=bounded("/sys/dev/block/252:129/size",size,sizeof(size));
    if(n!=6||cmp(size,"49024\n",6))return 42;
#else
    (void)size;
#endif
    n=bounded("/proc/meminfo",(char *)inspection,sizeof(inspection));
    if(n<0)return 43;
    u64 available=0;
    for(s64 at=0;at+13<n;at++)if((at==0||inspection[at-1]=='\n')&&!cmp(inspection+at,"MemAvailable:",13)){
        at+=13;while(at<n&&inspection[at]==' ')at++;
        while(at<n&&inspection[at]>='0'&&inspection[at]<='9')available=available*10+inspection[at++]-'0';
        break;
    }
    if(available<65536)return 43;
    int dir=(int)open_file("/tmp_wbshd",RDONLY|16384|NOFOLLOW|CLOEXEC);
    if(dir<0)return 43;
    s64 fs[15];u64 limit[2];
    int valid=sc(44,dir,P(fs),0,0,0,0)==0&&fs[0]==0x01021994&&fs[1]>0&&fs[4]>0&&
        (u64)fs[1]*(u64)fs[4]>PARTITION_BYTES+1048576;
    if(sc(163,1,P(limit),0,0,0,0)<0||limit[0]<PARTITION_BYTES)valid=0;
    if(close_fd(dir)<0||!valid)return 44;
    if(sc(34,AT_FDCWD,P(RAM_DIR),0700,0,0,0)<0)return 45;
    int journal=(int)open_file(JOURNAL_PATH,WRONLY|CREATE|EXCL|NOFOLLOW|CLOEXEC);
    if(journal<0)return 46;
#ifndef TRUST_FIXTURE
    if(!process_users_clear()){close_fd(journal);return 47;}
#else
    (void)process_users_clear;
#endif
    int fd=(int)open_file(TARGET_PATH,RDWR|EXCL|NOFOLLOW|CLOEXEC);
    if(fd<0){note(journal,"OPEN_REFUSED",0,-1,fd);close_fd(journal);return 48;}
    if(target_identity(fd)){close_fd(fd);close_fd(journal);return 49;}
    int code=trust_apply_fd(fd,journal,0);
    if(close_fd(fd)<0&&!code)code=50;
    if(!code)code=capture_reopened(journal);
    if(!code){
        n=bounded("/etc/ld.so.preload",preload,sizeof(preload));
        if(n!=(s64)sizeof(EXPECTED_PRELOAD)-1||cmp(preload,EXPECTED_PRELOAD,sizeof(EXPECTED_PRELOAD)-1))code=51;
    }
    if(note(journal,code?"STOP_NO_RETRY":"COMPLETED",code?0:PATCH_COUNT,-1,code)&&!code)code=52;
    if(close_fd(journal)<0&&!code)code=53;
    if(!code){
        const char message[]=OUTPUT_BEGIN "A7R5_TRUST_COMPLETE " CANDIDATE_SHA " sectors=258 bytes=132096 reopened=1\n" OUTPUT_END;
        if(write(output,message,sizeof(message)-1)!=(s64)sizeof(message)-1)code=54;
    }
    return code;
}
