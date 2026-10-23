/* 静态安装/回滚/中和工具；不启停现有SSH，不读取密钥。 */
#include "common.h"
static int stage,etc=-1,net=-1;
static const char neutral[512]={[0 ... 511]='\n'};
static int say(const char *text){return write(1,text,strlen(text))==(ssize_t)strlen(text)?0:-1;}
static int refuse(void){char out[4];unsigned n=(unsigned)stage;int used=0;if(n>=100)out[used++]=(char)('0'+n/100);if(n>=10)out[used++]=(char)('0'+n/10%10);out[used++]=(char)('0'+n%10);say("A7R5_NET_REFUSED1 " NET_ID " stage=");write(1,out,(size_t)used);say("\n");clear_buffer();return stage?stage:99;}
static int pointer(void){int n=get(etc,"ld.so.preload",net_buffer,sizeof(net_buffer));int kind=n==512&&!memcmp(net_buffer,neutral,512)?0:n==(int)sizeof(OLD_PRELOAD)-1&&!memcmp(net_buffer,OLD_PRELOAD,sizeof(OLD_PRELOAD)-1)?1:n==(int)sizeof(NEW_PRELOAD)-1&&!memcmp(net_buffer,NEW_PRELOAD,sizeof(NEW_PRELOAD)-1)?2:-1;clear_buffer();return kind;}
static int copy(int from,const char *name,int to,const char *dest){int n=get(from,name,net_buffer,sizeof(net_buffer));if(n<1)return -1;unsigned char local[65536];memcpy(local,net_buffer,(size_t)n);clear_buffer();int rc=store(to,dest,local,(size_t)n);volatile unsigned char *p=local;for(size_t i=0;i<sizeof(local);i++)p[i]=0;return rc;}
static int permissions(int dir,const char *name,unsigned wanted,int readable){int fd=openat(dir,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|NET_NONBLOCK);struct stat st;int ok=root_file(fd)&&!fchmod(fd,wanted)&&!fstat(fd,&st)&&(readable?(st.st_mode&0004):(st.st_mode&0100));if(fd>=0)close(fd);return ok;}
static int namespace_is_active(void){char raw[96];ssize_t n=readlink(PROC_SELF_NS,raw,sizeof(raw));return n==(ssize_t)sizeof(ACTIVE_NS)-1&&!memcmp(raw,ACTIVE_NS,sizeof(ACTIVE_NS)-1);}
static int lock(void){return mkdirat(etc,".a7r5-preload-edit.lock",0700);}
static int unlock(void){return unlinkat(etc,".a7r5-preload-edit.lock",NET_REMOVEDIR);}
static int install(void){
    stage=10;if(pointer()!=1||!absent(etc,NET_NAME))return refuse();
    stage=11;int old=open(HELPER_DIR,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(!root_dir(old,0)||!contents(old,"enabled",OLD_ID "\n",sizeof(OLD_ID))||!hashed(old,"boot.so",OLD_HOOK_SHA)||!hashed(old,"ssh-service.arm64",HELPER_SHA)){if(old>=0)close(old);return refuse();}close(old);
    stage=12;int source=open(STAGE_DIR,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(!root_dir(source,0700)||!ram_dir(source)||!hashed(source,"network.so",HOOK_SHA)){if(source>=0)close(source);return refuse();}
    stage=13;int ram=open(SERVICE_RAM,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(!root_dir(ram,0700)||!hashed(ram,"ready",READY_SHA)||!hashed(ram,"host-public-key",PUBLIC_SHA)||!namespace_is_active()){if(ram>=0)close(ram);close(source);return refuse();}close(ram);
    stage=14;long fs[32];memset(fs,0,sizeof(fs));if(NET_FSTATFS(etc,fs)||fs[1]<=0||fs[1]>1048576||fs[4]<262144/fs[1]+1||lock()){close(source);return refuse();}
    stage=15;if(mkdirat(etc,NET_NAME,0755)){close(source);return refuse();}net=openat(etc,NET_NAME,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(!root_dir(net,0)||fchmod(net,0755))return refuse();
    stage=16;if(copy(source,"network.so",net,"network.so")||store(net,"preload.previous",OLD_PRELOAD,sizeof(OLD_PRELOAD)-1)||!permissions(net,"network.so",0644,1)){close(source);return refuse();}close(source);
    /* /proc/self/exe是内核提供的固定链接；跟随后仍校验真实文件的所有者和类型。 */
    stage=17;int self=open(SELF_EXE,O_RDONLY|O_CLOEXEC);unsigned char code[65536];int n=root_file(self)?bounded(self,code,sizeof(code)):-1;if(self>=0)close(self);if(n<1||store(net,"control.static",code,(size_t)n)||!permissions(net,"control.static",0700,0)){memset(code,0,sizeof(code));return refuse();}memset(code,0,sizeof(code));
    stage=18;int network=open(RAM_PARENT,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(!ram_dir(network)||mkdirat(network,CLAIM_NAME,0700)){if(network>=0)close(network);return refuse();}int claim=openat(network,CLAIM_NAME,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);close(network);if(!root_dir(claim,0700)||store(claim,"suppressed-active-service",SERVICE_RUN "\n",sizeof(SERVICE_RUN))){if(claim>=0)close(claim);return refuse();}close(claim);
    stage=19;if(store(net,"enabled",NET_ID "\n",sizeof(NET_ID))||store(etc,PRELOAD_NEW,NEW_PRELOAD,sizeof(NEW_PRELOAD)-1)||NET_SYNCFS(etc))return refuse();
    stage=20;if(pointer()!=1||!contents(net,"enabled",NET_ID "\n",sizeof(NET_ID))||!hashed(net,"network.so",HOOK_SHA))return refuse();
    stage=21;if(NET_RENAME(etc,PRELOAD_NEW,etc,"ld.so.preload")||NET_SYNCFS(etc)||pointer()!=2)return refuse();
    stage=22;if(unlock())return refuse();
    return say("A7R5_NET_INSTALLED1 " NET_ID " current_boot_suppressed=1 service_preserved=1 rebooted=0\n");
}
static int restore(int rollback){
    stage=30;int before=pointer();if(before<0||(rollback&&before!=1&&before!=2))return refuse();
    if(rollback){
        stage=29;int old=open(HELPER_DIR,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
        int valid=root_dir(old,0)&&contents(old,"enabled",OLD_ID "\n",sizeof(OLD_ID))&&hashed(old,"boot.so",OLD_HOOK_SHA)&&hashed(old,"ssh-service.arm64",HELPER_SHA);
        if(old>=0)close(old);if(!valid)return refuse();
    }
    if((rollback&&before==1)||(!rollback&&before==0))return say(rollback?"A7R5_NET_ROLLED_BACK1 " NET_ID " service_preserved=1\n":"A7R5_NET_NEUTRAL1 " NET_ID " service_preserved=1\n");
    stage=31;if(lock())return refuse();
    /* 目录或marker损坏也必须能恢复已知指针；不依赖新库及helper。 */
    net=open(NET_DIR,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(root_dir(net,0)&&contents(net,"enabled",NET_ID "\n",sizeof(NET_ID))&&absent(net,"disabled")){
        stage=32;if(NET_RENAME(net,"enabled",net,"disabled")||NET_SYNCFS(etc))return refuse();
    }
    const char *bytes=rollback?OLD_PRELOAD:neutral;size_t size=rollback?sizeof(OLD_PRELOAD)-1:sizeof(neutral);
    stage=33;if(store(etc,PRELOAD_RESTORE,bytes,size))return refuse();
    stage=34;if(pointer()!=before||NET_RENAME(etc,PRELOAD_RESTORE,etc,"ld.so.preload")||NET_SYNCFS(etc)||pointer()!=(rollback?1:0))return refuse();
    stage=35;if(unlock())return refuse();
    return say(rollback?"A7R5_NET_ROLLED_BACK1 " NET_ID " service_preserved=1\n":"A7R5_NET_NEUTRAL1 " NET_ID " service_preserved=1\n");
}
int main(int argc,char **argv){stage=1;if(argc!=2||getuid()!=NET_OWNER||geteuid()!=NET_OWNER)return refuse();etc=open(ETC_ROOT,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);stage=2;if(!root_dir(etc,0))return refuse();
    if(!strcmp(argv[1],"install"))return install();
    if(!strcmp(argv[1],"rollback"))return restore(1);
    if(!strcmp(argv[1],"neutralize"))return restore(0);
    if(!strcmp(argv[1],"inspect")){stage=3;int kind=pointer();return kind<0?refuse():say(kind==2?"A7R5_NET_INSPECT1 " NET_ID " preload=network\n":kind==1?"A7R5_NET_INSPECT1 " NET_ID " preload=previous\n":"A7R5_NET_INSPECT1 " NET_ID " preload=neutral\n");}
    return refuse();
}
