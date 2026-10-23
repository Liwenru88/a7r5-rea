/* 私有认证与原始会话视图；用户对原始系统的修改只记录，不自动回滚。 */
#include "proof.h"
#include "ns_sha256.h"
#include "private_account.h"
#include "config.h"
extern int execve(const char *,char *const[],char *const[]);
extern int fchmod(int,unsigned);
extern int pipe2(int *,int);
struct service_rlimit {unsigned long current,maximum;};
extern int setrlimit(int,const struct service_rlimit *);
static volatile int stopping;
static int ram=-1,observed_changes=0;
/* 新主机密钥只在私有RAM内生成，不依赖旧服务。 */
extern int unlinkat(int,const char *,int),rmdir(const char *);
static int global_claim=-1;
static char passwd_before[8192],nss_before[2048],config_before[8192],mounts_before[65536],mnt_before[80];
static int passwd_length,nss_length,config_length,mounts_length;
static void stop_signal(int number){(void)number;stopping=1;}
static long long milliseconds(void){struct timespec ts;if(clock_gettime(CLOCK_MONOTONIC,&ts))return -1;return ts.tv_sec*1000LL+ts.tv_nsec/1000000;}
static int write_all(int fd,const void *raw,size_t n){const char *p=raw;while(n){ssize_t k=write(fd,p,n);if(k<0&&errno==EINTR)continue;if(k<=0)return -1;p+=k;n-=(size_t)k;}return 0;}
static int read_file(const char *path,char *raw,size_t cap){int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;size_t n=0;while(n<cap){ssize_t k=read(fd,raw+n,cap-n);if(k<0&&errno==EINTR)continue;if(k<0){close(fd);return -1;}if(!k)break;n+=(size_t)k;}char extra;ssize_t more=read(fd,&extra,1);int error=errno;close(fd);if(more!=0){errno=more<0?error:75;return -1;}return (int)n;}
static int text_file(const char *path,char *raw,size_t cap){int n=read_file(path,raw,cap-1);if(n>=0)raw[n]=0;return n;}
static int create_file(const char *path,const void *raw,size_t n){int fd=open(path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(fd<0)return -1;int failed=write_all(fd,raw,n)||fsync(fd);if(close(fd))failed=1;return failed?-1:0;}
static int ram_file(const char *name,const void *raw,size_t n){int fd=openat(ram,name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(fd<0)return -1;int failed=write_all(fd,raw,n)||fsync(fd);if(close(fd))failed=1;return failed?-1:0;}
static int ram_read(const char *name,char *raw,size_t cap){int fd=openat(ram,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;ssize_t n=read(fd,raw,cap);char extra;ssize_t more=n>=0?read(fd,&extra,1):-1;close(fd);return n<0||more!=0?-1:(int)n;}
static int parent_unchanged(void);
static int heartbeat(int child,long long elapsed){char row[256];int n=snprintf(row,sizeof(row),"A7R5_PRIVATE_ALIVE %s parent=%d child=%d ttl=%d elapsed_ms=%lld parent_unchanged=%d changes_observed=%d\n",RUN_ID,getpid(),child,SSH_SECONDS,elapsed,parent_unchanged(),observed_changes);if(n<=0||(size_t)n>=sizeof(row)||ram_file("heartbeat.new",row,(size_t)n))return -1;return renameat(ram,"heartbeat.new",ram,"heartbeat");}
static int mount_view(char raw[65536]){char all[65536];if(text_file("/proc/self/mountinfo",all,sizeof(all))<0)return -1;int used=0;char *line=all;while(*line){char *end=strchr(line,'\n');if(!end)return -1;char *p=line;for(int i=0;i<4;i++){p=strchr(p,' ');if(!p||p>=end)return -1;p++;}char *q=strchr(p,' ');if(!q||q>=end)return -1;size_t n=(size_t)(q-p);if((n==1&&!memcmp(p,"/",1))||(n==4&&!memcmp(p,"/etc",4))||(n==4&&!memcmp(p,"/var",4))||(n==12&&!memcmp(p,"/tmp_network",12))||(n==11&&!memcmp(p,"/etc/passwd",11))||(n==8&&!memcmp(p,"/dev/pts",8))){int count=(int)(end-line)+1;if(used+count>=65536)return -1;memcpy(raw+used,line,(size_t)count);used+=count;}line=end+1;}raw[used]=0;return used;}
static int namespace_name(int pid,char raw[80]){char path[80];snprintf(path,sizeof(path),"/proc/%d/ns/mnt",pid);ssize_t n=readlink(path,raw,79);if(n<=0||n>=79)return -1;raw[n]=0;return 0;}
static int shadow_absent(void){struct stat st;return lstat("/etc/shadow",&st)<0&&errno==ENOENT;}
static int parent_unchanged(void){char data[8192],mounts[65536],ns[80];return shadow_absent()&&read_file("/etc/passwd",data,sizeof(data))==passwd_length&&!memcmp(data,passwd_before,(size_t)passwd_length)&&read_file("/etc/nsswitch.conf",data,sizeof(data))==nss_length&&!memcmp(data,nss_before,(size_t)nss_length)&&read_file("/etc/ssh/sshd_config",data,sizeof(data))==config_length&&!memcmp(data,config_before,(size_t)config_length)&&mount_view(mounts)==mounts_length&&!memcmp(mounts,mounts_before,(size_t)mounts_length)&&!namespace_name(getpid(),ns)&&!strcmp(ns,mnt_before);}
static int owned_children(int signal_number){char path[96],raw[4096];snprintf(path,sizeof(path),"/proc/self/task/%d/children",getpid());int n=text_file(path,raw,sizeof(raw));if(n<0)return -1;int count=0;char *p=raw;while(*p){while(*p==' '||*p=='\n')p++;if(!*p)break;char *end;unsigned long long pid=strtoull(p,&end,10);if(end==p||pid<=1||pid>2147483647||(*end&&*end!=' '&&*end!='\n'))return -1;count++;if(signal_number&&kill((int)pid,signal_number)&&errno!=ESRCH)return -1;p=end;}return count;}
static int cleanup_children(void){int status;for(int i=0;i<60;i++){if(owned_children(i<20?SIGTERM:SIGKILL)<0)return 0;while(waitpid(-1,&status,WNOHANG)>0){}int remain=owned_children(0);if(remain<0)return 0;if(!remain)return 1;usleep(100000);}return 0;}
static int spawn(char *const argv[],int logfd){int parent=getpid(),pid=fork();if(pid)return pid;if(prctl(1,SIGTERM,0UL,0UL,0UL)||getppid()!=parent)_exit(121);if(logfd>=0&&(dup2(logfd,1)<0||dup2(logfd,2)<0))_exit(122);char *const environment[]={"PATH=/bin:/usr/bin:/usr/sbin","LC_ALL=C","HOME=/root",0};execve(argv[0],argv,environment);_exit(123);return -1;}
static int wait_command(int pid,int seconds){long long deadline=milliseconds()+seconds*1000LL;int status;while(milliseconds()<deadline&&!stopping){int n=waitpid(pid,&status,WNOHANG);if(n==pid){errno=0;return status==0?0:1;}if(n<0&&errno!=EINTR)return -1;usleep(50000);}return -1;}
/* 仅客体回环读取SSH标识，不提交凭据；连接和读取共用3秒上限。 */
static int local_banner(char raw[256]){
    extern int socket(int,int,int),connect(int,const void *,unsigned),getsockopt(int,int,int,void *,unsigned *);
    struct {unsigned short family;unsigned char port[2],address[4],zero[8];} address={2,{8,174},{127,0,0,1},{0}};
    int fd=socket(2,1|04000|O_CLOEXEC,0),used=0;long long deadline=milliseconds()+3000;
    if(fd<0)return -1;
    if(connect(fd,&address,sizeof(address))&&errno!=115){close(fd);return -1;}
    struct pollfd event={fd,4,0};int left=(int)(deadline-milliseconds());
    int error=0;unsigned size=sizeof(error);
    if(left<=0||poll(&event,1,left)<=0||getsockopt(fd,1,4,&error,&size)||error){close(fd);return -1;}
    while(used<256){
        left=(int)(deadline-milliseconds());event.events=POLLIN;event.revents=0;
        if(left<=0||poll(&event,1,left)<=0){close(fd);return -1;}
        ssize_t n=read(fd,raw+used,(size_t)(256-used));
        if(n<0&&(errno==EINTR||errno==11))continue;
        if(n<=0){close(fd);return -1;}used+=(int)n;
        for(int i=0;i<used;i++)if(raw[i]=='\n'){
            int length=i+1;close(fd);
            if(length<12||memcmp(raw,"SSH-2.0-",8))return -1;
            for(int j=0;j<i;j++)if((unsigned char)raw[j]<32&&!(j==i-1&&raw[j]=='\r'))return -1;
            errno=0;return length;
        }
    }
    close(fd);return -1;
}
static int port_listening(void){char raw[32768];if(text_file("/proc/net/tcp",raw,sizeof(raw))<0)return -1;char *line=strchr(raw,'\n');if(!line)return -1;line++;while(*line){char *end=strchr(line,'\n');if(!end)return -1;char *colon=strchr(line,':');if(!colon||colon>=end)return -1;char *p=colon+1;while(*p==' ')p++;char *port=strchr(p,':');if(!port||port>=end)return -1;if(end-port>5&&!strncmp(port+1,"08AE",4)){char *remote=strchr(port,' ');if(!remote||remote>=end)return -1;while(*remote==' ')remote++;char *state=strchr(remote,' ');if(!state||state>=end)return -1;while(*state==' ')state++;if(!strncmp(state,"0A",2))return port-p==8&&!strncmp(p,"00000000",8)?1:2;}line=end+1;}return 0;}
static int safe_directory(const char *path,unsigned mode){if(mkdir(path,0700))return -1;int fd=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;struct stat st;int failed=fstat(fd,&st)||!S_ISDIR(st.st_mode)||st.st_uid||fchmod(fd,mode)||fstat(fd,&st)||(st.st_mode&07777)!=mode;close(fd);return failed?-1:0;}
/* 持续排空日志管道，最多保留前4032字节，避免常驻服务填满私有tmpfs。 */
static void drain_log(int input,int output,size_t *kept){
    if(input<0||output<0)return;
    for(int i=0;i<128;i++){
        struct pollfd event={input,POLLIN,0};char raw[512];
        if(poll(&event,1,0)<=0||!(event.revents&(POLLIN|POLLHUP)))return;
        ssize_t n=read(input,raw,sizeof(raw));if(n<=0)return;
        size_t save=*kept<4032?4032-*kept:0;if(save>(size_t)n)save=(size_t)n;
        if(save){if(write_all(output,raw,save))return;*kept+=save;}
    }
}
static void private_child(int notify,int parent){
    int code=0,error=0,sshd=-1,attempted=0,listened=0,clean=0,private_view=0,account_changed=0,banner_verified=0,logfd=-1,logread=-1;size_t kept=0;char modified[8192],copy[8192],pub[512],ns[80],all[65536];
    if(prctl(1,SIGTERM,0UL,0UL,0UL)||getppid()!=parent||prctl(36,1UL,0UL,0UL,0UL)){code=101;goto finish;}
    if(unshare(NEWNS)||mount(0,"/",0,MS_REC_P|MS_PRIVATE_P,0)){code=102;goto finish;}
    if(text_file("/proc/self/mountinfo",all,sizeof(all))<0||strstr(all," shared:")||strstr(all," master:")||strstr(all," propagate_from:")){code=103;goto finish;}
    if(mount("a7r5-private-ssh","/var","tmpfs",MS_NOSUID_P|MS_NODEV_P,"size=4m,mode=0755")){code=104;goto finish;}
    private_view=1;
    {struct statvfs space;if(statvfs("/var",&space)||space.bavail*space.frsize<2097152){code=104;goto finish;}}
    if(safe_directory("/var/empty",0755)||safe_directory("/var/run",0755)||safe_directory("/var/run/sshd",0755)||safe_directory(PRIVATE_DIR,0700)){code=105;goto finish;}
    {int n=private_account(passwd_before,passwd_length,PASSWORD_HASH,modified);if(n<0||create_file(PRIVATE_DIR "/passwd.view",modified,(size_t)n)||mount(PRIVATE_DIR "/passwd.view","/etc/passwd",0,MS_BIND_P,0)||mount(0,"/etc/passwd",0,MS_BIND_P|MS_REMOUNT_P|MS_RDONLY_P,0)){code=106;goto finish;}if(read_file("/etc/passwd",copy,sizeof(copy))!=n||memcmp(copy,modified,(size_t)n)){code=106;goto finish;}int fd=open("/etc/passwd",O_WRONLY|O_NOFOLLOW|O_CLOEXEC);int e=errno;if(fd>=0){close(fd);code=106;goto finish;}if(e!=30){code=106;goto finish;}}
    account_changed=1;
    /* devpts挂载仅在私有子视图内建立；父视图仍持续核对。 */
    {struct stat st;if(lstat("/dev/pts",&st)||!S_ISDIR(st.st_mode)||mount("devpts","/dev/pts","devpts",MS_NOSUID_P|8UL,"mode=0620,ptmxmode=0666")){code=124;goto finish;}}
    {
      int keylog=open(PRIVATE_DIR "/keygen.log",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
      char *args[]={"/usr/bin/ssh-keygen","-q","-t","ecdsa","-b","256","-N","","-f",PRIVATE_DIR "/host_ecdsa",0};
      if(keylog<0){code=109;goto finish;}
      int pid=spawn(args,keylog);int failed=pid<0||wait_command(pid,12);close(keylog);
      struct stat st;int fd=open(PRIVATE_DIR "/host_ecdsa",O_RDONLY|O_NOFOLLOW|O_CLOEXEC|04000);long fs[32];
      if(fd<0){code=109;goto finish;}
      failed=failed||fchmod(fd,0600)||fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_uid||st.st_gid||(st.st_mode&07777)!=0600||st.st_nlink!=1||st.st_size<=0||st.st_size>8192||fstatfs(fd,fs)||fs[0]!=0x01021994;
      close(fd);if(failed){code=109;goto finish;}
      const char ok[]="A7R5_RAM_GENERATED_HOSTKEY verified=1 mode=600 tmpfs=1 private_key_logged=0\n";
      if(ram_file("hostkey-check",ok,sizeof(ok)-1)){code=109;goto finish;}
    }

    if(create_file(PRIVATE_DIR "/sshd_config",SSH_CONFIG,sizeof(SSH_CONFIG)-1)){code=107;goto finish;}
    {logfd=open(PRIVATE_DIR "/sshd.log",O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);if(logfd<0){code=108;goto finish;}
      int pid;
      char *testargs[]={"/usr/sbin/sshd","-t","-f",PRIVATE_DIR "/sshd_config",0};pid=spawn(testargs,logfd);if(pid<0||wait_command(pid,8)){code=110;goto finish;}
      int n=read_file(PRIVATE_DIR "/host_ecdsa.pub",pub,sizeof(pub));if(n<=0||n>=512||ram_file("host-public-key",pub,(size_t)n)||namespace_name(getpid(),ns)||!strcmp(ns,mnt_before)){code=111;goto finish;}
      /* 不检查局域网地址；固定通配监听只尝试启动一次。 */
      if(port_listening()!=0){code=114;goto finish;}
      attempted=1;long long deadline=milliseconds()+SSH_SECONDS*1000LL;
      int logpipe[2];if(pipe2(logpipe,O_CLOEXEC)){code=108;goto finish;}logread=logpipe[0];
      char *args[]={"/usr/sbin/sshd","-D","-e","-f",PRIVATE_DIR "/sshd_config",0};sshd=spawn(args,logpipe[1]);close(logpipe[1]);
      if(sshd<0){code=115;goto finish;}
      long long startup_deadline=milliseconds()+3000;
      while(!stopping&&milliseconds()<startup_deadline){
        drain_log(logread,logfd,&kept);
        int status,n=waitpid(sshd,&status,WNOHANG),listener=port_listening();
        if(n==sshd||n<0){code=116;goto finish;}
        if(listener<0||listener>1){code=117;goto finish;}
        if(listener){listened=1;break;}usleep(50000);
      }
      if(!listened){code=117;goto finish;}
      char banner[256],banner_sha[65];int banner_length=local_banner(banner);
      if(banner_length<=0||ram_file("banner",banner,(size_t)banner_length)){code=120;goto finish;}
      banner_verified=1;sha_bytes(banner,(size_t)banner_length,banner_sha);
      char row[384];int k=snprintf(row,sizeof(row),"A7R5_WILDCARD_STARTED %s pid=%d bind=0.0.0.0:2222 listener_observed=1 banner_sha=%s\n",RUN_ID,sshd,banner_sha);
      if(k<=0||(size_t)k>=sizeof(row)||ram_file("started",row,(size_t)k)){code=120;goto finish;}
      k=snprintf(row,sizeof(row),"PRIVATE_READY child=%d namespace=%s\n",getpid(),ns);if(write_all(notify,row,(size_t)k)){code=112;goto finish;}close(notify);notify=-1;
      while(!stopping&&(SSH_SECONDS==0||milliseconds()<deadline)){
        drain_log(logread,logfd,&kept);
        int status,n=waitpid(sshd,&status,WNOHANG);if(n==sshd||n<0){code=116;break;}
        if(port_listening()!=1){code=117;break;}
        usleep(1000000);
      }
      if(!attempted&&!code)code=118;
    }
finish:
    error=code?errno:0;clean=cleanup_children();if(!clean)code=119;
    drain_log(logread,logfd,&kept);if(logread>=0)close(logread);if(logfd>=0)close(logfd);
    if(private_view){char log[4096];int n=read_file(PRIVATE_DIR "/sshd.log",log,sizeof(log));if(n>=0)ram_file("diagnostic",log,(size_t)n);}
    {char row[512];int k=snprintf(row,sizeof(row),"PRIVATE_RESULT code=%d errno=%d sshd_attempted=%d listener_observed=%d children_reaped=%d private_account_changed=%d local_banner_verified=%d\n",code,error,attempted,listened,clean,account_changed,banner_verified);ram_file("child-result",row,(size_t)k);}
    if(notify>=0){char row[80];int k=snprintf(row,sizeof(row),"PRIVATE_FAILED code=%d errno=%d\n",code,error);write_all(notify,row,(size_t)k);close(notify);}
    _exit(code?1:0);
}
static int snapshot(void){passwd_length=read_file("/etc/passwd",passwd_before,sizeof(passwd_before));nss_length=read_file("/etc/nsswitch.conf",nss_before,sizeof(nss_before));config_length=read_file("/etc/ssh/sshd_config",config_before,sizeof(config_before));mounts_length=mount_view(mounts_before);if(!shadow_absent()||passwd_length<=0||nss_length<=0||config_length<=0||mounts_length<=0||namespace_name(getpid(),mnt_before))return -1;char sha[65];sha_bytes(passwd_before,(size_t)passwd_length,sha);return strcmp(sha,EXPECTED_PASSWD_SHA)?-1:0;}
static int prepare_ram(void){extern int fstatfs(int,void *);struct stat initial;if(lstat("/tmp_network",&initial)||!S_ISDIR(initial.st_mode))return -1;int fd=open("/tmp_network",O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return -1;long fs[32];struct stat st;if(fstatfs(fd,fs)||fs[0]!=0x01021994||fstat(fd,&st)||st.st_uid||!S_ISDIR(st.st_mode)||((st.st_mode&07777)!=01777&&(st.st_mode&07777)!=0755&&(st.st_mode&07777)!=0700)){close(fd);return -1;}if(mkdirat(fd,RAM_NAME,0700)){close(fd);return -1;}ram=openat(fd,RAM_NAME,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);close(fd);return ram<0?-1:0;}
static int close_inherited(int keep){DIR *d=opendir("/proc/self/fd");if(!d)return -1;int owner=dirfd(d),fds[256],count=0;struct dirent *item;while((item=readdir(d))){char *end;unsigned long long fd=strtoull(item->d_name,&end,10);if(end==item->d_name||*end||fd<=2||fd==(unsigned)owner||fd==(unsigned)keep)continue;if(fd>1048576||count==256){closedir(d);return -1;}fds[count++]=(int)fd;}closedir(d);for(int i=0;i<count;i++)close(fds[i]);return 0;}
static void supervisor(int notify){
    int code=0,child=-1,reaped=0;char reply[512];
    if(setsid()<0||prctl(36,1UL,0UL,0UL,0UL)||close_inherited(notify))_exit(80);
    int nullfd=open("/dev/null",O_RDWR|O_CLOEXEC);if(nullfd<0)_exit(80);for(int i=0;i<3;i++)if(dup2(nullfd,i)<0)_exit(80);close(nullfd);
    /* root_once限制的是安装脚本输出；后台SFTP文件不能继承其32KiB文件上限。 */
    const struct service_rlimit unlimited={~0UL,~0UL},no_core={0,0};
    if(setrlimit(1,&unlimited)||setrlimit(4,&no_core))_exit(80);
    signal(SIGTERM,stop_signal);signal(2,stop_signal);signal(1,stop_signal);
    if(snapshot()||prepare_ram()){code=81;goto finish;}
    if(mkdir("/tmp_network/a7r5-libjit-ssh.active",0700)){code=94;goto finish;}
    global_claim=open("/tmp_network/a7r5-libjit-ssh.active",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(global_claim<0){code=94;goto finish;}
    if(origin_capture(ram)){code=93;goto finish;}
    if(owned_children(0)!=0){code=82;goto finish;}
    {int pair[2];if(pipe(pair)){code=83;goto finish;}int parent=getpid();child=fork();if(child<0){close(pair[0]);close(pair[1]);code=83;goto finish;}if(!child){close(pair[0]);close(notify);private_child(pair[1],parent);}
     close(pair[1]);struct pollfd wait={pair[0],POLLIN|POLLHUP,0};int ok=poll(&wait,1,30000);ssize_t n=ok>0?read(pair[0],reply,sizeof(reply)-1):-1;close(pair[0]);if(n<=0){code=84;goto finish;}reply[n]=0;if(strncmp(reply,"PRIVATE_READY ",14)||!parent_unchanged()){code=85;goto finish;}
     char row[768],pub[512],pub_sha[65],child_ns[80];int pub_n=ram_read("host-public-key",pub,sizeof(pub));if(pub_n<=0||namespace_name(child,child_ns)||!strcmp(child_ns,mnt_before)){code=86;goto finish;}sha_bytes(pub,(size_t)pub_n,pub_sha);
     int k=snprintf(row,sizeof(row),"A7R5_PRIVATE_READY %s parent=%d child=%d uid=%u euid=%u ttl=%d parent_unchanged=1 private_account_changed=1 parent_ns=%s child_ns=%s host_public_sha=%s\n",RUN_ID,getpid(),child,getuid(),geteuid(),SSH_SECONDS,mnt_before,child_ns,pub_sha);if(k<=0||(size_t)k>=sizeof(row)||ram_file("ready",row,(size_t)k)||heartbeat(child,0)||write_all(notify,"READY\n",6)){code=86;goto finish;}close(notify);notify=-1;
     long long start=milliseconds(),deadline=start+(SSH_SECONDS+5)*1000LL,stop_deadline=0;
     while(!stopping&&(SSH_SECONDS==0||milliseconds()<deadline)){
        int status,n=waitpid(child,&status,WNOHANG);
        if(n==child){reaped=1;if(status)code=87;break;}
        if(n<0){code=88;break;}
        /* 原始视图中的用户写入只记录，不回滚、不冒充原件未变。 */
        if(!parent_unchanged())observed_changes=1;
        if(!stop_deadline){
            char request[64];int count=ram_read("stop-request",request,sizeof(request));
            if(count==(int)sizeof(RUN_ID)-1&&!memcmp(request,RUN_ID,sizeof(RUN_ID)-1)){
                if(kill(child,SIGTERM)){code=92;break;}
                stop_deadline=milliseconds()+8000;
            }else if(count>=0||errno!=ENOENT){code=92;break;}
        }else if(milliseconds()>=stop_deadline){code=92;break;}
        if(heartbeat(child,milliseconds()-start)){code=91;break;}
        usleep(1000000);
     }
    }
finish:
    {int clean=cleanup_children();int parent_ok=ram>=0&&parent_unchanged();int listener=port_listening();if(!parent_ok)observed_changes=1;if(!clean||listener!=0)code=90;
     char row[512];int k=snprintf(row,sizeof(row),"A7R5_PRIVATE_RESULT %s code=%d parent_unchanged=%d child_tree_reaped=%d child_terminal_seen=%d listener_absent=%d changes_observed=%d\n",RUN_ID,code,parent_ok,clean,reaped,listener==0,observed_changes);if(ram>=0)ram_file("result",row,(size_t)k);
     if(ram>=0){const char ended[]="A7R5_PRIVATE_ENDED\n";if(!ram_file("heartbeat.new",ended,sizeof(ended)-1))renameat(ram,"heartbeat.new",ram,"heartbeat");}
     if(global_claim>=0){close(global_claim);if(clean&&listener==0)rmdir("/tmp_network/a7r5-libjit-ssh.active");}
     if(notify>=0){write_all(notify,row,(size_t)k);close(notify);}_exit(code?1:0);}
}
static int request_stop(void){
    ram=open("/tmp_network/" RAM_NAME,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
    if(ram<0)return 70;
    struct stat st;if(fstat(ram,&st)||st.st_uid||!S_ISDIR(st.st_mode)||(st.st_mode&07777)!=0700){close(ram);return 70;}
    if(ram_file("stop-request",RUN_ID,sizeof(RUN_ID)-1)){close(ram);return 71;}
    long long deadline=milliseconds()+16000;char data[512];
    while(milliseconds()<deadline){int n=ram_read("result",data,sizeof(data));if(n>0){char expected[512];int matched=0;for(int changed=0;changed<2;changed++)for(int same=0;same<2;same++){int count=snprintf(expected,sizeof(expected),"A7R5_PRIVATE_RESULT " RUN_ID " code=0 parent_unchanged=%d child_tree_reaped=1 child_terminal_seen=1 listener_absent=1 changes_observed=%d\n",same,changed);if(count==n&&!memcmp(data,expected,(size_t)n)&&(!changed?same:1))matched=1;}write_all(1,data,(size_t)n);close(ram);return matched?0:73;}usleep(100000);}
    close(ram);return 72;
}
int main(int argc,char **argv){
    if(argc!=2||getuid()||geteuid())return 64;
    if(!strcmp(argv[1],"--stop"))return request_stop();
    if(strcmp(argv[1],"--launch-original"))return 64;
    char baseline[513];if(read_file("/etc/ld.so.preload",baseline,sizeof(baseline))!=512)return 125;
    for(int i=0;i<512;i++)if(baseline[i]!='\n')return 125;
    int pair[2];if(pipe(pair))return 65;int pid=fork();if(pid<0)return 66;
    if(!pid){close(pair[0]);supervisor(pair[1]);}
    close(pair[1]);struct pollfd event={pair[0],POLLIN|POLLHUP,0};int ok=poll(&event,1,35000);
    char raw[512];ssize_t n=ok>0?read(pair[0],raw,sizeof(raw)-1):-1;close(pair[0]);
    if(n<=0){kill(pid,SIGTERM);return 67;}raw[n]=0;
    if(strcmp(raw,"READY\n")){write_all(1,raw,(size_t)n);return 68;}
    const char ready[]="A7R5_LIBJIT_SSH_LAUNCH " RUN_ID " READY\n";
    return write_all(1,ready,sizeof(ready)-1)?69:0;
}
