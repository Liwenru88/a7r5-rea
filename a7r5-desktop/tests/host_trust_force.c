/* 普通文件执行真实机内强制事务，仅转换系统调用，不访问设备。 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
typedef long s64;
typedef unsigned long u64;
#define P(x) ((s64)(x))
#define RDONLY 0
#define WRONLY 1
#define RDWR 2
#define CREATE 64
#define EXCL 128
#define NOFOLLOW 32768
#define CLOEXEC 524288
#undef AT_FDCWD
#define AT_FDCWD -100
#define TRUST_FIXTURE 1
#include "jit_config.h"
static char *target_path,*base_path,ram_path[4096],journal_path[4096],readback_path[4096];
static unsigned target_writes;
static int readback_fault,target_reopened;
static int resource_fault;
#ifdef TRUST_SCAN_TEST
static int scan_fault,proc_reads,fd_reads,inspection_reads,namespace_reads,fd_scans;
static s64 scan_open(s64 parent,const char *path)
{
    if(parent==90001&&!strcmp(path,"101"))return scan_fault==23?-EACCES:scan_fault==24?-ENOENT:90003;
    if(parent==90003&&!strcmp(path,"fd")){fd_scans++;return scan_fault==4||scan_fault==29?-EACCES:scan_fault==8||scan_fault==17?-ENOENT:90002;}
    if(parent==90003&&!strcmp(path,"mountinfo")){inspection_reads=0;return 90004;}
    if(parent==90003&&!strcmp(path,"stat")){inspection_reads=0;return scan_fault==17?-ENOENT:scan_fault==20?-EACCES:90005;}
    return -ENOSYS;
}
static s64 scan_read(s64 fd,char *raw,u64 cap)
{
    if(fd==90004){
        if(scan_fault==5)return -EACCES;if(scan_fault==8)return -ENOENT;
        if(scan_fault>=12)return -EINVAL;
    }
    if(inspection_reads++)return 0;
    const char *text;
    if(fd==90004)text=scan_fault==1?"1 0 252:129 / /target rw - ext4 /dev/cnflasha1 rw\n":
        scan_fault==10?"malformed":"1 0 0:1 / / rw - rootfs rootfs rw\n";
    else text=scan_fault==14?"101 (user) S 1 1 1 0 -1 0 0 0 0 0 0 0 0 0 0 0 1 0 100\n":
        scan_fault==15?"101 (user) Z 1 1 1 0 -1 0 0 0 0 0 0 0 0 0 0 0 1 0 100\n":
        scan_fault==16?"101 (user) X 1 1 1 0 -1 0 0 0 0 0 0 0 0 0 0 0 1 0 100\n":
        scan_fault==21?"malformed\n":
        scan_fault==25?"102 (worker) S 2 1 1 0 -1 2097152 0 0 0 0 0 0 0 0 0 0 1 0 100\n":
        scan_fault==26?"101 (worker ) nested) S 2 1 1 0 -1 2097152 0 0 0 0 0 0 0 0 0 0 1 0 100\n":
        scan_fault==27?"101 (worker) S 2 1 1 0 -1 184467440737095516160 0 0 0 0 0 0 0 0 0 0 1 0 100\n":
        "101 (worker) S 2 1 1 0 -1 2097152 0 0 0 0 0 0 0 0 0 0 1 0 100\n";
    size_t size=strlen(text);if(size>cap)return -EIO;memcpy(raw,text,size);return (s64)size;
}
#endif
static s64 sc(s64 n,s64 a,s64 b,s64 c,s64 d,s64 e,s64 f);
static s64 close_fd(s64 fd){
#ifdef TRUST_SCAN_TEST
    if(fd>=90001&&fd<=90005){
        if(scan_fault==9&&fd==90002)return -EIO;
        if((scan_fault==31&&fd==90004)||(scan_fault==32&&fd==90005))return -EINVAL;
        if(scan_fault==33&&fd==90004)return -EIO;
        return 0;
    }
#endif
    return close((int)fd);
}
static s64 open_file(const char *path,int flags){
    if(target_path&&!strcmp(path,target_path)&&(flags&3)==RDONLY&&(flags&EXCL))target_reopened=1;
#ifdef TRUST_SCAN_TEST
    if(!strcmp(path,"/proc"))return scan_fault==3?-EACCES:90001;
    if(!strcmp(path,"/proc/101/fd"))return scan_fault==4?-EACCES:scan_fault==8?-ENOENT:90002;
#endif
    if(!strcmp(path,"/tmp_wbshd")){if(resource_fault==3)return -EACCES;path=base_path;}
    int native=flags&3;
    if(flags&CREATE)native|=O_CREAT;
    if(flags&EXCL)native|=O_EXCL;
    if(flags&16384)native|=O_DIRECTORY;
    int fd=open(path,native|O_NOFOLLOW|O_CLOEXEC,0600);return fd<0?-errno:fd;
}
static s64 bounded(const char *path,char *raw,u64 cap){
    const char *info="MemAvailable: 131072 kB\n";
    if(resource_fault==2)info="MemAvailable: 65535 kB\n";
    const char *custom=getenv("A7R5_NATIVE_MEMINFO");if(custom)info=custom;
    if(!strcmp(path,"/proc/meminfo")&&resource_fault==1)return -EACCES;
    if(!strcmp(path,"/etc/ld.so.preload")&&cap>=512){memset(raw,'\n',512);return 512;}
    if(!strcmp(path,"/proc/meminfo")&&cap>=strlen(info)){memcpy(raw,info,strlen(info));return (s64)strlen(info);}
#ifdef TRUST_SCAN_TEST
    if(!strcmp(path,"/proc/101/mountinfo")){
        if(scan_fault>=12)return -EINVAL;
        if(scan_fault==5)return -EACCES;if(scan_fault==8)return -ENOENT;
        const char *mounts=scan_fault==1?"1 0 252:129 / /target rw - ext4 /dev/cnflasha1 rw\n":
            scan_fault==10?"malformed":"1 0 0:1 / / rw - rootfs rootfs rw\n";
        size_t n=strlen(mounts);if(n>cap)return -EIO;memcpy(raw,mounts,n);return (s64)n;
    }
#endif
    return -ENOENT;
}
static u64 append(char *out,u64 at,const char *s){while(*s)out[at++]=*s++;return at;}
static u64 number(char *out,u64 at,s64 n){return at+(u64)sprintf(out+at,"%ld",n);}
#undef memcpy
#include "native_gate.c"
#undef pread
#undef pwrite
#undef write
#undef fsync
#undef memcmp
#undef memcpy
static s64 sc(s64 n,s64 a,s64 b,s64 c,s64 d,s64 e,s64 f){
    (void)e;(void)f;
#ifdef TRUST_SCAN_TEST
    if(n==56&&(a==90001||a==90003))return scan_open(a,(const char *)b);
    if(n==63&&(a==90004||a==90005))return scan_read(a,(char *)b,(u64)c);
    if(n==78&&a==90003&&!strcmp((const char *)b,"ns/mnt")){
        namespace_reads++;
        if(scan_fault==19)return -EACCES;
        if(scan_fault==13||(scan_fault==22&&namespace_reads>1)){memcpy((void *)c,"mnt:[1]",7);return 7;}
        if(scan_fault==28&&namespace_reads>1)return -EIO;
        return -ENOENT;
    }
    if(n==172)return 999;
    if(n==61&&(a==90001||a==90002)){
        int *reads=a==90001?&proc_reads:&fd_reads;if((*reads)++)return 0;
        if(scan_fault==2&&a==90001)return 19;
        if(scan_fault==30&&a==90002)return -EIO;
        unsigned char *raw=(void *)b;const char *name=a==90001?"101":"17";
        unsigned len=32;memset(raw,0,len);raw[16]=len;memcpy(raw+19,name,strlen(name)+1);return len;
    }
    if(n==79&&a==90002){
        if(scan_fault==7)return -EACCES;
        if(scan_fault==6)return -ENOENT;
        struct target_stat *st=(void *)c;memset(st,0,sizeof(*st));
        st->mode=scan_fault==11||scan_fault==18?0060000:0100000;st->rdev=(252UL<<8)|129;return 0;
    }
#endif
    if(n==174||n==175)return 0;
    if(n==78){memcpy((void *)c,"mnt:[1]",7);return 7;}
    if(n==44){s64 *fs=(void *)b;memset(fs,0,15*sizeof(*fs));fs[0]=0x01021994;fs[1]=4096;fs[4]=resource_fault==4?1:65536;
        const char *size=getenv("A7R5_NATIVE_RAM_AVAILABLE");if(size){fs[1]=1;fs[4]=(s64)strtoull(size,0,10);}
        if(getenv("A7R5_NATIVE_RAM_OVERFLOW")){fs[1]=4294967297L;fs[4]=4294967296L;}
        return 0;}
    if(n==163){const char *limit=getenv("A7R5_NATIVE_FILE_LIMIT");((u64 *)b)[0]=limit?strtoull(limit,0,10):resource_fault==5?1:~0UL;return 0;}
    if(n==80){struct stat native;struct target_stat *st=(void *)b;
        if(fstat((int)a,&native))return -errno;
        memset(st,0,sizeof(*st));st->mode=native.st_mode;st->size=native.st_size;return 0;}
    if(n==67){ssize_t got=pread((int)a,(void *)b,(size_t)c,(off_t)d);
        if(target_reopened&&got>0){
            if(readback_fault==1&&d==0&&c>512)return got-1;
            if(readback_fault==2&&c==512)((unsigned char *)b)[0]^=1;
        }
        return got<0?-errno:got;}
    if(n==68){target_writes++;ssize_t got=pwrite((int)a,(void *)b,(size_t)c,(off_t)d);return got<0?-errno:got;}
    if(n==64){ssize_t got=write((int)a,(void *)b,(size_t)(target_reopened&&readback_fault==3?c-1:c));return got<0?-errno:got;}
    if(n==82)return fsync((int)a)?-errno:0;
    if(n==34)return mkdir((char *)b,(mode_t)c)?-errno:0;
    return -ENOSYS;
}
int main(int argc,char **argv){
#ifdef TRUST_SCAN_TEST
    if(argc!=4)return 2;scan_fault=atoi(argv[3]);
    int clear=process_users_clear();char row[512];u64 size=trust_users_state(row,0);row[size]=0;
    printf("clear=%d%s target_writes=%u fd_scans=%d\n",clear,row,target_writes,fd_scans);return 0;
#else
    if(argc!=3)return 2;
    const char *fault=getenv("A7R5_NATIVE_RB_FAULT");if(fault)readback_fault=atoi(fault);
    fault=getenv("A7R5_NATIVE_RESOURCE_FAULT");if(fault)resource_fault=atoi(fault);
    target_path=argv[1];base_path=argv[2];
    snprintf(ram_path,sizeof(ram_path),"%s/ram",base_path);
    snprintf(journal_path,sizeof(journal_path),"%s/ram/journal",base_path);
    snprintf(readback_path,sizeof(readback_path),"%s/ram/partition.logical",base_path);
    int code=native_task(1);printf("code=%d target_writes=%u\n",code,target_writes);
#ifdef TRUST_RESOURCE_CHECK_DIAGNOSTICS
    if(code==43||code==44){char row[512];u64 n=trust_resources_state(row,0);row[n]=0;printf("%s\n",row);}
#endif
    return 0;
#endif
}
