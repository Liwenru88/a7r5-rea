/* 认证成功后唯一的用户执行入口；失败不回退，标准FD与PTY保持原样。 */
#include "proof.h"
extern int execve(const char *,char *const[],char *const[]);
int main(int argc,char **argv){
    (void)argv;if(argc!=1||origin_enter()){
        char error[160];int n=snprintf(error,sizeof(error),"A7R5_ORIGINAL_VIEW_REFUSED stage=%d errno=%d: no user command executed\n",origin_failure,origin_error);write(2,error,(size_t)n);return 126;
    }
    char term[256];char *type=getenv("TERM");
    char *environment[]={"PATH=/bin:/sbin:/usr/bin:/usr/sbin","HOME=/","LC_ALL=C","USER=root","LOGNAME=root",0,0};
    if(type&&strlen(type)<240){int valid=1;for(char *p=type;*p;p++)if((unsigned char)*p<32||(unsigned char)*p>126)valid=0;if(valid){snprintf(term,sizeof(term),"TERM=%s",type);environment[5]=term;}}
    char *command=getenv("SSH_ORIGINAL_COMMAND");
    if(command&&!strcmp(command,SFTP_PATH)){
        char *args[]={SFTP_PATH,0};execve(args[0],args,environment);
    }else if(command){
        char *args[]={"/bin/sh","-c",command,0};execve(args[0],args,environment);
    }else{
        /* 使用普通sh，避免login shell读取全局profile改变libJit基础环境。 */
        char *args[]={"/bin/sh",0};execve(args[0],args,environment);
    }
    const char error[]="A7R5_ORIGINAL_VIEW_EXEC_FAILED\n";write(2,error,sizeof(error)-1);return 127;
}
