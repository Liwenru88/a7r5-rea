/* 无 SSH、无账户字段修改：私有挂载能力验证与有界网络元数据观察。 */
#include "ns_abi.h"
#include "ns_sha256.h"
#include "ns_config.h"

/* 继承固定执行器32KiB的RLIMIT_FSIZE，不提高权限或放宽原限制。 */
#define TRACE_LIMIT 32768
static volatile int stopping;
static int stage_error;
static int ram_fd=-1;
static char original_passwd[8192],original_mounts[65536],original_ns[80],original_net[80];
static int passwd_n,mount_n;
static unsigned network_mode;
static void stop_signal(int ignored){(void)ignored;stopping=1;}
static long long now_ms(void){struct timespec ts;if(clock_gettime(CLOCK_MONOTONIC,&ts))return -1;return ts.tv_sec*1000LL+ts.tv_nsec/1000000;}
static int wr(int fd,const void *data,size_t n){const char *p=data;while(n){ssize_t k=write(fd,p,n);if(k<0&&errno==EINTR)continue;if(k<=0)return -1;p+=k;n-=(size_t)k;}return 0;}
static int get_file(const char *path,char *out,size_t cap){int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return -1;size_t used=0;while(used<cap){ssize_t n=read(fd,out+used,cap-used);if(n<0&&errno==EINTR)continue;if(n<0){int e=errno;close(fd);errno=e;return -1;}if(!n)break;used+=(size_t)n;}char extra;ssize_t extra_n=read(fd,&extra,1);int e=errno;close(fd);if(extra_n!=0){errno=extra_n<0?e:75;return -1;}return (int)used;}
static int text_file(const char *path,char *out,size_t cap){int n=get_file(path,out,cap-1);if(n>=0)out[n]=0;return n;}
static const char *ram_name(const char *path){size_t n=strlen(RUN_DIR);if(!strncmp(path,RUN_DIR,n)&&path[n]=='/'&&path[n+1]&&!strchr(path+n+1,'/'))return path+n+1;return 0;}
static int create_file(const char *path,const void *raw,size_t n){const char *name=ram_name(path);int flags=O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW;int fd=name?(ram_fd<0?-1:openat(ram_fd,name,flags,0600)):open(path,flags,0600);if(fd<0)return -1;int failed=wr(fd,raw,n)||fsync(fd);if(close(fd))failed=1;return failed?-1:0;}
static int atomic_file(const char *path,const void *raw,size_t n){char temporary[512];int k=snprintf(temporary,sizeof(temporary),"%s.new",path);if(k<0||(size_t)k>=sizeof(temporary)||create_file(temporary,raw,n))return -1;const char *old=ram_name(temporary),*new_name=ram_name(path);return old&&new_name?renameat(ram_fd,old,ram_fd,new_name):rename(temporary,path);}
static int directory(const char *path,unsigned *mode){int fd=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;struct stat st;int ok=!fstat(fd,&st)&&S_ISDIR(st.st_mode)&&st.st_uid==geteuid();close(fd);if(!ok)return -1;*mode=st.st_mode&07777;return 0;}
static int ns_name(const char *kind,char out[80]){
#ifdef NS_HOST_TEST
    return snprintf(out,80,"%s:host-fixture",kind)<0?-1:0;
#else
    char path[128];snprintf(path,sizeof(path),"/proc/self/ns/%s",kind);ssize_t n=readlink(path,out,79);if(n<0&&errno==ENOENT){snprintf(out,80,"%s:unavailable",kind);return 0;}if(n<=0||n>=79)return -1;out[n]=0;return 0;
#endif
}
static unsigned long long start_ticks(int pid){
#ifdef NS_HOST_TEST
    return (unsigned long long)pid;
#else
    char path[80],raw[4096];snprintf(path,sizeof(path),"/proc/%d/stat",pid);if(text_file(path,raw,sizeof(raw))<0)return 0;char *p=strrchr(raw,')');if(!p)return 0;p++;for(int field=3;field<22;field++){while(*p==' ')p++;while(*p&&*p!=' ')p++;}while(*p==' ')p++;char *end;unsigned long long ticks=strtoull(p,&end,10);return end==p?0:ticks;
#endif
}
static int relevant_mounts(char out[65536]){
#ifdef NS_HOST_TEST
    return text_file(TEST_MOUNTS,out,65536);
#else
    char raw[65536];int n=text_file("/proc/self/mountinfo",raw,sizeof(raw));if(n<0)return -1;int used=0;char *line=raw;while(*line){char *end=strchr(line,'\n');if(!end)return -1;char *p=line;for(int i=0;i<4;i++){p=strchr(p,' ');if(!p||p>=end)return -1;p++;}char *q=strchr(p,' ');if(!q||q>=end)return -1;size_t len=(size_t)(q-p);if((len==1&&!memcmp(p,"/",1))||(len==4&&!memcmp(p,"/var",4))||(len==4&&!memcmp(p,"/etc",4))||(len==12&&!memcmp(p,"/tmp_network",12))||(len==11&&!memcmp(p,"/etc/passwd",11))){int count=(int)(end-line)+1;if(used+count>=65536)return -1;memcpy(out+used,line,(size_t)count);used+=count;}line=end+1;}out[used]=0;return used;
#endif
}
static int parent_unchanged(void){
#ifdef NS_HOST_TEST
    if(TEST_FAILURE==73)return 0;
#endif
    char raw[8192],mounts[65536],mnt[80],net[80];unsigned mode;int n=get_file(PASSWD_PATH,raw,sizeof(raw));if(n!=passwd_n||memcmp(raw,original_passwd,(size_t)passwd_n)||relevant_mounts(mounts)!=mount_n||memcmp(mounts,original_mounts,(size_t)mount_n)||ns_name("mnt",mnt)||strcmp(mnt,original_ns)||ns_name("net",net)||strcmp(net,original_net)||directory(RAM_PARENT,&mode)||mode!=network_mode)return 0;struct stat st;if(!lstat(MARKER_PATH,&st)||errno!=ENOENT)return 0;return 1;}
static int no_shared_mounts(void){
#ifdef NS_HOST_TEST
    return 1;
#else
    char raw[65536];if(text_file("/proc/self/mountinfo",raw,sizeof(raw))<0)return 0;return !strstr(raw," shared:")&&!strstr(raw," master:")&&!strstr(raw," propagate_from:");
#endif
}
static int fail_step(int step){
#ifdef NS_HOST_TEST
    if(TEST_FAILURE==step){errno=1;return 1;}
#else
    (void)step;
#endif
    return 0;
}
struct child_note { int code,error;char mnt[80],net[80]; };
static void child(int notify,int parent){struct child_note note;memset(&note,0,sizeof(note));int code=0;errno=0;
#ifndef NS_HOST_TEST
    if(prctl(1,SIGKILL,0UL,0UL,0UL)||getppid()!=parent){code=60;goto finished;}
#else
    (void)parent;
#endif
    if(fail_step(61)){code=61;goto finished;}
#ifndef NS_HOST_TEST
    if(unshare(NEWNS)){code=61;goto finished;}
    if(fail_step(62)||mount(0,"/",0,MS_REC_P|MS_PRIVATE_P,0)){code=62;goto finished;}
#else
    if(fail_step(62)){code=62;goto finished;}
#endif
    if(!no_shared_mounts()){code=63;goto finished;}
    if(fail_step(64)){code=64;goto finished;}
#ifndef NS_HOST_TEST
    if(mount("a7r5-ns-probe",VAR_PATH,"tmpfs",MS_NOSUID_P|MS_NODEV_P,"size=4m,mode=0755")){code=64;goto finished;}
#endif
    if(fail_step(65)||create_file(PRIVATE_PASSWD,original_passwd,(size_t)passwd_n)){code=65;goto finished;}
    if(fail_step(66)){code=66;goto finished;}
#ifndef NS_HOST_TEST
    if(mount(PRIVATE_PASSWD,PASSWD_PATH,0,MS_BIND_P,0)){code=66;goto finished;}
#endif
    if(fail_step(67)){code=67;goto finished;}
#ifndef NS_HOST_TEST
    if(mount(0,PASSWD_PATH,0,MS_BIND_P|MS_REMOUNT_P|MS_RDONLY_P,0)){code=67;goto finished;}
    {int test=open(PASSWD_PATH,O_WRONLY|O_CLOEXEC|O_NOFOLLOW);int error=errno;if(test>=0){close(test);errno=0;code=68;goto finished;}if(error!=30){errno=error;code=68;goto finished;}errno=0;}
#endif
    {char copy[8192];int n=get_file(PASSWD_PATH,copy,sizeof(copy));if(n!=passwd_n||memcmp(copy,original_passwd,(size_t)passwd_n)){code=68;goto finished;}}
    if(fail_step(69)||create_file(PRIVATE_MARKER,"private-mount-proof\n",20)){code=69;goto finished;}
    if(ns_name("mnt",note.mnt)||ns_name("net",note.net)){code=70;goto finished;}
#ifdef NS_HOST_TEST
    snprintf(note.mnt,sizeof(note.mnt),"mnt:private-fixture");
#endif
    if(!strcmp(note.mnt,original_ns)||strcmp(note.net,original_net)){code=70;goto finished;}
finished:
    note.code=code;note.error=code?errno:0;
    if(wr(notify,&note,sizeof(note))){close(notify);_exit(71);}close(notify);
    if(code)_exit(code);
#ifdef NS_HOST_TEST
    if(TEST_FAILURE==74)_exit(74);
#endif
    /* 无 exec、无后代；只维持已验证的私有挂载，父进程负责截止和回收。 */
    for(int i=0;i<(PROBE_SECONDS+10)*10&&!stopping;i++)usleep(100000);
    _exit(0);
}
static int reap(int pid){int status;for(int stage=0;stage<2;stage++){if(kill(pid,stage?SIGKILL:SIGTERM)&&errno!=ESRCH)return 0;for(int i=0;i<20;i++){int got=waitpid(pid,&status,WNOHANG);if(got==pid)return 1;if(got<0&&errno!=EINTR)return 0;usleep(100000);}}return 0;}
static int close_inherited(int keep){DIR *d=opendir("/proc/self/fd");
#ifdef NS_HOST_TEST
    if(!d)d=opendir("/dev/fd");
#endif
    if(!d)return -1;int own=dirfd(d),fds[256],used=0;struct dirent *entry;
    while((entry=readdir(d))){char *end;unsigned long long n=strtoull(entry->d_name,&end,10);if(end==entry->d_name||*end)continue;if(n>2&&n!=(unsigned)keep&&n!=(unsigned)own){if(n>1048576||used==256){closedir(d);return -1;}fds[used++]=(int)n;}}
    closedir(d);for(int i=0;i<used;i++)close(fds[i]);return 0;
}
static int ipv4(char out[2048],int *lan){
#ifdef NS_HOST_TEST
    int n=text_file(NET_IP_PATH,out,2048);if(n>=0&&strstr(out,"192.168."))*lan=1;return n;
#else
    /* 仅向本机内核查询接口地址；不bind/listen/connect/send网络数据。 */
    extern int socket(int,int,int),ioctl(int,unsigned long,...);
    struct ifconf { int length; char *buffer; };char entries[1280];struct ifconf conf={sizeof(entries),entries};int fd=socket(2,2,0);if(fd<0)return -1;int rc=ioctl(fd,0x8912UL,&conf),error=rc?errno:0;close(fd);if(rc){errno=error;return -1;}if(conf.length<0||conf.length>=(int)sizeof(entries)||conf.length%40){errno=75;return -1;}
    int used=0;for(int i=0;i<conf.length;i+=40){const unsigned char *ip=(unsigned char *)entries+i+20;unsigned short family;memcpy(&family,entries+i+16,2);if(family!=2)continue;int n=snprintf(out+used,2048-(size_t)used,"IPV4 %.16s %u.%u.%u.%u\n",entries+i,ip[0],ip[1],ip[2],ip[3]);if(n<=0||used+n>=2048){errno=75;return -1;}used+=n;if(ip[0]&&ip[0]!=127&&ip[0]<224)*lan=1;}return used;
#endif
}
static int trace_sample(int fd,long long elapsed,int *lan,struct sha_ctx *hash,long *bytes){if(fail_step(78)){errno=75;return -1;}char line[256],raw[2048];int n=snprintf(line,sizeof(line),"SAMPLE elapsed_ms=%lld parent=%d child_namespace_held=1\n",elapsed,getpid());if(n<=0||*bytes+n>TRACE_LIMIT||wr(fd,line,(size_t)n))return -1;sha_add(hash,line,(size_t)n);*bytes+=n;
    const char *paths[]={NET_DEV_PATH,NET_ROUTE_PATH,"kernel-interface-ipv4"};
    for(int i=0;i<3;i++){n=i==2?ipv4(raw,lan):get_file(paths[i],raw,sizeof(raw));int e=n<0?errno:0;int k=snprintf(line,sizeof(line),"FILE %s bytes=%d errno=%d\n",paths[i],n,e);if(k<=0||*bytes+k+(n>0?n:0)>TRACE_LIMIT)return -1;if(wr(fd,line,(size_t)k))return -1;sha_add(hash,line,(size_t)k);*bytes+=k;if(n<0)return -1;if(wr(fd,raw,(size_t)n))return -1;sha_add(hash,raw,(size_t)n);*bytes+=n;}
    return fsync(fd);
}
static void setup_failed(int notify,int code,const char *step){int error=errno;char row[256];int n=snprintf(row,sizeof(row),"A7R5_NS_SETUP_FAILED %s code=%d errno=%d step=%s\n",RUN_ID,code,error,step);if(n>0&&(size_t)n<sizeof(row))wr(notify,row,(size_t)n);close(notify);_exit(code);}
static void supervisor(int notify){
    if(setsid()<0)setup_failed(notify,80,"setsid");int nullfd=open("/dev/null",O_RDWR|O_CLOEXEC);if(nullfd<0)setup_failed(notify,80,"dev_null");for(int i=0;i<3;i++)if(dup2(nullfd,i)<0)setup_failed(notify,80,"stdio");if(close_inherited(notify))setup_failed(notify,80,"close_fds");
    signal(SIGTERM,stop_signal);signal(2,stop_signal);signal(1,stop_signal);
    unsigned var_mode;
    passwd_n=get_file(PASSWD_PATH,original_passwd,sizeof(original_passwd));if(passwd_n<=0)setup_failed(notify,81,"passwd_read");mount_n=relevant_mounts(original_mounts);if(mount_n<=0)setup_failed(notify,81,"mounts_read");
    if(directory(VAR_PATH,&var_mode))setup_failed(notify,81,"var_metadata");if(ns_name("mnt",original_ns))setup_failed(notify,81,"mnt_identity");if(ns_name("net",original_net))setup_failed(notify,81,"net_identity");if(directory(RAM_PARENT,&network_mode))setup_failed(notify,81,"ram_metadata");
    if(network_mode!=01777&&network_mode!=0755&&network_mode!=0700){errno=0;setup_failed(notify,81,"ram_permissions");}
#ifndef NS_HOST_TEST
    {unsigned long space[32];if(statvfs(RAM_PARENT,(struct statvfs *)space))setup_failed(notify,81,"ram_statvfs");if(space[4]*space[1]<524288){errno=0;setup_failed(notify,81,"ram_space");}}
    {extern int statfs(const char *,void *);long fs[32];if(statfs(RAM_PARENT,fs))setup_failed(notify,81,"ram_statfs");if(fs[0]!=0x01021994){errno=0;setup_failed(notify,81,"ram_filesystem");}}
#endif
    struct stat st;if(!lstat(MARKER_PATH,&st)||errno!=ENOENT)setup_failed(notify,82,"marker_collision");
    int parent_fd=open(RAM_PARENT,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);if(parent_fd<0)setup_failed(notify,82,"ram_parent_fd");
#ifndef NS_HOST_TEST
    {extern int fstatfs(int,void *);long fs[32];if(fstatfs(parent_fd,fs))setup_failed(notify,82,"ram_parent_fstatfs");if(fs[0]!=0x01021994){errno=0;setup_failed(notify,82,"ram_parent_not_tmpfs");}}
#endif
    size_t parent_len=strlen(RAM_PARENT);if(strncmp(RUN_DIR,RAM_PARENT,parent_len)||RUN_DIR[parent_len]!='/'||strchr(&RUN_DIR[parent_len+1],'/')){errno=0;setup_failed(notify,82,"ram_path_contract");}
    const char *name=&RUN_DIR[parent_len+1];if(mkdirat(parent_fd,name,0700))setup_failed(notify,82,"run_directory");
    ram_fd=openat(parent_fd,name,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);close(parent_fd);if(ram_fd<0)setup_failed(notify,82,"run_directory_fd");
    int trace=openat(ram_fd,ram_name(TRACE_PATH),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);if(trace<0)setup_failed(notify,82,"trace_create");
    int pair[2];if(pipe(pair))setup_failed(notify,83,"child_pipe");int owner_pid=getpid(),pid=fork();if(pid<0)setup_failed(notify,83,"child_fork");
    if(!pid){close(pair[0]);close(notify);close(trace);close(ram_fd);ram_fd=-1;child(pair[1],owner_pid);}
    close(pair[1]);struct child_note note;memset(&note,0,sizeof(note));struct pollfd p={pair[0],POLLIN,0};int code=0,child_reaped=0,isolation=0,lan=0,samples=0,ready_sent=0;
    long bytes=0;long long start=now_ms();unsigned long long ticks=start_ticks(getpid());struct sha_ctx hash;sha_init(&hash);
    int rc=poll(&p,1,10000);ssize_t count=rc>0?read(pair[0],&note,sizeof(note)):-1;close(pair[0]);
    if(start<0){code=76;goto cleanup;}
    if(count!=(ssize_t)sizeof(note)){code=72;stage_error=rc<0?errno:0;goto cleanup;}
    stage_error=note.error;if(note.code){code=note.code;goto cleanup;}
    if(!parent_unchanged()||!ticks){code=73;goto cleanup;}isolation=1;
    {char row[1024],passwd_sha[65];sha_bytes(original_passwd,(size_t)passwd_n,passwd_sha);int n=snprintf(row,sizeof(row),"A7R5_NS_READY %s pid=%d ticks=%llu child=%d uid=%u euid=%u ttl=%d isolation=1 parent_unchanged=1 account_modified=0 ssh_started=0 passwd_sha=%s parent_ns=%s child_ns=%s net_ns=%s\n",RUN_ID,getpid(),ticks,pid,getuid(),geteuid(),PROBE_SECONDS,passwd_sha,original_ns,note.mnt,note.net);if(n<=0||(size_t)n>=sizeof(row)||create_file(READY_PATH,row,(size_t)n)){code=75;goto cleanup;}}
    for(int sequence=1;;sequence++){
        long long elapsed=now_ms()-start;if(elapsed<0){code=76;break;}if(stopping){code=77;break;}if(elapsed>=PROBE_SECONDS*1000LL)break;
        int status;int got=waitpid(pid,&status,WNOHANG);if(got==pid){child_reaped=1;code=74;break;}if(got<0&&errno!=EINTR){code=74;break;}
        if(!parent_unchanged()){code=73;break;}
        if(trace_sample(trace,elapsed,&lan,&hash,&bytes)){code=78;stage_error=errno;break;}samples++;
        char beat[512];int n=snprintf(beat,sizeof(beat),"A7R5_NS_ALIVE %s pid=%d ticks=%llu child=%d seq=%d elapsed_ms=%lld ttl=%d parent_unchanged=1\n",RUN_ID,getpid(),ticks,pid,sequence,elapsed,PROBE_SECONDS);
        if(n<=0||(size_t)n>=sizeof(beat)||atomic_file(HEARTBEAT_PATH,beat,(size_t)n)){code=79;break;}
        if(!ready_sent){const char row[]="READY\n";if(wr(notify,row,sizeof(row)-1)){code=80;break;}ready_sent=1;close(notify);notify=-1;}
        for(int i=0;i<SAMPLE_MS/100&&!stopping;i++)usleep(100000);
    }
cleanup:
    if(!child_reaped)child_reaped=reap(pid);int parent_ok=parent_unchanged();if(!child_reaped||!parent_ok)code=84;
    if(fsync(trace)||close(trace))code=85;
    char digest[65];sha_end(&hash,digest);char result[2048];int n=snprintf(result,sizeof(result),"A7R5_NS_RESULT %s\ncode=%d\nerrno=%d\nuid=%u\neuid=%u\npid=%d\nticks=%llu\nchild=%d\nisolation_verified=%d\nparent_unchanged=%d\npasswd_unchanged=%d\nchild_reaped=%d\nnetwork_hint=%d\nsamples=%d\ntrace_bytes=%ld\ntrace_sha256=%s\nssh_started=0\naccount_modified=0\nEND %s\n",RUN_ID,code,stage_error,getuid(),geteuid(),getpid(),ticks,pid,isolation,parent_ok,parent_ok,child_reaped,lan,samples,bytes,digest,RUN_ID);
    int saved=n>0&&(size_t)n<sizeof(result)&&create_file(RESULT_PATH,result,(size_t)n)==0;
    if(notify>=0){const char *message=saved&&parent_ok&&child_reaped?"NEGATIVE_CLEAN\n":"UNCONFIRMED\n";wr(notify,message,strlen(message));close(notify);}
    /* 最终心跳不再标成ALIVE；旧READY不能在任务结束后授权STOP。 */
    {char done[128];int k=snprintf(done,sizeof(done),"A7R5_NS_ENDED %s code=%d\n",RUN_ID,code);if(k>0)atomic_file(HEARTBEAT_PATH,done,(size_t)k);}
    _exit(saved&&parent_ok&&child_reaped?0:86);
}
int main(int argc,char **argv){
    if(argc!=2||strcmp(argv[1],"--launch"))return 64;
#ifndef NS_HOST_TEST
    if(getuid()||geteuid())return 65;
#endif
    int pipefd[2];if(pipe(pipefd))return 66;int pid=fork();if(pid<0)return 67;
    if(!pid){close(pipefd[0]);supervisor(pipefd[1]);_exit(87);}close(pipefd[1]);struct pollfd p={pipefd[0],POLLIN|POLLHUP,0};char reply[512];int rc=poll(&p,1,15000);ssize_t n=rc>0?read(pipefd[0],reply,sizeof(reply)-1):-1;close(pipefd[0]);
    if(n<=0){reap(pid);return 88;}reply[n]=0;
    if(strcmp(reply,"READY\n")&&strcmp(reply,"NEGATIVE_CLEAN\n")){wr(1,reply,(size_t)n);reap(pid);return 89;}
    char row[192];int k=snprintf(row,sizeof(row),"A7R5_NS_LAUNCH %s outcome=%s",RUN_ID,reply);return k>0&&wr(1,row,(size_t)k)==0?0:90;
}
