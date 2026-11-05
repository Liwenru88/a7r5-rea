/* 仅用于独立 QEMU 客体的服务边界；不修改磁盘上的 AP/CP 文件。 */
static unsigned long n12_base;
extern int usleep(unsigned);
static int n12_sd=-1;
static unsigned n12_bytes,n12_sequence;
static volatile unsigned char *n12_mailbox;
static unsigned n12_observer_busy;
/* 只读采样生产状态和名称，供QMP回读；不写生产状态、可用位或名称表。 */
static void native12_observe(void) {
    unsigned zero=0;
    if(!n12_mailbox||!n12_base||!__atomic_compare_exchange_n(&n12_observer_busy,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))return;
    volatile unsigned char *out=n12_mailbox+8192;
    *(volatile unsigned *)out=0;
    *(volatile unsigned *)(out+4)=((unsigned(*)(void))(n12_base+0x8e96ad8UL))();
    *(volatile unsigned *)(out+8)=((unsigned(*)(void))(n12_base+0x8e97224UL))();
    *(volatile unsigned *)(out+12)=((unsigned(*)(void))(n12_base+0x8e97270UL))();
    for(unsigned i=0;i<80;i++)out[16+i]=*(volatile unsigned char *)(n12_base+0x8ea0020UL+i);
    for(unsigned i=0;i<32;i++)out[96+i]=*(volatile unsigned char *)(n12_base+0x8eb5a60UL+i);
    for(unsigned n=1;n<=12;n++){
        const char *s=((const char *(*)(unsigned))(n12_base+0x8e96a60UL))(n);
        const char *f=((const char *(*)(unsigned))(n12_base+0x8e96ab8UL))(n);
        for(unsigned i=0;i<24;i++)out[128+(n-1)*88+i]=s?(unsigned char)s[i]:0;
        for(unsigned i=0;i<64;i++)out[152+(n-1)*88+i]=f?(unsigned char)f[i]:0;
    }
    *(volatile unsigned *)(out+1184)=*(volatile unsigned *)(n12_base+0x8eb9d18UL);
    *(volatile unsigned *)(out+1188)=*(volatile unsigned *)(n12_base+0x8eb9d1cUL);
    *(volatile unsigned long *)(out+1192)=*(volatile unsigned long *)(n12_base+0x8eb9d70UL);
    *(volatile unsigned long *)(out+1200)=n12_base+0x8eb9da8UL;
    *(volatile unsigned long *)(out+1208)=n12_base;
    /* 只读选择文件：成功状态之外仍保留缺失／暂存等实际观测。 */
    int selected_fd=open("/usr/data/lut/R5FILTER.BIN",0x28000);unsigned char file[25]={0};long used=0;
    if(selected_fd>=0){while(used<25){long n=read(selected_fd,file+used,25-used);if(n<=0){if(n<0)used=-1;break;}used+=n;}close(selected_fd);}else used=-1;
    *(volatile int *)(out+1224)=(int)used;
    for(unsigned i=0;i<24;i++)out[1228+i]=file[i];
    int pending_fd=open("/usr/data/lut/R5FILTER.NEW",0x28000);
    *(volatile unsigned *)(out+1252)=pending_fd>=0;if(pending_fd>=0)close(pending_fd);
    __atomic_store_n((unsigned *)out,0x4d32314eu,__ATOMIC_RELEASE);
    __atomic_store_n(&n12_observer_busy,0,__ATOMIC_RELEASE);
}
static int n12_open(const char *path,unsigned mode,unsigned long *handle) {
    if(!path||!same_name(path,"A:/R5NATIVE.BIN")||mode!=1||!handle||n12_sd>=0)return -1;
    n12_sd=open("/simulation/R5NATIVE.BIN",0);if(n12_sd<0)return -1;
    *handle=(unsigned long)n12_sd;n12_bytes=0;record("A7R5_N12_SD_OPEN ",path);return 0;
}
static int n12_read(unsigned long handle,void *dst,unsigned long capacity,unsigned long *got) {
    if(n12_sd<0||handle!=(unsigned long)n12_sd||!got||!dst||capacity>1024)return -1;
    long n=read(n12_sd,dst,capacity);if(n<0)return -1;*got=(unsigned long)n;n12_bytes+=(unsigned)n;return 0;
}
static int n12_close(unsigned long handle) {
    if(n12_sd<0||handle!=(unsigned long)n12_sd)return -1;
    int rc=close(n12_sd);n12_sd=-1;char s[80];snprintf(s,sizeof(s),"bytes=%u rc=%d",n12_bytes,rc);record("A7R5_N12_SD_CLOSE ",s);return rc;
}
static int n12_send(void *ctx,const unsigned char *packet,unsigned long n) {
    (void)ctx;if(!packet||!n||n>4096||n12_sequence>=1000)return -1024;
    unsigned sequence=++n12_sequence;
    if(!n12_mailbox)return -1024;
    for(unsigned i=0;i<n;i++)n12_mailbox[64+i]=packet[i];
    *(volatile unsigned *)(n12_mailbox+4)=(unsigned)n;
    __atomic_store_n((unsigned *)n12_mailbox,sequence,__ATOMIC_RELEASE);
    char request[100];snprintf(request,sizeof(request),"seq=%u size=%lu mailbox=0x41ec00000",sequence,n);
    record("A7R5_N12_REQUEST ",request);
    char path[80];snprintf(path,sizeof(path),"/tmp/n12-ack-%u",sequence);
    for(unsigned poll=0;poll<200;poll++){
        int fd=open(path,0);
        if(fd>=0){
            unsigned long storage[520]={0};unsigned char *reply=(unsigned char *)storage+16;
            long length=read(fd,reply,4096);close(fd);if(length<=0||length>4096)return -1024;
            *(unsigned *)((unsigned char *)storage+8)=(unsigned)length;
            void (*setsrc)(void *,unsigned)=real_dlsym(0,"osal_set_msg_src");
            unsigned (*size)(const void *)=real_dlsym(0,"osal_msg_size");
            if(!setsrc||!size)__builtin_trap();setsrc(reply,0x90030001u);
            if(size(reply)!=(unsigned)length)__builtin_trap();
            int rc=((int(*)(const unsigned char *,unsigned))(n12_base+0x8e92c8cUL))(reply,0x90030001u);
            char s[96];snprintf(s,sizeof(s),"seq=%u size=%ld inbound=%d",sequence,length,rc);record("A7R5_N12_ACK ",s);
            return 0;
        }
        usleep(5000);
    }
    record("A7R5_N12_TRANSPORT_TIMEOUT ",path);return -1024;
}
static void n12_detour(unsigned long at,void *target) {
    unsigned int *p=(void *)(n12_base+at);
    if(mprotect((void *)((unsigned long)p&~4095UL),4096,7))__builtin_trap();
    p[0]=0x58000050;p[1]=0xd61f0200;*(unsigned long *)(p+2)=(unsigned long)target;
    clear_cache_range(p,16);
    if(mprotect((void *)((unsigned long)p&~4095UL),4096,5))__builtin_trap();
}
#include "e4-trace.inc"
#include "dataflow-adapter.inc"
#include "e4-services.inc"
static void native12_install(unsigned long base) {
    n12_base=base;
    if(getenv("A7R5_N12_LOADING")) {
        int fd=open("/dev/mem",2);if(fd<0)__builtin_trap();
        void *area=mmap(0,65536,3,1,fd,0x41ec00000UL);close(fd);
        if(area==(void *)-1)__builtin_trap();n12_mailbox=area;
        n12_detour(0x3691104UL,n12_open);n12_detour(0x3691138UL,n12_read);n12_detour(0x3691124UL,n12_close);
        n12_detour(0x8e93bd4UL,n12_send);
        n12_trace_install();
        ((void(*)(unsigned,unsigned))(base+0x8e90658UL))(1,0);
        ((void(*)(unsigned))(base+0x8e9066cUL))(0);
        ((void(*)(unsigned,unsigned,unsigned))(base+0x8e9067cUL))(0,0,'A');
        record("A7R5_N12_MEDIA_READY ","virtual read-only A:/R5NATIVE.BIN; production scan callbacks");
    }
    record("A7R5_N12_SERVICES ","software SD and CP transport only; no font or name injection");
}
