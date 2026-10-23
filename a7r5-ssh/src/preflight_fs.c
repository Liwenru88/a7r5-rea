/* AArch64 glibc 2.25 statvfs 布局；只查询空间，不挂载或修复文件系统。 */
typedef unsigned long size_t;
typedef long ssize_t;
struct a7r5_statvfs { unsigned long bsize,frsize,blocks,bfree,bavail,files,ffree,favail,fsid,flag,namemax; int spare[6]; };
extern int statvfs(const char *,struct a7r5_statvfs *),snprintf(char *,size_t,const char *,...);
extern ssize_t write(int,const void *,size_t);
extern int *__errno_location(void);
int ssh_preflight_fs(int fd) {
    const char *paths[]={"/tmp_network","/tmp/jiritsu","/etc"};
    for(int i=0;i<3;i++) {
        struct a7r5_statvfs st; char line[256];
        int rc=statvfs(paths[i],&st),error=rc?*__errno_location():0;
        int n=rc?snprintf(line,sizeof(line),"FS_SPACE %s errno=%d\n",paths[i],error):
            snprintf(line,sizeof(line),"FS_SPACE %s available_bytes=%lu fragment_bytes=%lu\n",paths[i],st.bavail*st.frsize,st.frsize);
        if(n<=0 || (size_t)n>=sizeof(line) || write(fd,line,(size_t)n)!=n)return -1;
    }
    return 0;
}
