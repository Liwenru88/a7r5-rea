/* 执行生产控制目录校验；仅替换Linux ABI，不接触设备。 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
typedef long s64;
typedef unsigned long u64;
#define P(x) ((s64)(x))
#define RDONLY 0
#define NOFOLLOW 32768
#define CLOEXEC 524288
#define AT_FDCWD_TEST -100
#undef AT_FDCWD
#define AT_FDCWD AT_FDCWD_TEST
static const char *parent_path,*control_path;
#define CAPTURE_CONTROL_PARENT parent_path
#define CAPTURE_CONTROL_DIR control_path
static int fault,opens,closes,stats;
static int same(const char *a,const char *b,u64 n){return !memcmp(a,b,n);}
static s64 open_file(const char *path,int flags){
    if(flags!=(RDONLY|16384|NOFOLLOW|CLOEXEC))return -EPERM;
    opens++;int fd=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    return fd<0?-errno:fd;
}
static s64 close_fd(s64 fd){closes++;int rc=close((int)fd);return rc<0||fault==6?-EIO:0;}
static s64 sc(s64,s64,s64,s64,s64,s64,s64);
#include "capture_control.h"
static s64 sc(s64 n,s64 a,s64 b,s64 c,s64 d,s64 e,s64 f){
    (void)d;(void)e;(void)f;
    if(n==78){const char *ns=(fault==8&&!strcmp((const char *)b,"/proc/1/ns/mnt"))?"mnt:[2]":"mnt:[1]";
        memcpy((void *)c,ns,7);return 7;}
    if(n==44){s64 *fs=(void *)b;memset(fs,0,15*sizeof(*fs));
        fs[0]=(fault==1||fault==12||(fault==2&&opens==2))?0x4d44:0x01021994;
        fs[10]=fault==9?1:0;return 0;}
    if(n==80){struct stat source;struct control_stat *st=(void *)b;
        if(fault==5||fstat((int)a,&source))return -EIO;
        memset(st,0,sizeof(*st));stats++;st->mode=source.st_mode;
        st->uid=fault==7?501:0;st->dev=(u64)source.st_dev+(fault==3&&stats==2);return 0;}
    if(n==34){
        if(a!=AT_FDCWD||strcmp((const char *)b,control_path)||c!=0700)return -EPERM;
        return mkdir((const char *)b,0700)<0?-errno:0;
    }
    return -ENOSYS;
}
int main(int argc,char **argv){
    if(argc!=4)return 2;parent_path=argv[1];control_path=argv[2];sscanf(argv[3],"%d",&fault);
    int ready=fault>=10&&fault<=12?(capture_control_parent_ready()&&capture_control_create()):capture_control_ready();
    printf("ready=%d opens=%d closes=%d\n",ready,opens,closes);return 0;
}
