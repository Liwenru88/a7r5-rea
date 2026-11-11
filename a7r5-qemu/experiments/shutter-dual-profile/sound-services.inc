/* 仅用于QEMU的虚拟卡和音频服务，原菜单、导入、保存、调度均执行候选AP。 */
#include "r5_shutter_backend.h"
extern long lseek(int,long,int);
extern int memcmp(const void *,const void *,unsigned long);
static const char *sound_names[2]={"机械咔嗒.R5S","电子轻响.R5S"};
static unsigned sound_find_index,sound_starts,sound_stops,sound_installs;
static unsigned sound_playing,sound_epoch,sound_last_volume,sound_last_bytes;
static unsigned long sound_deadline;
static unsigned long sound_ms(void){long time[2];if(syscall(113,1,time))__builtin_trap();return time[0]*1000UL+time[1]/1000000UL;}
static int sound_fs_open(const char *path,unsigned mode,unsigned long *handle){
 if(!path||!handle||path[0]!='A'||path[1]!=':'||path[2]!='/')return -1;
 if(mode!=1)return -1;
 char local[320];int valid=same_name(path+3,"R5NATIVE.BIN");
 for(unsigned i=0;i<2;i++)valid|=same_name(path+3,sound_names[i]);
 if(!valid||getenv("R5_SOUND_NO_CARD"))return -1;
 snprintf(local,sizeof local,"/simulation/%s",path+3);int fd=open(local,0);
 if(fd<0)return -1;*handle=(unsigned long)fd;return 0;
}
static int sound_fs_read(unsigned long fd,void *p,unsigned long cap,unsigned long *got){
 if(fd>1024||!p||!got||cap>65536)return -1;long n=read((int)fd,p,cap);if(n<0)return -1;*got=(unsigned long)n;return 0;
}
static int sound_fs_close(unsigned long fd){return fd<=1024?close((int)fd):-1;}
static int sound_find_info(void *buffer){
 if(!buffer)return 1;if(sound_find_index>=2)return 4;
 unsigned char *info=buffer;for(unsigned i=0;i<4096;i++)info[i]=0;
 char path[320];snprintf(path,sizeof path,"/simulation/%s",sound_names[sound_find_index]);
 int fd=open(path,0);if(fd<0)return 1;long bytes=lseek(fd,0,2);int closed=close(fd);if(bytes<0||closed)return 1;
 *(unsigned long *)info=(unsigned long)(info+0x100);*(unsigned long *)(info+8)=(unsigned long)bytes;
 const char *name=sound_names[sound_find_index];unsigned i=0;do{info[0x100+i]=(unsigned char)name[i];}while(name[i++]);
 return 0;
}
static int sound_find_first(const char *path,void *info){if(!same_name(path,"A:/*"))return 1;sound_find_index=0;return sound_find_info(info);}
static int sound_find_next(void *info){sound_find_index++;return sound_find_info(info);}
static void sound_log(unsigned drive,const char *stage,const char *name,int rc,const unsigned *values,unsigned count){
 (void)drive;char line[1024];int n=snprintf(line,sizeof line,"%s rc=%d name=%s",stage,rc,name?name:"");
 for(unsigned i=0;i<count&&n>0&&(unsigned)n+12<sizeof line;i++)n+=snprintf(line+n,sizeof line-(unsigned)n," %08x",values[i]);
 record("A7R5_R5_SOUND_LOG ",line);
}
static int sound_owner(unsigned *token){if(!token)return -1;*token=0x5153554e;return 0;}
static int sound_epoch_bind(unsigned epoch){sound_epoch=epoch;return 0;}
static int sound_authorize_first(r5ss_native_backend *b,unsigned token){if(!b||token!=0x5153554e)return -1;b->session_witness=token;return 0;}
static int sound_poll(void *unused){(void)unused;if(sound_playing&&sound_ms()>=sound_deadline)sound_playing=0;return (int)sound_playing;}
static int sound_active(void){return sound_poll(0);}
static int sound_resume(r5ss_native_backend *b){if(sound_poll(b))return 1;b->registered=b->mapped=b->ap_owned=0;return 0;}
static int sound_stage(r5ss_native_backend *b,unsigned generation,const unsigned char *p,unsigned bytes,unsigned padded,unsigned volume){
 if(!b||!p||!generation||!bytes||padded!=bytes+64||volume<1||volume>10||sound_poll(b))return -1;
 for(unsigned i=bytes;i<padded;i++)if(p[i])return -1;
 b->encoded=p;b->encoded_bytes=bytes;b->padded_bytes=padded;b->offered_generation=generation;b->volume_step=volume;return 0;
}
static int sound_install(void *ctx,unsigned generation){
 r5ss_native_backend *b=ctx;if(!b||!b->encoded||b->offered_generation!=generation||sound_poll(b))return -1;
 b->registered=1;b->installed_generation=generation;b->installed_bytes=b->encoded_bytes;
 sound_last_volume=b->volume_step;sound_last_bytes=b->encoded_bytes;sound_installs++;b->encoded=0;
 char line[120];snprintf(line,sizeof line,"generation=%u bytes=%u volume=%u backend=fixture",generation,sound_last_bytes,sound_last_volume);record("A7R5_R5_SOUND_INSTALL ",line);return 0;
}
static int sound_unload(r5ss_native_backend *b){if(sound_poll(b))return 1;b->registered=0;b->installed_generation=0;b->encoded=0;return 0;}
static int sound_stop(void *ctx){(void)ctx;sound_stops++;sound_deadline=sound_ms()+20;return 0;}
static int sound_authorize(void *ctx){
 r5ss_native_backend *b=ctx;
 unsigned silent=((unsigned(*)(void))(n12_base+SILENT_GET))();
 unsigned signals=((unsigned(*)(void))(n12_base+SIGNALS_GET))();
 return b&&b->session_witness&&silent==1&&signals<3;
}
static int sound_start(void *ctx,unsigned generation,unsigned serial){
 r5ss_native_backend *b=ctx;if(!b||!b->registered||b->installed_generation!=generation||sound_poll(b)||!sound_authorize(b))return -1;
 sound_playing=1;sound_deadline=sound_ms()+60;sound_starts++;char line[100];snprintf(line,sizeof line,"generation=%u serial=%u starts=%u backend=fixture",generation,serial,sound_starts);record("A7R5_R5_SOUND_START ",line);return 0;
}
static void sound_diagnostics(unsigned *out){for(unsigned i=0;i<21;i++)out[i]=0;out[0]=1;}
static void sound_observe(volatile unsigned char *out){
 *(volatile unsigned *)(out+2320)=((unsigned(*)(void))(n12_base+SOUND_COUNT))();
 for(unsigned g=0;g<2;g++){
  *(volatile unsigned *)(out+2324+4*g)=((unsigned(*)(unsigned))(n12_base+PROFILE_SELECTED))(g);
  *(volatile unsigned *)(out+2332+4*g)=((unsigned(*)(unsigned))(n12_base+PROFILE_VOLUME))(g);
 }
 *(volatile unsigned *)(out+2340)=((unsigned(*)(void))(n12_base+SOUND_SELECTED))();
 *(volatile unsigned *)(out+2344)=((unsigned(*)(void))(n12_base+SOUND_VOLUME))();
 *(volatile unsigned *)(out+2348)=sound_installs;*(volatile unsigned *)(out+2352)=sound_starts;
 *(volatile unsigned *)(out+2356)=sound_stops;*(volatile unsigned *)(out+2360)=sound_last_volume;
 *(volatile unsigned *)(out+2364)=sound_last_bytes;*(volatile unsigned *)(out+2368)=sound_epoch;
}
static void sound_install_services(void){
 SOUND_INSTALL_DETOURS
 record("A7R5_R5_SOUND_FIXTURE_BOUNDARY ","native UI/catalog/profile/scheduler; virtual SD and audio backend; no sound hardware proof");
}
