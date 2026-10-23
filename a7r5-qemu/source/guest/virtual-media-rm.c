/* 原厂 MediaRM 的受限文件卡模型；不伪造 UI，不提供未核对的 CP 通用服务。 */
extern void *dlvsym(void *,const char *,const char *);
#ifndef A7R5_RM_HOST_TEST
extern char *getenv(const char *);
extern int printf(const char *,...),fflush(void *),strcmp(const char *,const char *);
extern void *memcpy(void *,const void *,unsigned long),*memset(void *,int,unsigned long);
extern int memcmp(const void *,const void *,unsigned long);
extern void _exit(int);
extern void *fopen(const char *,const char *);
extern int fprintf(void *,const char *,...),fclose(void *);
extern unsigned long fwrite(const void *,unsigned long,unsigned long,void *);
extern int vsnprintf(char *,unsigned long,const char *,__builtin_va_list),vprintf(const char *,__builtin_va_list);
extern int snprintf(char *,unsigned long,const char *,...);
extern char *strstr(const char *,const char *);
extern long write(int,const void *,unsigned long);
extern char *fgets(char *,int,void *);
extern int sscanf(const char *,const char *,...);
extern int open(const char *,int,...),close(int),munmap(void *,unsigned long);
extern void *mmap(void *,unsigned long,int,int,int,long);
#endif

#ifndef A7R5_RM_HOST_TEST
/* 模型消息异步产生，单独成行写入有界客体日志，不能插入画面 base64 传输。 */
int a7r5_media_record(const char *format,...) {
    __builtin_va_list args;__builtin_va_start(args,format);
    const char *enabled=getenv("A7R5_VIRTUAL_MEDIA_RM");
    if(!enabled || enabled[0]!='1' || enabled[1]) {
        int result=vprintf(format,args);__builtin_va_end(args);return result;
    }
    static __thread char line[1024];static __thread unsigned used;
    static unsigned budget;
    int count=vsnprintf(line+used,sizeof(line)-used,format,args);__builtin_va_end(args);
    if(count<0 || (unsigned)count>=sizeof(line)-used)_exit(125);
    used+=(unsigned)count;
    if(used && line[used-1]=='\n') {
        if(__atomic_fetch_add(&budget,used,__ATOMIC_RELAXED)+used>2*1024*1024)_exit(125);
        void *log=fopen("/tmp/media-model.log","a");
        if(!log || fwrite(line,1,used,log)!=used || fclose(log))_exit(125);
        /* 失败仍在原控制台可见，成功的异步诊断不污染图像通道。 */
        if(strstr(line,"MEDIA_DATAFLOW_FATAL") || strstr(line,"UNSUPPORTED") ||
           (strstr(line,"MEDIA_RM_") && strstr(line,"result=-")))write(1,line,used);
        used=0;
    }
    return count;
}
#define printf a7r5_media_record
#endif

#define RM_ID 0x80d9016eU
#define LOCAL_POOL 0x80cf016dU
#include "cp-request-capture.inc"
#ifndef A7R5_RM_HOST_TEST
static void cp_init_observe(const unsigned char *request,unsigned bytes,unsigned destination,unsigned source) {
    const char *enabled=getenv("A7R5_CP_INIT_CAPTURE");
    static unsigned captures;
    if(!enabled || enabled[0]!='1' || enabled[1] || bytes!=2400 || destination!=0x90030001 ||
       source!=0x80020002 || request[2]!=0x63 || request[3]!=0x40)return;
    unsigned sequence=__atomic_fetch_add(&captures,1,__ATOMIC_RELAXED);
    if(sequence>=4)_exit(125);
    /* 仅允许候选 DTB 明确声明的客体预留 RAM；不是相机物理地址。 */
    char command[4096];void *file=fopen("/proc/cmdline","r");
    if(!file || !fgets(command,sizeof command,file))_exit(125);
    if(fclose(file) || !strstr(command," memrsv=0x00004000@0x41ea00000:uc "))_exit(125);
    int fd=open("/dev/mem",2);if(fd<0)_exit(125);
    void *area=mmap(0,16384,3,1,fd,0x41ea00000L);
    if(close(fd) || area==(void *)-1)_exit(125);
    int result=a7r5_capture_cp_init(request,bytes,destination,source,sequence,area,16384);
    if(munmap(area,16384) || result)_exit(125);
    printf("MEDIA_CP_INIT_CAPTURED sequence=%u bytes=%u observation_only=1\n",sequence,bytes);
}
#endif
static unsigned notification_queue;
static unsigned virtual_touch_enabled;
static unsigned virtual_release_locks;
static unsigned virtual_hdmi_definition;
static unsigned virtual_hdmi_preset;
static unsigned virtual_hdmi_flags;
static unsigned virtual_output_configured;
static unsigned virtual_output_selection;
static unsigned virtual_panel_mode;
static unsigned virtual_panel_aux;
static unsigned virtual_adf_path;
static unsigned virtual_adf_input_channel;
static unsigned virtual_adf_output_mask;
static unsigned virtual_aux_302c_value;
static unsigned virtual_aux_3012_configured;
static unsigned virtual_aux_notify_configured;
static unsigned char virtual_aux_still_format[16];
static unsigned char virtual_aux_cap_mode[16];
static unsigned virtual_aux_setting_load_configured;
static unsigned virtual_aux_mode_configured;
static unsigned virtual_aux_detail_configured;
static unsigned virtual_aux_event_configured;
static __thread unsigned pin_draining;
static __thread int pin_transport_error;
static unsigned pin_connections,media_next_records;
static int media_wait_trace_enabled(void) {
    const char *value=getenv("A7R5_MEDIA_WAIT_TRACE");
    return value && value[0]=='1' && !value[1];
}

int a7r5_adf_path_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +3529f9c..a044：adf_proc_set_path；仅支持已观察到的全零路径配置。 */
    const unsigned char expected[12]={0x0d,0x20,0x21,3,12,0,1,0x80,0,0,0,0};
    /* +352a1e8..a314：adf_set_input，当前 type 0 / channel 2 / 其余为零。 */
    const unsigned char input[14]={0x0d,0x20,0x34,3,14,0,1,0x80,0,2,0,0,0,0};
    /* +35246cc..497c：adf_set_output，本次 +8 的输出掩码为零。 */
    const unsigned char output[26]={0x0d,0x20,0x2b,3,26,0,1,0x80,0,0,1,0,1,1,1,1,0,0,0,0,0,0,0,0,0,0};
    if(!request || !reply || !((bytes==12 && !memcmp(request,expected,12)) || (bytes==14 && !memcmp(request,input,14)) || (bytes==26 && !memcmp(request,output,26))))return -1024;
    memcpy(reply,request,8);reply[3]=0x13;reply[4]=12;memset(reply+8,0,4);return 0;
}

int a7r5_panel_mode_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +3521f20..1fe4 的 0x149 为 0/1/15；+3522058..2114 的 0x110 为 0/1。 */
    const unsigned char header[8]={0x0d,0x20,0x49,1,10,0,1,0x80};
    const unsigned char auxiliary[8]={0x0d,0x20,0x10,1,10,0,1,0x80};
    if(!request || !reply || bytes!=10 || (memcmp(request,header,8) && memcmp(request,auxiliary,8)) || request[9] ||
       (request[8]!=0 && request[8]!=1 && (request[2]!=0x49 || request[8]!=15)))return -1024;
    const unsigned char response[12]={0x0d,0x20,0x49,0x11,12,0,1,0x80,0,0,0,0};
    memcpy(reply,response,12);reply[2]=request[2];return 0;
}

int a7r5_output_config_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    const unsigned char start[22]={0x0d,0x20,0x18,1,22,0,1,0x80,3,1,0,0,0,0,0,0,0,0,0,0,1,0};
    const unsigned char configure[28]={0x0d,0x20,0x19,1,28,0,1,0x80,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
    /* +3528d04..8efc 在 +20 生成 0/1/2；首次设置前后实测依次出现 1 和 2。 */
    if(!request || !reply || !((bytes==22 && !memcmp(request,start,20) && request[20]<=2 && !request[21]) || (bytes==28 && !memcmp(request,configure,28))))return -1024;
    const unsigned char header[12]={0x0d,0x20,0,0x11,12,0,1,0x80,0,0,0,0};
    memcpy(reply,header,12);reply[2]=request[2];return 0;
}
int a7r5_output_fixed_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +35293ac/+3522940/+35225a4/+3522290/+3522434/+3522ef0：固定配置均等12字节回复。 */
    const unsigned char requests[6][24]={
        {0x0d,0x20,0x38,1,24,0,1,0x80,1,5,5},
        {0x0d,0x20,0x3d,1,10,0,1,0x80,0,1},
        {0x0d,0x20,0x1a,1,14,0,1,0x80,1,14,0,14,6,0},
        {0x0d,0x20,0x53,1,14,0,1,0x80,3,0,32,75,65,0},
        {0x0d,0x20,0x52,1,16,0,1,0x80,3,0,1,0,0,0xeb,0x80,0x80},
        {0x0d,0x20,0x62,1,10,0,1,0x80,0,0}};
    if(!request || !reply)return -1024;
    for(unsigned i=0;i<6;i++)if(bytes==requests[i][4] && !memcmp(request,requests[i],bytes)) {
        memcpy(reply,request,8);reply[3]=0x11;reply[4]=12;memset(reply+8,0,4);return 0;
    }
    return -1024;
}

int a7r5_hdmi_flags_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +352b470..b938 构造相同的双输出格式/帧率；+3520628 返回 1..6 或 0x11。 */
    const unsigned char expected[12]={0,0x25,0x17,1,12,0,1,0,0,0,0,0};
    if(!request || !reply || bytes!=12 || memcmp(request,expected,8) ||
       request[8]>4 || (request[9]>6 && request[9]!=0x11) ||
       request[10]!=request[8] || request[11]!=request[9])return -1024;
    memcpy(reply,expected,12);reply[3]=0x81;return 0;
}

int a7r5_hdmi_preset_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* 原厂 +352ae5c 默认构造器；仅支持本次观察到的关闭输出 / preset 6。 */
    const unsigned char expected[16]={0,0x25,1,1,16,0,1,0,0,0,0,0,6,0,0,0};
    if(!request || !reply || bytes!=16 || memcmp(request,expected,16))return -1024;
    const unsigned char response[12]={0,0x25,1,0x81,12,0,1,0,0,0,0,0};
    memcpy(reply,response,12);return 0;
}

int a7r5_hdmi_definition_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    const unsigned char header[8]={0,0x25,0x0a,1,12,0,1,0};
    if(!request || !reply || bytes!=12 || memcmp(request,header,8) || request[8]>3 || request[9] || request[10] || request[11])return -1024;
    const unsigned char response[12]={0,0x25,0x0a,0x81,12,0,1,0,0,0,0,0};
    memcpy(reply,response,12);return 0;
}

/* AppFw+3554d90：0x11 回复以 +4 的命令号匹配 future；+355c708 读取 +8 状态。 */
int a7r5_release_lock_reply(const unsigned char *request,unsigned bytes,unsigned char *reply,unsigned *locks) {
    if(!request || !reply || !locks || bytes!=16)return -1024;
    const unsigned char header[8]={5,0,0x3d,0x40,2,0,0,0x80};
    if(memcmp(request,header,8) || request[12]>1 || request[13] || request[14] || request[15])return -1024;
    unsigned mask=(unsigned)request[8]|(unsigned)request[9]<<8|(unsigned)request[10]<<16|(unsigned)request[11]<<24;
    if(mask!=0x8000 && mask!=0x200000)return -1024;
    const unsigned char response[12]={0x11,0,0,0,0x3d,0x40,0,0,0,0xf0,0,0};
    memcpy(reply,response,12);
    *locks=request[12]?(*locks|mask):(*locks&~mask);
    return 0;
}
int a7r5_aux_302c_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +3565748/+356550c 的实测固定配置；同一原厂 receiver，+3565788 比较 +8 与 0xf000。 */
    unsigned char expected[24]={0,0,0x2c,0x30,3,0,0,0x80,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
    /* +35656a8也经同一24/12字节辅助函数调用，仅另接受本次0x3012固定请求。 */
    if(request && bytes==24 && request[2]==0x12)expected[2]=0x12;
    if(!request || !reply || bytes!=24 || memcmp(request,expected,24))return -1024;
    const unsigned char response[12]={0x11,0,0,0,0x2c,0x30,0,0,0,0xf0,0,0};
    memcpy(reply,response,12);reply[4]=request[2];return 0;
}
int a7r5_aux_notify_off_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +3567b5c：PID_SET_NOTIFY_MODE 的关闭分支，只要求12字节回复；开启分支不在此模型内。 */
    const unsigned char expected[12]={5,0,0x73,0x40,3,0,0,0x80,0,0,0,0};
    if(!request || !reply || bytes!=12 || memcmp(request,expected,12))return -1024;
    const unsigned char response[12]={0x11,0,0,0,0x73,0x40,0,0,0,0xf0,0,0};
    memcpy(reply,response,12);return 0;
}
int a7r5_aux_still_format_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +3566a28..6a6c：PID_SET_STILL_FORMAT；只接受本次固定测试设置，保存配置，不生成照片。 */
    const unsigned char expected[24]={5,0,0x2d,0x40,3,0,0,0x80,2,0,1,1,1,1,1,0,1,1,1,1,1,0,0,0};
    if(!request || !reply || bytes!=24 || memcmp(request,expected,24))return -1024;
    const unsigned char response[12]={0x11,0,0,0,0x2d,0x40,0,0,0,0xf0,0,0};
    memcpy(reply,response,12);return 0;
}
int a7r5_aux_cap_mode_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +3565eb0..5ee8：PID_SET_CAP_MODE 的固定配置；这里只保存参数，不触发拍摄。 */
    const unsigned char expected[24]={5,0,0x14,0x40,3,0,0,0x80,0,0,1,0,1,0,0,0,1,0,0,0,0,0,0,0};
    if(!request || !reply || bytes!=24 || memcmp(request,expected,24))return -1024;
    const unsigned char response[12]={0x11,0,0,0,0x14,0x40,0,0,0,0xf0,0,0};
    memcpy(reply,response,12);return 0;
}
int a7r5_aux_setting_load_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +355fd68..fd94：PID_SET_SETTING_LOAD，本次仅支持值0；不读取主机或相机设置。 */
    const unsigned char expected[12]={5,0,0x57,0x40,3,0,0,0x80,0,0,0,0};
    if(!request || !reply || bytes!=12 || memcmp(request,expected,12))return -1024;
    const unsigned char response[12]={0x11,0,0,0,0x57,0x40,0,0,0,0xf0,0,0};
    memcpy(reply,response,12);return 0;
}
int a7r5_aux_mode_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +3564ff4..5108：异步子任务的0x409d固定请求，读取12字节回复+8并比较0xf000。 */
    const unsigned char expected[12]={5,0,0x9d,0x40,3,0,0,0x80,0,0,0,0};
    if(!request || !reply || bytes!=12 || memcmp(request,expected,12))return -1024;
    const unsigned char response[12]={0x11,0,0,0,0x9d,0x40,0,0,0,0xf0,0,0};
    memcpy(reply,response,12);return 0;
}
int a7r5_aux_detail_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +3565408..5450：0x4000固定20字节请求；完成回复12字节，状态+8为0xf000。 */
    const unsigned char expected[20]={5,0,0,0x40,3,0,0,0x80,5,0,0,0,0,0,0,0,0,0,1,0};
    if(!request || !reply || bytes!=20 || memcmp(request,expected,20))return -1024;
    const unsigned char response[12]={0x11,0,0,0,0,0x40,0,0,0,0xf0,0,0};
    memcpy(reply,response,12);return 0;
}
int a7r5_aux_event_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    /* +3565468..5504：0x3003等待16字节完成体，+8状态外的+12字段未被该消费者读取。 */
    const unsigned char expected[24]={0,0,3,0x30,3,0,0,0x80};
    if(!request || !reply || bytes!=24 || memcmp(request,expected,24))return -1024;
    const unsigned char response[16]={0x11,0,0,0,3,0x30,0,0,0,0xf0,0,0,0,0,0,0};
    memcpy(reply,response,16);return 0;
}

int a7r5_media_rm_enabled(void) {
    const char *value=getenv("A7R5_VIRTUAL_MEDIA_RM");
    return value && value[0]=='1' && !value[1];
}
int a7r5_media_observer_record(const void *data,unsigned long bytes) {
    /* 原观察库发出的完整诊断行单独保存；不删除未知输出或异常记录。 */
    const char *p=data;
    if(!p || bytes<24 || bytes>512 || p[bytes-1]!='\n')return 0;
    const char *prefixes[]={"OBS A7R5_MODEL_LOG ","OBS BB_CONFIG_REQUEST ","OBS PLANE_CONFIG_REQUEST "};
    const unsigned lengths[]={19,22,25};
    for(unsigned i=0;i<3;i++)if(bytes>lengths[i] && !memcmp(p,prefixes[i],lengths[i]))return 1;
    return 0;
}
static void *next(const char *name) {
    void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
    void *result=lookup?lookup((void *)-1,name):0;
    if (!result)_exit(126);
    return result;
}
#ifndef A7R5_RM_HOST_TEST
long write(int fd,const void *data,unsigned long bytes) {
    if(a7r5_media_rm_enabled() && a7r5_media_observer_record(data,bytes)) {
        char path[64],target[64];snprintf(path,sizeof path,"/proc/self/fd/%d",fd);
        long (*read_link)(const char *,char *,unsigned long)=next("readlink");
        long count=read_link(path,target,sizeof target-1);
        if(count>0 && count<(long)sizeof target) {
            target[count]=0;
            if(!strcmp(target,"/dev/console")) {
                a7r5_media_record("%.*s",(int)bytes,(const char *)data);return (long)bytes;
            }
        }
    }
    long (*original)(int,const void *,unsigned long)=next("write");
    return original(fd,data,bytes);
}
#endif
/* 原 libstdc++ b74b8 的成员 ABI：this,x1=addr,w2=value,w3=timed,x4=sec,x5=nsec。只观察并原样转发。 */
int a7r5_future_wait(void *,unsigned *,unsigned,unsigned char,long,long)
    __asm__("_ZNSt28__atomic_futex_unsigned_base19_M_futex_wait_untilEPjjbNSt6chrono8durationIlSt5ratioILl1ELl1EEEENS2_IlS3_ILl1ELl1000000000EEEE");
int a7r5_future_wait(void *self,unsigned *address,unsigned value,unsigned char timed,long seconds,long nanoseconds) {
    static __thread unsigned samples;
    static unsigned total_samples;
    if(a7r5_media_rm_enabled() && media_wait_trace_enabled() && samples<4 && __atomic_load_n(&pin_connections,__ATOMIC_ACQUIRE)>=14) {
        unsigned long (*thread_self)(void)=next("pthread_self");
        int (*thread_name)(unsigned long,char *,unsigned long)=next("pthread_getname_np");
        char name[16]={0};
        /* 公共序列还会等待异步子任务；只读观测同时覆盖它们，总样本数固定封顶。 */
        if(!thread_name(thread_self(),name,sizeof name) &&
           __atomic_fetch_add(&total_samples,1,__ATOMIC_RELAXED)<16) {
            samples++;
            unsigned long fp=(unsigned long)__builtin_frame_address(0),start=0,end=0;
            void *maps=fopen("/proc/self/maps","r");char line[512],permissions[5];
            if(maps) {
                while(fgets(line,sizeof line,maps)) {
                    unsigned long first,last;
                    if(sscanf(line,"%lx-%lx %4s",&first,&last,permissions)==3 && permissions[0]=='r' && first<=fp && fp+16<=last) {start=first;end=last;break;}
                }
                fclose(maps);
            }
            printf("MEDIA_FUTURE_WAIT thread=%s address=%p value=%u timed=%u seconds=%ld nanos=%ld frames=",name,address,value,timed,seconds,nanoseconds);
            for(unsigned i=0;i<24 && start && fp>=start && fp+16<=end && !(fp&15);i++) {
                const unsigned long *frame=(const unsigned long *)fp;unsigned long parent=frame[0];
                printf("%#lx,",frame[1]);if(parent<=fp)break;fp=parent;
            }
            printf("\n");fflush(0);
        }
    }
    int (*original)(void *,unsigned *,unsigned,unsigned char,long,long)=next("_ZNSt28__atomic_futex_unsigned_base19_M_futex_wait_untilEPjjbNSt6chrono8durationIlSt5ratioILl1ELl1EEEENS2_IlS3_ILl1ELl1000000000EEEE");
    return original(self,address,value,timed,seconds,nanoseconds);
}
int osal_valloc_msg_wait(unsigned id,void **message,int bytes,int count) {
    int (*original)(unsigned,void **,int,int)=next("osal_valloc_msg_wait");
    unsigned pool=(id==RM_ID && a7r5_media_rm_enabled())?LOCAL_POOL:id;
    int result=original(pool,message,bytes,count);
    if(pin_draining && result)pin_transport_error=result;
    if (id==RM_ID && a7r5_media_rm_enabled()) {
        printf("MEDIA_RM_ALLOC bytes=%d pool=%#x result=%d\n",bytes,pool,result);fflush(0);
    }
    return result;
}
int osal_free_msg(unsigned id,void *message) {
    int (*original)(unsigned,void *)=next("osal_free_msg");
    return original((id==RM_ID && a7r5_media_rm_enabled())?LOCAL_POOL:id,message);
}
int osal_rcv_msg_tmo(unsigned id,void **message,long timeout) {
    int (*original)(unsigned,void **,long)=next("osal_rcv_msg_tmo");
    if(a7r5_media_rm_enabled() && media_wait_trace_enabled() && __atomic_load_n(&pin_connections,__ATOMIC_ACQUIRE)>=14 &&
       (id>>16)==0x81cf && __atomic_fetch_add(&media_next_records,1,__ATOMIC_RELAXED)<24) {
        void *frames[16];int (*trace)(void **,int)=next("backtrace");int count=trace(frames,16);
        void *log=fopen("/tmp/media-wait-trace.log","a");
        if(!log)_exit(125);
        fprintf(log,"MEDIA_NEXT_WAIT queue=%#x timeout=%ld frames=",id,timeout);
        for(int i=0;i<count;i++)fprintf(log,"%p,",frames[i]);fprintf(log,"\n");fclose(log);
    }
    int result=original(id,message,timeout);
    if(!result && id==0x80020002 && message && *message && a7r5_media_rm_enabled()) {
        unsigned (*size)(void *)=next("osal_msg_size");
        unsigned (*get_source)(void *)=next("osal_get_msg_src");
        const unsigned char *p=*message;unsigned bytes=size(*message);
        if(bytes==12 && p[0]==0x11 && p[4]==0x3d && p[5]==0x40) {
            printf("MEDIA_IMAGING_RECEIVED queue=%#x source=%#x bytes=%u callback=0x11 command=0x403d\n",id,get_source(*message),bytes);fflush(0);
        }
        if(bytes==12 && p[0]==0x11 && p[4]==0x2c && p[5]==0x30) {
            unsigned status=0;memcpy(&status,p+8,4);
            printf("MEDIA_AUX_RECEIVED queue=%#x source=%#x command=0x302c status=%#x\n",id,get_source(*message),status);fflush(0);
        }
    }
    return result;
}
static int notify(unsigned queue) {
    int (*alloc)(unsigned,void **,int,int)=next("osal_valloc_msg_wait");
    int (*send)(unsigned,void *)=next("osal_snd_msg");
    int (*release)(unsigned,void *)=next("osal_free_msg");
    void (*source)(void *,unsigned)=next("osal_set_msg_src");
    void *message=0;int result=alloc(queue,&message,7,1);
    if (result) {
        printf("MEDIA_RM_NOTIFY queue=%#x result=%d virtual_input=1\n",queue,result);fflush(0);return result;
    }
    /* A7R5 实测有效配置为 rm2/rm3；仅 rm2 插卡，rm3 空，均未置 hold。 */
    const unsigned char state[7]={2,0,0,6,0,2,0};
    memcpy(message,state,7);source(message,RM_ID);result=send(queue,message);
    if (result)release(queue,message);
    printf("MEDIA_RM_NOTIFY queue=%#x state=02000006000200 result=%d virtual_input=1\n",queue,result);fflush(0);
    return result;
}
int a7r5_touch_reply(const unsigned char *request,unsigned bytes,unsigned char *reply) {
    static const unsigned char header[8]={0x0d,0x20,0x46,1,10,0,1,0x80};
    if (!request || !reply || bytes!=10 || memcmp(request,header,8) || request[8]>1 || request[9])return -1024;
    const unsigned char response[12]={0x0d,0x20,0x46,0x11,12,0,1,0x80,0,0,0,0};
    memcpy(reply,response,12);virtual_touch_enabled=request[8];return 0;
}
/* 只登记原厂实际查询过的端口；连接由 SDK 检查双方属性，不代表存在图像生产者。 */
#include "dataflow-pin-definitions.inc"
static int pin_index(const unsigned char *property,unsigned node) {
    for(unsigned i=0;i<sizeof(pin_definitions)/sizeof(pin_definitions[0]);i++)
        if(pin_definitions[i][3]==node && !memcmp(property,pin_definitions[i],12))return (int)i;
    return -1;
}
static int dataflow_node(unsigned node) {
    for(unsigned i=0;i<sizeof(pin_definitions)/sizeof(pin_definitions[0]);i++)if(pin_definitions[i][3]==node)return 1;
    return 0;
}
int a7r5_pin_query_valid(const unsigned char *request,unsigned bytes,unsigned queue,unsigned node) {
    const unsigned char expected[40]={1,0,48,0,24,0,0,0,48,0,0,0,0x7f,0,0,0,
        0,0x10,0,0,24,0,2,0,0,0,0,0,2,0,0,0,1,0,0,0,0,0,0,0};
    unsigned reply_id=0;
    if(!request || bytes!=48 || (queue>>16)!=0x81cf ||
       !dataflow_node(node) || memcmp(request+8,expected,12) ||
       (request[20]!=0 && request[20]!=0x7f) || request[21] || request[22] || request[23] ||
       memcmp(request+24,expected+16,8) || pin_index(request+32,node)<0 ||
       request[44] || request[45] || request[46] || request[47])return -1024;
    memcpy(&reply_id,request,4);return reply_id==queue?0:-1024;
}
/* 两端对象贯穿本次客体进程；SDK 自身维护 peer/state/pending，不直接写其内部字段。 */
struct virtual_pin {unsigned long pin[8],sender[1];unsigned initialized;};
static struct virtual_pin dataflow_pins[sizeof(pin_definitions)/sizeof(pin_definitions[0])];
static struct virtual_pin *pin_object(unsigned index) {
    struct virtual_pin *p=&dataflow_pins[index];
    if(!p->initialized) {
        void (*sender_init)(void *)=next("_ZN19DataflowInfraSenderC1Ev");
        void (*pin_init)(void *,const void *,void *)=next("_ZN16DataflowInfraPinC1EPN19DefDataflowInfraPin12PIN_PROPERTYEP19DataflowInfraSender");
        sender_init(p->sender);pin_init(p->pin,pin_definitions[index],p->sender);p->initialized=1;
    }
    return p;
}
static int pin_query(void *request,unsigned bytes,unsigned queue,unsigned node) {
    int result=a7r5_pin_query_valid(request,bytes,queue,node);if(result)return result;
    /* 已核对原厂类大小：Pin 0x40、Msg 0x198、Sender 8。查询本次持久对象的实际状态。 */
    unsigned index=pin_index((const unsigned char *)request+32,node);
    struct virtual_pin *object=pin_object(index);
    void *pin=object->pin,*sender=object->sender;unsigned long message[51]={0};
    /* SDK PIN_PROPERTY 与 AppFw ds_infra_pin 顺序不同：Module,Instance,Pin,Node。 */
    const unsigned *own=pin_definitions[index];unsigned identity[4]={0},peer[4]={0},state=0;
    void (*pin_state)(void *,void *)=next("_ZN16DataflowInfraPin11GetPinStateEPN19DefDataflowInfraPin8PinStateE");
    int (*pin_peer)(void *,void *)=next("_ZN16DataflowInfraPin12GetTargetPinEPN19DefDataflowInfraPin12PIN_PROPERTYE");
    int (*pin_self)(void *,void *)=next("_ZN16DataflowInfraPin10GetSelfPinEPN19DefDataflowInfraPin12PIN_PROPERTYE");
    void (*msg_init)(void *)=next("_ZN16DataflowInfraMsgC1Ev");
    int (*set_data)(void *,void *,unsigned short)=next("_ZN16DataflowInfraMsg14SetDataflowMsgEPvt");
    int (*set_source)(void *,unsigned)=next("_ZN16DataflowInfraMsg8SetSrcIdEj");
    int (*set_reply)(void *,unsigned)=next("_ZN16DataflowInfraMsg10SetReplyIdEj");
    int (*send)(void *,unsigned,void *)=next("_ZN19DataflowInfraSender9SendASyncEjP16DataflowInfraMsg");
    pin_state(pin,&state);result=pin_peer(pin,peer);
    if(!result)result=pin_self(pin,identity);
    unsigned char payload[32]={0,0x10,0,0x80,32,0,2,0};
    if(!result && (memcmp(identity,own,16) || state>2))result=-1024;
    if(!result) {
        /* +3542918..2940 按 Node,Module,Instance,Pin 重排；+3542b18 必须与查询身份相同。 */
        memcpy(payload+8,identity,12);memcpy(payload+20,&state,4);memcpy(payload+24,identity+3,4);
        msg_init(message);result=set_data(message,payload,32);
        if(!result)result=set_source(message,node);
        if(!result)result=set_reply(message,0);
        if(!result)result=send(sender,queue,message);
        void (*destroy)(void *)=next("_ZN16DataflowInfraMsgD1Ev");destroy(message);
    }
    /* 原厂 Sender 自行管理回复消息；失败时原请求仍归调用者。 */
    if(!result) {int (*release)(unsigned,void *)=next("osal_free_msg");release(node,request);}
    printf("MEDIA_DATAFLOW_PIN_QUERY node=%#x pin=%u,%u,%u state=%u peer=%#x,%#x,%u,%u result=%d original_sdk=1 virtual_input=1\n",node,own[0],own[1],own[2],state,peer[0],peer[1],peer[2],peer[3],result);fflush(0);return result;
}
#include "dataflow-pin-service.inc"
int osal_snd_msg(unsigned id,void *message) {
    int (*original)(unsigned,void *)=next("osal_snd_msg");
    if(message && a7r5_media_rm_enabled()) {
        unsigned (*size)(void *)=next("osal_msg_size");
        unsigned (*get_source)(void *)=next("osal_get_msg_src");
        const unsigned char *p=message;unsigned bytes=size(message);
#ifndef A7R5_RM_HOST_TEST
        cp_init_observe(p,bytes,id,get_source(message));
#endif
        if(id==0x90030001) {
            printf("MEDIA_AUX_REQUEST dest=%#x source=%#x bytes=%u payload=",id,get_source(message),bytes);
            for(unsigned i=0;i<bytes && i<80;i++)printf("%02x",p[i]);printf("\n");fflush(0);
            if(bytes>=4 && (((p[2]==0x2c || p[2]==3 || p[2]==0x12) && p[3]==0x30) || ((p[2]==0x73 || p[2]==0x2d || p[2]==0x14 || p[2]==0x57 || p[2]==0x9d || p[2]==0) && p[3]==0x40))) {
                unsigned command=p[2]|(unsigned)p[3]<<8;
                unsigned char response[16];unsigned response_bytes=command==0x3003?16:12;
                int result=command==0x3003?a7r5_aux_event_reply(p,bytes,response):(command==0x302c || command==0x3012)?a7r5_aux_302c_reply(p,bytes,response):command==0x4073?a7r5_aux_notify_off_reply(p,bytes,response):command==0x402d?a7r5_aux_still_format_reply(p,bytes,response):command==0x4014?a7r5_aux_cap_mode_reply(p,bytes,response):command==0x409d?a7r5_aux_mode_reply(p,bytes,response):command==0x4000?a7r5_aux_detail_reply(p,bytes,response):a7r5_aux_setting_load_reply(p,bytes,response);unsigned queue=get_source(message);
                if(result || queue!=0x80020002) {
                    printf("MEDIA_AUX_UNSUPPORTED command=%#x bytes=%u source=%#x body8=%u\n",command,bytes,queue,bytes>8?p[8]:0);fflush(0);return -1024;
                }
                int (*alloc)(unsigned,void **,int,int)=next("osal_valloc_msg_wait");
                int (*release)(unsigned,void *)=next("osal_free_msg");void (*set_source)(void *,unsigned)=next("osal_set_msg_src");
                void *reply=0;result=alloc(queue,&reply,response_bytes,1);if(result)return result;
                memcpy(reply,response,response_bytes);set_source(reply,id);result=original(queue,reply);
                if(result) {release(queue,reply);return result;}
                if(command==0x302c)virtual_aux_302c_value=0x80000003;
                else if(command==0x3012)virtual_aux_3012_configured=1;
                else if(command==0x4073)virtual_aux_notify_configured=1;
                else if(command==0x402d)memcpy(virtual_aux_still_format,p+8,16);
                else if(command==0x4014)memcpy(virtual_aux_cap_mode,p+8,16);
                else if(command==0x4057)virtual_aux_setting_load_configured=1;
                else if(command==0x409d)virtual_aux_mode_configured=1;
                else if(command==0x4000)virtual_aux_detail_configured=1;
                else virtual_aux_event_configured=1;
                release(id,message);
                printf("MEDIA_AUX_CONFIG command=%#x value=%#x notify_off=%u callback_status=0xf000 virtual_input=1\n",command,virtual_aux_302c_value,virtual_aux_notify_configured);fflush(0);return 0;
            }
        }
        if(media_wait_trace_enabled() && __atomic_load_n(&pin_connections,__ATOMIC_ACQUIRE)>=14 &&
           (get_source(message)>>16)==0x81cf && __atomic_fetch_add(&media_next_records,1,__ATOMIC_RELAXED)<24) {
            void *log=fopen("/tmp/media-wait-trace.log","a");if(!log)_exit(125);
            fprintf(log,"MEDIA_NEXT_SEND dest=%#x source=%#x bytes=%u payload=",id,get_source(message),bytes);
            for(unsigned i=0;i<bytes && i<80;i++)fprintf(log,"%02x",p[i]);fprintf(log,"\n");fclose(log);
        }
        if(id==0x90050004 || id==0x9284074a || (bytes>=32 && bytes<=408 && p[8]==1 && !p[9] && !p[24] && p[25]==0x10)) {
            printf("MEDIA_DATAFLOW_TRANSPORT dest=%#x source=%#x bytes=%u payload=",id,get_source(message),bytes);
            for(unsigned i=0;i<bytes && i<96;i++)printf("%02x",p[i]);printf("\n");fflush(0);
        }
        if(dataflow_node(id) && bytes>=28 && p[24]==0 && p[25]==0x10)
            return dataflow_dispatch(id,message,bytes,get_source(message));
    }
    if ((id==0x909a015a || id==0x92840747) && message && a7r5_media_rm_enabled()) {
        unsigned (*size)(void *)=next("osal_msg_size");
        unsigned (*get_source)(void *)=next("osal_get_msg_src");
        unsigned bytes=size(message);const unsigned char *p=message;
        if(bytes>=4) {
            printf("MEDIA_OUTPUT_REQUEST dest=%#x source=%#x bytes=%u payload=",id,get_source(message),bytes);
            for(unsigned i=0;i<bytes && i<64;i++)printf("%02x",p[i]);printf("\n");fflush(0);
        }
        unsigned property=bytes>=4?((unsigned)p[2]|(unsigned)p[3]<<8):0;
        if(id==0x92840747 && (property==0x110 || property==0x118 || property==0x119 || property==0x149 || property==0x321 || property==0x334 || property==0x32b || property==0x138 || property==0x13d || property==0x11a || property==0x153 || property==0x152 || property==0x162)) {
            unsigned char response[12];int result=(property==0x138 || property==0x13d || property==0x11a || property==0x153 || property==0x152 || property==0x162)?a7r5_output_fixed_reply(p,bytes,response):(property==0x321 || property==0x334 || property==0x32b)?a7r5_adf_path_reply(p,bytes,response):(property==0x110 || property==0x149)?a7r5_panel_mode_reply(p,bytes,response):a7r5_output_config_reply(p,bytes,response);
            unsigned queue=get_source(message),command=property;
            unsigned mode=bytes>=9?p[8]:0;
            unsigned channel=bytes>=10?p[9]:0;
            unsigned selection=bytes>=21?p[20]:0;
            if(result || !queue || queue==0xa5a5a5a5)return -1024;
            int (*alloc)(unsigned,void **,int,int)=next("osal_valloc_msg_wait");
            int (*release)(unsigned,void *)=next("osal_free_msg");
            void (*set_source)(void *,unsigned)=next("osal_set_msg_src");
            void *reply=0;result=alloc(queue,&reply,12,1);if(result)return result;
            memcpy(reply,response,12);set_source(reply,id);result=original(queue,reply);
            if(result) {release(queue,reply);return result;}
            if(command==0x321)virtual_adf_path=0;
            else if(command==0x334)virtual_adf_input_channel=channel;
            else if(command==0x32b)virtual_adf_output_mask=0;
            else if(command==0x110)virtual_panel_aux=mode;
            else if(command==0x149)virtual_panel_mode=mode;
            else if(command==0x138 || command==0x13d || command==0x11a || command==0x153 || command==0x152 || command==0x162)
                __atomic_fetch_or(&virtual_output_configured,command==0x138?4:command==0x13d?8:command==0x11a?16:command==0x153?32:command==0x152?64:128,__ATOMIC_RELAXED);
            else {
                if(command==0x118)virtual_output_selection=selection;
                __atomic_fetch_or(&virtual_output_configured,command==0x118?1:2,__ATOMIC_RELAXED);
            }
            release(id,message);
            printf("MEDIA_OUTPUT_CONFIG command=%#x configured=%u selection=%u panel_mode=%u panel_aux=%u adf_path=%u adf_input_channel=%u adf_output_mask=%#x result=0 virtual_input=1\n",command,__atomic_load_n(&virtual_output_configured,__ATOMIC_RELAXED),virtual_output_selection,virtual_panel_mode,virtual_panel_aux,virtual_adf_path,virtual_adf_input_channel,virtual_adf_output_mask);fflush(0);return 0;
        }
        if(id==0x909a015a && bytes>=4 && (p[2]==0x0a || p[2]==1 || p[2]==0x17) && p[3]==1) {
            unsigned command=p[2];unsigned char response[12];
            int result=command==1?a7r5_hdmi_preset_reply(p,bytes,response):command==0x17?a7r5_hdmi_flags_reply(p,bytes,response):a7r5_hdmi_definition_reply(p,bytes,response);
            unsigned queue=get_source(message),definition=bytes==12?p[8]:0;
            unsigned flags=bytes==12?((unsigned)p[8]|(unsigned)p[9]<<8|(unsigned)p[10]<<16|(unsigned)p[11]<<24):0;
            if(result || !queue || queue==0xa5a5a5a5)return -1024;
            int (*alloc)(unsigned,void **,int,int)=next("osal_valloc_msg_wait");
            int (*release)(unsigned,void *)=next("osal_free_msg");
            void (*set_source)(void *,unsigned)=next("osal_set_msg_src");
            void *reply=0;result=alloc(queue,&reply,12,1);if(result)return result;
            memcpy(reply,response,12);set_source(reply,id);result=original(queue,reply);
            if(result) {release(queue,reply);return result;}
            if(command==1)virtual_hdmi_preset=6;else if(command==0x17)virtual_hdmi_flags=flags;else virtual_hdmi_definition=definition;
            release(id,message);
            printf("MEDIA_OUTPUT_HDMI_MODEL command=%#x definition=%u preset=%u flags=%#x result=0 virtual_input=1\n",command,virtual_hdmi_definition,virtual_hdmi_preset,virtual_hdmi_flags);fflush(0);return 0;
        }
    }
    if (id==0x90040193 && message && a7r5_media_rm_enabled()) {
        unsigned (*size)(void *)=next("osal_msg_size");
        unsigned (*get_source)(void *)=next("osal_get_msg_src");
        unsigned bytes=size(message);const unsigned char *p=message;
        /* 有界观察成像队列；保持原消息及所有权不变。 */
        printf("MEDIA_IMAGING_REQUEST dest=%#x source=%#x bytes=%u payload=",id,get_source(message),bytes);
        for(unsigned i=0;i<bytes && i<64;i++)printf("%02x",p[i]);
        printf("\n");fflush(0);
        if(bytes>=4 && p[2]==0x3d && p[3]==0x40) {
            unsigned queue=get_source(message),updated=virtual_release_locks;unsigned char response[12];
            int result=a7r5_release_lock_reply(p,bytes,response,&updated);
            if(result || queue!=0x80020002)return -1024;
            int (*alloc)(unsigned,void **,int,int)=next("osal_valloc_msg_wait");
            int (*release)(unsigned,void *)=next("osal_free_msg");
            void (*set_source)(void *,unsigned)=next("osal_set_msg_src");
            void *reply=0;result=alloc(queue,&reply,12,1);if(result)return result;
            memcpy(reply,response,12);set_source(reply,id);result=original(queue,reply);
            if(result) {release(queue,reply);return result;}
            virtual_release_locks=updated;release(id,message);
            printf("MEDIA_IMAGING_RELEASE_LOCK command=0x403d callback=0x11 locks=%#x result=0 virtual_input=1\n",updated);fflush(0);return 0;
        }
    }
    if (id==0x92840747 && message && a7r5_media_rm_enabled()) {
        unsigned (*size)(void *)=next("osal_msg_size");
        unsigned bytes=size(message);const unsigned char *p=message;
        if (bytes>=4 && p[0]==0x0d && p[1]==0x20 && p[2]==0x46 && p[3]==1) {
            unsigned (*get_source)(void *)=next("osal_get_msg_src");
            int (*alloc)(unsigned,void **,int,int)=next("osal_valloc_msg_wait");
            int (*release)(unsigned,void *)=next("osal_free_msg");
            void (*set_source)(void *,unsigned)=next("osal_set_msg_src");
            unsigned queue=get_source(message);unsigned char response[12];
            int result=a7r5_touch_reply(p,bytes,response);
            if (result || !queue || queue==0xa5a5a5a5)return -1024;
            void *reply=0;result=alloc(queue,&reply,12,1);if(result)return result;
            memcpy(reply,response,12);set_source(reply,id);result=original(queue,reply);
            if (result) {release(queue,reply);return result;}
            release(id,message);
            printf("MEDIA_TOUCH_MODEL enabled=%u property=0x146 reply=0x1146 result=0\n",virtual_touch_enabled);fflush(0);return 0;
        }
    }
    if (id!=RM_ID || !a7r5_media_rm_enabled()) {
        int result=original(id,message);
        if(pin_draining && result)pin_transport_error=result;
        return result;
    }
    unsigned (*size)(void *)=next("osal_msg_size");
    int (*alloc)(unsigned,void **,int,int)=next("osal_valloc_msg_wait");
    int (*release)(unsigned,void *)=next("osal_free_msg");
    void (*source)(void *,unsigned)=next("osal_set_msg_src");
    unsigned bytes=message?size(message):0;
    if (bytes<24 || bytes>136)return -1024;
    unsigned *head=message;unsigned op=head[0],queue=head[2];
    unsigned short *shorts=message;unsigned payload=shorts[3];
    printf("MEDIA_RM_REQUEST op=%u bytes=%u payload=%u reply=%#x\n",op,bytes,payload,queue);fflush(0);
    if (shorts[2]!=1 || payload+24!=bytes || !queue || queue==0xa5a5a5a5 ||
        !((op==3 && payload==4)||(op==9 && payload==112))) {
        printf("MEDIA_RM_UNSUPPORTED op=%u\n",op);fflush(0);return -1024;
    }
    void *response=0;int result=alloc(queue,&response,bytes,1);
    if (result)return result;
    memcpy(response,message,bytes);((unsigned *)response)[3]=0;
    unsigned notify_to=0;
    if (op==3) {
        notify_to=((unsigned *)message)[6];
        if (!notify_to || notify_to==0xa5a5a5a5) {release(queue,response);return -1024;}
        notification_queue=notify_to;
    } else {
        /* MediaDetect.Init 依次读取 3 个 36 字节记录的 +4 掩码；实测 rm2/rm3 有效。 */
        unsigned *cfg=(unsigned *)((char *)response+24);memset(cfg,0,112);
        cfg[0]=3;cfg[10]=1;cfg[11]=2;cfg[19]=2;cfg[20]=4;
    }
    source(response,RM_ID);result=original(queue,response);
    if (result) {release(queue,response);return result;}
    release(LOCAL_POOL,message);
    printf("MEDIA_RM_REPLY op=%u result=0 modeled=1\n",op);fflush(0);
    if (notify_to)notify(notification_queue);
    return 0;
}

/* 以下仅观察已核对对象布局，不改原厂媒体状态字段。 */
static void media_info(const void *self,const char *phase) {
    const unsigned char *p=self;
    for (unsigned i=0;i<3;i++) {
        const unsigned char *r=p+0x108+i*0x70;
        printf("MEDIA_DETECT_NATIVE phase=%s index=%u active=%u media=%#x mask=%#x watching=%u state=%u path=%.31s\n",
            phase,i,r[8],*(const unsigned *)(r+12),*(const unsigned *)(r+20),r[24],*(const unsigned *)(r+0x34),r+0x3c);
    }
    fflush(0);
}
void rm_init(void *self) __asm__("_ZN24InfraMediaDetectThreadRM4InitEv");
void rm_init(void *self) {
    void (*original)(void *)=next("_ZN24InfraMediaDetectThreadRM4InitEv");
    original(self);if(a7r5_media_rm_enabled())media_info(self,"init");
}
int rm_parse(void *self,unsigned id,void *message) __asm__("_ZN24InfraMediaDetectThreadRM20ParseInternalMessageEjPN3MWF6ObjMsgE");
int rm_parse(void *self,unsigned id,void *message) {
    int (*original)(void *,unsigned,void *)=next("_ZN24InfraMediaDetectThreadRM20ParseInternalMessageEjPN3MWF6ObjMsgE");
    int result=original(self,id,message);
    if(a7r5_media_rm_enabled()) {printf("MEDIA_DETECT_PARSE id=%#x result=%d\n",id,result);media_info(self,"parse");}
    return result;
}
void rm_notify(void *self,unsigned media,unsigned queue,signed char inserted,signed char held,unsigned char count,unsigned short extra)
    __asm__("_ZN26InfraMediaDetectThreadBase16NotifyInOutEventEjjaaht");
void rm_notify(void *self,unsigned media,unsigned queue,signed char inserted,signed char held,unsigned char count,unsigned short extra) {
    void (*original)(void *,unsigned,unsigned,signed char,signed char,unsigned char,unsigned short)=next("_ZN26InfraMediaDetectThreadBase16NotifyInOutEventEjjaaht");
    printf("MEDIA_DETECT_NOTIFY media=%#x queue=%#x inserted=%d held=%d count=%u extra=%u\n",media,queue,inserted,held,count,extra);fflush(0);
    original(self,media,queue,inserted,held,count,extra);
}
int rm_start(void *self,unsigned media,void *payload) __asm__("_ZN24InfraMediaDetectThreadRM10StartInOutEjPv");
int rm_start(void *self,unsigned media,void *payload) {
    int (*original)(void *,unsigned,void *)=next("_ZN24InfraMediaDetectThreadRM10StartInOutEjPv");
    printf("MEDIA_DETECT_SUBSCRIBE media=%#x queue=%#x initial=%u\n",media,payload?*(unsigned *)payload:0,payload?((unsigned char *)payload)[4]:0);fflush(0);
    int result=original(self,media,payload);media_info(self,"subscribe");return result;
}
