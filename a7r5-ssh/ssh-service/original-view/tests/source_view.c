/* 仅QEMU：构造旧SSH私有/var，启动器切回原始/var后源路径不可见。 */
#include "../../../src/ns_abi.h"
extern int execve(const char *,char *const[],char *const[]);
extern int fchmod(int,unsigned),symlink(const char *,const char *),unlink(const char *);
int main(int argc,char **argv){
    const char *directory="/var/run/a7r5-ssh-5e551f1a97774fa1885f15799583d09b";
    struct stat st;if(!lstat(directory,&st))return 104;
    if((argc!=2&&argc!=3)||unshare(NEWNS)||mount(0,"/",0,MS_REC_P|MS_PRIVATE_P,0)||mount("fixture-source","/var","tmpfs",0,"mode=0755")||mkdir("/var/run",0755)||mkdir(directory,0700))return 101;
    int in=open("/simulation/host_ecdsa",O_RDONLY|O_CLOEXEC),dir=open(directory,O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    int out=dir<0?-1:openat(dir,"host_ecdsa",O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);
    char raw[8192];ssize_t n=in<0?-1:read(in,raw,sizeof(raw));
    if(out<0||n<=0||fstat(in,&st)||!S_ISREG(st.st_mode)||write(out,raw,(size_t)n)!=n)return 102;
    if(argc==3){
        if(!strcmp(argv[2],"mode")){if(fchmod(out,0644))return 105;}
        else if(!strcmp(argv[2],"size")){if(write(out,"x",1)!=1)return 105;}
        else if(!strcmp(argv[2],"directory")){if(fchmod(dir,0755))return 105;}
        else if(!strcmp(argv[2],"link")){if(unlink("/var/run/a7r5-ssh-5e551f1a97774fa1885f15799583d09b/host_ecdsa")||symlink("/simulation/host_ecdsa","/var/run/a7r5-ssh-5e551f1a97774fa1885f15799583d09b/host_ecdsa"))return 105;}
        else return 106;
    }
    if(close(out)||close(in)||close(dir))return 102;
    char *args[]={argc==3?argv[1]:"/bin/sh",argc==3?"--launch-from-proof":argv[1],0};char *env[]={"PATH=/bin:/sbin:/usr/bin:/usr/sbin","LC_ALL=C",0};
    execve(args[0],args,env);return 103;
}
