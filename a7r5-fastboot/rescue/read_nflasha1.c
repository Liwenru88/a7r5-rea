#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <time.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>
#include <CoreFoundation/CoreFoundation.h>

static IOUSBInterfaceInterface300 **usb; static UInt8 inp, outp;
static int last_version_verified;
static int allowed(const char *s) {
    return !strcmp(s,"getvar:version") || !strcmp(s,"oem partition") ||
           !strcmp(s,"oem partition dump nflasha 0 0x80") ||
           !strcmp(s,"oem partition dump nflasha 0x80 0xbf80") ||
           !strcmp(s,"oem partition dump nflasha2") ||
           !strcmp(s,"oem partition dump nflasha3") ||
           !strcmp(s,"oem partition dump nflasha5") ||
           !strcmp(s,"oem partition dump nflasha8") ||
           !strcmp(s,"oem partition dump nflasha15") ||
           !strcmp(s,"oem partition dump nflasha 0xc000 0xa000") ||
           /* 仅开放固定的状态、芯片编号和 4 KiB NOR 头部查询。 */
           !strcmp(s,"oem cetus") ||
           !strcmp(s,"oem cetus norcmd:9f:3") ||
           !strcmp(s,"oem cetus dumpnor:0:1000") ||
           !strcmp(s,"oem dumpbrom") || !strcmp(s,"reboot") || !strncmp(s,"upload:/",8);
}
static int readbuf(void *b, UInt32 *n) {
    IOReturn r=(*usb)->ReadPipeTO(usb,inp,b,n,5000,5000);
    if(r){fprintf(stderr,"ReadPipeTO=0x%08x\n",r);return -1;} return 0;
}
static int command(const char *arg) {
    last_version_verified=0;
    const char *cmd=!strncmp(arg,"upload:",7)?"upload":arg;
    printf("COMMAND %s\n",cmd); fflush(stdout);
    IOReturn r=(*usb)->WritePipeTO(usb,outp,(void*)cmd,(UInt32)strlen(cmd),5000,5000);
    if(r){fprintf(stderr,"WritePipeTO=0x%08x\n",r);return -1;}
    for(int replies=0;replies<256;replies++){
        unsigned char b[65537]; UInt32 n=64;
        if(readbuf(b,&n))return -1; b[n]=0;
        if(n<4){fprintf(stderr,"Short response %u\n",n);return -1;}
        printf("REPLY %.*s\n",(int)n,b); fflush(stdout);
        if(!memcmp(b,"OKAY",4)){
            last_version_verified=!strcmp(cmd,"getvar:version") && n==7 && !memcmp(b,"OKAY0.5",7);
            return 0;
        }
        if(!memcmp(b,"FAIL",4))return -1;
        if(!memcmp(b,"INFO",4))continue;
        if(!memcmp(b,"DATA",4)&&!strncmp(arg,"upload:/",8)&&n==12){
            unsigned long total=strtoul((char*)b+4,NULL,16),done=0;
            /* Permit bounded readback of the explicitly whitelisted partitions. */
            /* 最大只读目标 nflasha15 的完整容量为 715 MiB。 */
            if(total==0 || total>715UL*1024UL*1024UL)return -1;
            int f=open(arg+7,O_WRONLY|O_CREAT|O_EXCL,0600); if(f<0){perror("output");return -1;}
            while(done<total){UInt32 chunk=(UInt32)(total-done);if(chunk>65536)chunk=65536;
                if(readbuf(b,&chunk)||!chunk||chunk>total-done){close(f);return -1;}
                if(write(f,b,chunk)!=(ssize_t)chunk){close(f);return -1;} done+=chunk;}
            fsync(f);close(f);printf("SAVED %lu bytes %s\n",done,arg+7);fflush(stdout);continue;
        }
        fprintf(stderr,"Unexpected response\n");return -1;
    } return -1;
}
static int open_fastboot_interface(void) {
    io_iterator_t it=0; io_service_t svc;
    kern_return_t kr=IOServiceGetMatchingServices(kIOMainPortDefault,IOServiceMatching(kIOUSBInterfaceClassName),&it);
    if(kr!=KERN_SUCCESS)return 3;
    while((svc=IOIteratorNext(it))){
        IOCFPlugInInterface **p=NULL; IOUSBInterfaceInterface300 **candidate=NULL; SInt32 score;
        kr=IOCreatePlugInInterfaceForService(svc,kIOUSBInterfaceUserClientTypeID,kIOCFPlugInInterfaceID,&p,&score);
        IOObjectRelease(svc); if(kr!=KERN_SUCCESS||!p)continue;
        HRESULT hr=(*p)->QueryInterface(p,CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID300),(LPVOID*)&candidate); (*p)->Release(p);
        if(hr||!candidate)continue;
        UInt16 vid=0,pid=0; UInt8 cls=0,sub=0,proto=0;
        (*candidate)->GetDeviceVendor(candidate,&vid); (*candidate)->GetDeviceProduct(candidate,&pid);
        (*candidate)->GetInterfaceClass(candidate,&cls); (*candidate)->GetInterfaceSubClass(candidate,&sub); (*candidate)->GetInterfaceProtocol(candidate,&proto);
        if(vid!=0x18d1||pid!=0x4ee0||cls!=255||sub!=66||proto!=3){(*candidate)->Release(candidate);continue;}
        usb=candidate; break;
    }
    IOObjectRelease(it);
    if(!usb){fprintf(stderr,"No Fastboot interface\n");return 5;}
    kr=(*usb)->USBInterfaceOpen(usb);
    if(kr!=KERN_SUCCESS){fprintf(stderr,"USBInterfaceOpen=0x%08x\n",kr);(*usb)->Release(usb);usb=NULL;return 6;}
    UInt8 count=0; (*usb)->GetNumEndpoints(usb,&count);
    for(UInt8 p=1;p<=count;p++){UInt8 dir,num,type,interval;UInt16 packet;
        (*usb)->GetPipeProperties(usb,p,&dir,&num,&type,&packet,&interval);
        printf("PIPE %u dir=%u endpoint=%u type=%u packet=%u\n",p,dir,num,type,packet);
        if(type==kUSBBulk){if(dir==kUSBIn)inp=p;else outp=p;}}
    return inp&&outp?0:10;
}

static volatile sig_atomic_t hold_running=1;
static void stop_hold(int signal_number) { (void)signal_number; hold_running=0; }

static void close_usb(void) {
    if(usb){(*usb)->USBInterfaceClose(usb);(*usb)->Release(usb);usb=NULL;}
}

static int write_hold_status(const char *path, const char *state, unsigned long heartbeats,
                             time_t last_success, int error, int initial) {
    char temporary[PATH_MAX];
    int length=snprintf(temporary,sizeof(temporary),"%s.tmp.%ld",path,(long)getpid());
    if(length<0 || (size_t)length>=sizeof(temporary)){errno=ENAMETOOLONG;return -1;}
    int fd=open(temporary,O_WRONLY|O_CREAT|O_EXCL,0600);
    if(fd<0)return -1;
    FILE *file=fdopen(fd,"w");
    if(!file){close(fd);unlink(temporary);return -1;}
    int result=fprintf(file,"{\"pid\":%ld,\"state\":\"%s\",\"heartbeats\":%lu,"
                      "\"last_success_unix\":%lld,\"error_code\":%d}\n",
                      (long)getpid(),state,heartbeats,(long long)last_success,error)<0?-1:0;
    if(fclose(file))result=-1;
    /* 首次发布拒绝已有路径；后续原子替换本进程的状态文件。 */
    if(!result)result=initial?link(temporary,path):rename(temporary,path);
    unlink(temporary);
    return result;
}

static int configured_interface_present(void) {
    /* 只检查系统注册表中的接口，不打开设备或发送 USB 请求。 */
    CFMutableDictionaryRef matching=IOServiceMatching(kIOUSBInterfaceClassName);
    if(!matching)return -3;
    CFStringRef keys[]={CFSTR(kUSBVendorID),CFSTR(kUSBProductID),CFSTR("bInterfaceClass"),
                        CFSTR("bInterfaceSubClass"),CFSTR("bInterfaceProtocol")};
    SInt32 values[]={0x18d1,0x4ee0,255,66,3};
    for(unsigned int index=0;index<5;index++){
        CFNumberRef value=CFNumberCreate(kCFAllocatorDefault,kCFNumberSInt32Type,&values[index]);
        if(!value){CFRelease(matching);return -3;}
        CFDictionarySetValue(matching,keys[index],value);CFRelease(value);
    }
    io_iterator_t iterator=0;io_service_t service;
    kern_return_t result=IOServiceGetMatchingServices(kIOMainPortDefault,matching,&iterator);
    if(result!=KERN_SUCCESS){printf("HOLD registry error=0x%08x\n",result);return -3;}
    int count=0;
    while((service=IOIteratorNext(iterator))){count++;IOObjectRelease(service);}
    IOObjectRelease(iterator);
    return count>1?-4:count;
}

static int hold_session(const char *status_path) {
    if(status_path[0]!='/' || write_hold_status(status_path,"starting",0,0,0,1)){
        perror("hold status");return 64;
    }
    signal(SIGTERM,stop_hold);signal(SIGINT,stop_hold);signal(SIGHUP,SIG_IGN);
    unsigned long heartbeats=0;time_t last_success=0;
    if(write_hold_status(status_path,"waiting_for_usb",0,0,0,0)){perror("hold status");return 64;}
    puts("HOLD waiting_for_usb; registry inspection only");
    int available=0,error=0;
    while(hold_running && !(available=configured_interface_present()))sleep(2);
    if(hold_running)error=available<0?-available:open_fastboot_interface();
    while(hold_running && !error){
        /* 保持模式只发送固定的只读版本查询，不接受其他命令。 */
        if(command("getvar:version"))error=8;
        else if(!last_version_verified)error=9;
        if(error)break;
        heartbeats++;last_success=time(NULL);
        printf("HOLD heartbeat=%lu\n",heartbeats);
        if(write_hold_status(status_path,"connected",heartbeats,last_success,0,0)){
            perror("hold status");error=11;break;
        }
        if(hold_running)sleep(5);
    }
    close_usb();
    if(error && hold_running){
        printf("HOLD blocked error=%d; no automatic reconnect\n",error);
        if(write_hold_status(status_path,"blocked",heartbeats,last_success,error,0))perror("hold status");
        /* 异常时保留后台进程供检查，不复位、重启、重配或重新连接。 */
        while(hold_running)sleep(1);
    }
    if(write_hold_status(status_path,"stopped",heartbeats,last_success,error,0))perror("hold status");
    return 0;
}

int main(int argc,char **argv){
    setbuf(stdout,NULL);
    if(argc==3 && !strcmp(argv[1],"--hold"))return hold_session(argv[2]);
    for(int i=1;i<argc;i++)if(!allowed(argv[i])){fprintf(stderr,"Rejected command: %s\n",argv[i]);return 2;}
    int result=open_fastboot_interface();
    for(int i=1;!result&&i<argc;i++)if(command(argv[i]))result=8;
    close_usb(); return result;
}
