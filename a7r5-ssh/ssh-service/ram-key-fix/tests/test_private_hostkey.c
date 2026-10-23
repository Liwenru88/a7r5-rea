/* 本机临时目录契约；tmpfs类型用明确替身，真实类型另由断网客体验证。 */
#define NS_HOST_TEST
#include "../../../src/ns_abi.h"
#include <sys/types.h>
static const char *fault;
static unsigned long source_inode;
static int source_reads,source_stats;
static int fake_tmpfs(int fd){(void)fd;return strcmp(fault,"not_ram")!=0;}
static int fake_fchmod(int fd,unsigned mode){if(!strcmp(fault,"chmod")){errno=1;return -1;}return fchmod(fd,(mode_t)(!strcmp(fault,"chmod_ignored")?0755:mode));}
static int fake_fstat(int fd,struct stat *st){int rc=fstat(fd,st);if(!rc&&(unsigned long)st->st_ino==source_inode){source_stats++;if(!strcmp(fault,"owner"))st->st_uid++;if(!strcmp(fault,"race")&&source_stats>1)st->st_size++;}return rc;}
static ssize_t fake_read(int fd,void *raw,size_t size){struct stat st;if(!fstat(fd,&st)&&(unsigned long)st.st_ino==source_inode){source_reads++;if(!strcmp(fault,"read")){errno=5;return -1;}}ssize_t n=read(fd,raw,size);if(!strcmp(fault,"corrupt")&&n>0&&(unsigned long)st.st_ino!=source_inode)((char *)raw)[0]^=1;return n;}
static ssize_t fake_write(int fd,const void *raw,size_t size){if(!strcmp(fault,"disk_full")){errno=28;return -1;}if(!strcmp(fault,"short_write")&&size>1)size=1;return write(fd,raw,size);}
#define HK_OWNER getuid()
#define HK_TMPFS fake_tmpfs
#define HK_FCHMOD fake_fchmod
#define HK_FSTAT fake_fstat
#define HK_READ fake_read
#define HK_WRITE fake_write
#include "../../private_hostkey.h"
int main(int argc,char **argv){
    if(argc!=3)return 64;fault=argv[2];char src[1024],dst[1024],key[1024],target[1024];
    snprintf(src,sizeof(src),"%s/source",argv[1]);snprintf(dst,sizeof(dst),"%s/private",argv[1]);snprintf(key,sizeof(key),"%s/source/host_ecdsa",argv[1]);snprintf(target,sizeof(target),"%s/private/host_ecdsa",argv[1]);
    if(mkdir(src,0755)||mkdir(dst,0700))return 65;
    const char secret[]="SYNTHETIC_PRIVATE_KEY_BYTES_NOT_FOR_LOGS\n";
    if(!strcmp(fault,"fifo")){if(mkfifo(key,0600))return 66;}
    else if(!strcmp(fault,"symlink")){if(symlink("/does-not-exist",key))return 66;}
    else if(strcmp(fault,"missing")){
        int fd=open(key,O_WRONLY|O_CREAT|O_EXCL,0600);if(fd<0)return 66;
        if(!strcmp(fault,"oversize")){char raw[9000];memset(raw,'x',sizeof(raw));if(write(fd,raw,sizeof(raw))!=(ssize_t)sizeof(raw))return 66;}
        else if(write(fd,secret,sizeof(secret)-1)!=(ssize_t)sizeof(secret)-1)return 66;
        close(fd);if(chmod(key,!strcmp(fault,"writable")?0777:0755))return 66;
    }
    if(!strcmp(fault,"dir_mode")&&chmod(dst,0755))return 66;
    if(!strcmp(fault,"collision")||!strcmp(fault,"destination_symlink")){
        if(!strcmp(fault,"destination_symlink")){if(symlink(key,target))return 66;}
        else{int fd=open(target,O_WRONLY|O_CREAT|O_EXCL,0600);if(fd<0||write(fd,"EXISTING",8)!=8)return 66;close(fd);}
    }
    struct stat before;memset(&before,0,sizeof(before));if(!lstat(key,&before))source_inode=(unsigned long)before.st_ino;
    int a=open(src,O_RDONLY|O_DIRECTORY|O_NOFOLLOW),b=open(dst,O_RDONLY|O_DIRECTORY|O_NOFOLLOW);
    struct hostkey_copy r;errno=30;int rc=private_hostkey_copy(a,b,&r);close(a);close(b);
    char report[1024];int count=hostkey_report(report,sizeof(report),"test",&r);if(count<0||(size_t)count>=sizeof(report))return 67;
    fputs(report,stdout);if(strstr(report,secret))return 68;
    int want=!strcmp(fault,"success")||!strcmp(fault,"short_write");
    if(want){
        char copy[sizeof(secret)];int fd=open(target,O_RDONLY|O_NOFOLLOW);if(rc||fd<0||read(fd,copy,sizeof(copy))!=(ssize_t)sizeof(secret)-1||memcmp(copy,secret,sizeof(secret)-1))return 70;close(fd);
        if(stat(target,&before)||(before.st_mode&07777)!=0600||before.st_uid!=getuid())return 71;
        if(stat(key,&before)||(before.st_mode&07777)!=0755)return 72;
    }else{
        if(rc==0||r.verified||r.error==30)return 73;
        int remains=lstat(target,&before)==0;
        int existing=!strcmp(fault,"collision")||!strcmp(fault,"destination_symlink");
        if(remains!=existing)return 74;
        if(r.created&&!r.removed)return 75;
        if(!strcmp(fault,"not_ram")&&source_reads)return 76;
    }
    puts("PRIVATE_HOSTKEY_CONTRACT_OK source_not_chmodded=1 secret_not_logged=1");return 0;
}
