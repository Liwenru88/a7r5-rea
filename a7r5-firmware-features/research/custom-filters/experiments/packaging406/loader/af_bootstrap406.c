/* 真实Linux/glibc2.25接线。没有模拟后端、默认数据目录或CP准入替代。 */
#include "af_bootstrap406.h"
#include "manifest_types.h"
#include "af_bootstrap_manifest.h"
#include "af_ap_ui.h"
#include "af_ap_lifecycle.h"
#include "af_storage406.h"
#include "af_fsys406.h"
#include "af_media_snapshot406.h"
#include "af_ap_names.h"
#include "af_ap_browser.h"
#include "af_ap_cards.h"
#include "af_ap_requests_binding.h"
#include "af_repository_service.h"
#include "af_imaging406.h"
#include "af_apply.h"
#include "af_sha256.h"
#ifdef AF_TARGET_GLIBC225
#include "af_target_posix.h"
typedef struct {const char *name;void *base;const char *symbol;void *address;} DlInfo;
extern void *mmap(void *,size_t,int,int,int,long);
extern int munmap(void *,size_t),mprotect(void *,size_t,int);
extern void *dlopen(const char *,int),*dlsym(void *,const char *);
extern int dladdr(const void *,DlInfo *);
extern int sscanf(const char *,const char *,...);
#else
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <dlfcn.h>
typedef Dl_info DlInfo;
#endif
#define COUNT(a) (sizeof(a)/sizeof((a)[0]))
#define PAGE(a) ((uintptr_t)(a)&~(uintptr_t)4095)
typedef struct {uintptr_t lo,hi;int flags;} Region;
typedef struct {const BootModule *spec;uint8_t *base;} Loaded;
/* 现场已有1090条；有界扩容实际数组，不能只改比较值而越界写入。 */
static Region regions[2048];static size_t region_count;
static Loaded ui,requests;
static AfApLifecycle natural_registration;
static AfApRegistration natural_receipt;
static uintptr_t observer_base;
static uint32_t observer_word;
static unsigned ctor_attempted,observer_installed;
static void *observer_island;
static void *obj_handle,*repository_handle,*repository_context;
static int native_storage_parent=-1;
static void *fsys_handle,*native_media_source;
static uintptr_t fsys_base;
static AfFsys406 native_media[2];
static unsigned native_media_bound,native_media_importer_bound,native_media_cards_bound;
static int native_media_result=AF_EMPTY;
static int reference_import_result=AF_EMPTY;
static uintptr_t ap_base;
static unsigned attempted,registered,installed,prepared;
/* 自然登记回执不能代替完整产品准入；不提供可伪造成功的设置接口。 */
static volatile unsigned admission_ready;
#ifdef AF_RECIPE_BRIDGE406
/* 仅配对原生分支启用：1等真实握手，2同UI拥有者发布，3结束，4失败。 */
static unsigned startup_phase,startup_busy,startup_changed,startup_live;
static uint32_t startup_after[3];
static uintptr_t startup_owner,startup_manager;
static uintptr_t (*startup_thread)(void);
static uintptr_t (*startup_ui_refresh)(void *);
static const uint32_t *(*startup_menu_getter)(void);
static uint32_t (*startup_capabilities)(void);
static int (*startup_peer_status)(void);
static void *startup_island;
static int startup_result=AF_EMPTY;
#endif
static int last_status=AF_EMPTY;
static AfCatalog *catalog;static AfLabels *labels;static AfApManage *manager;
static unsigned hook_changed;
static int descriptor_protection=-1,parent_protection=-1;
static unsigned descriptor_open,parent_open;
static unsigned manage_menu_enabled,research_enabled;
static uint32_t hook_after[COUNT(boot_hooks)];
static void *island;
static int same(const void *a,const void *b,size_t n){
 const uint8_t *x=a,*y=b;for(size_t i=0;i<n;++i)if(x[i]!=y[i])return 0;return 1;
}
static void bytes(void *to,const void *from,size_t n){uint8_t *a=to;const uint8_t *b=from;for(size_t i=0;i<n;++i)a[i]=b[i];}
static int text_equal(const char *a,const char *b){for(;;++a,++b){if(*a!=*b)return 0;if(!*a)return 1;}}
static int maps(void){
 int fd=open("/proc/self/maps",O_RDONLY|O_CLOEXEC);char data[4096],line[512];size_t used=0,total=0;ssize_t n;
 int good=0;
 region_count=0;if(fd<0)return 0;
 while((n=read(fd,data,sizeof(data)))>0){
  total+=(size_t)n;if(total>262144)goto done;
  for(ssize_t i=0;i<n;++i){
   if(data[i]!='\n'){if(used+1>=sizeof(line))goto done;line[used++]=data[i];continue;}
   line[used]=0;used=0;unsigned long lo,hi;char mode[5]={0};
   if(sscanf(line,"%lx-%lx %4s",&lo,&hi,mode)!=3 || lo>=hi || region_count==COUNT(regions) ||
      (region_count && regions[region_count-1].hi>lo))goto done;
   regions[region_count++]=(Region){lo,hi,(mode[0]=='r'?1:0)|(mode[1]=='w'?2:0)|(mode[2]=='x'?4:0)};
  }
 }
 good=n==0 && !used && region_count;
done:
 if(close(fd))good=0;
 /* 失败时不向后续权限查询遗留已解析的前缀；正常拥有者顺序不变。 */
 if(!good)region_count=0;
 return good;
}
static int protection(uintptr_t at,size_t n){
 if(!n || at>UINTPTR_MAX-n)return -1;
 uintptr_t end=at+n,cursor=at;int flags=-1;
 /* 原挂钩的mprotect/COW可分裂连续VMA；逐段证明完整覆盖，不放过空洞或权限改变。 */
 for(size_t i=0;i<region_count;++i){const Region *r=&regions[i];
  if(r->hi<=cursor)continue;
  if(r->lo>cursor || (flags!=-1 && r->flags!=flags))return -1;
  flags=r->flags;if(end<=r->hi)return flags;cursor=r->hi;
 }
 return -1;
}
/* 仅证明UTF-8资格函数实际读取的区间；完整文件和ELF形状另由同包摘要门控。 */
static int fsys_codec_mapping(uintptr_t base){
 static const uint32_t code[]={0x843bcu,0x85688u,0x9445cu,0x945c4u,
                               0x946ecu,0x94714u,0x94750u,0x94778u};
 if(!base || (base&4095u) || base>UINTPTR_MAX-AF_FSYS406_LIBRARY_SPAN)return 0;
 for(size_t i=0;i<COUNT(code);++i)
  if(protection(base+code[i],i==COUNT(code)-1?8:16)!=5)return 0;
 int got=protection(base+0xb9e68u,8);
 return (got==1||got==3) && protection(base+0xd4418u,0x48)==3;
}
static int jump(uintptr_t from,uintptr_t to,int link,uint32_t *out){
 uint64_t d=from>to?from-to:to-from;
 if((from|to)&3u || d>(1u<<27) || (to>=from && d==(1u<<27)))return 0;
 int64_t delta=to>=from?(int64_t)d:-(int64_t)d;
 *out=(link?0x94000000u:0x14000000u)|((uint32_t)(delta/4)&0x3ffffffu);return 1;
}
static void cache(uintptr_t at,size_t n){
#ifdef AF_TARGET_GLIBC225
 uintptr_t ctr;__asm__ volatile("mrs %0,ctr_el0":"=r"(ctr));
 uintptr_t dl=4ul<<((ctr>>16)&15),il=4ul<<(ctr&15);
 for(uintptr_t p=at&~(dl-1);p<at+n;p+=dl)__asm__ volatile("dc cvau,%0"::"r"(p):"memory");
 __asm__ volatile("dsb ish":::"memory");
 for(uintptr_t p=at&~(il-1);p<at+n;p+=il)__asm__ volatile("ic ivau,%0"::"r"(p):"memory");
 __asm__ volatile("dsb ish\nisb":::"memory");
#else
 __builtin___clear_cache((char *)at,(char *)(at+n));
#endif
}
static int protect_instruction_page(void *page,int flags){return mprotect(page,4096,flags);}
static void flush_instruction(void *at,size_t n){cache((uintptr_t)at,n);}
static int code(uintptr_t at,uint32_t expected,uint32_t value){
 if(!maps() || protection(at,4)!=5 || *(const uint32_t *)at!=expected)return 0;
 int result=af_ap_lifecycle_write((uint32_t *)at,expected,value,protect_instruction_page,flush_instruction);
 /* 双重失败后原页可能仍NX，无法安全执行原ctor；不能伪称继续原厂。 */
 if(result==AF_AP_LIFE_UNSAFE_PERMISSIONS)__builtin_trap();
 return result==AF_OK;
}
static void *file_map(const BootFile *f,int writable){
 struct stat st;int fd=open(f->path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);uint8_t digest[32];void *p;
 if(fd<0)return 0;
 if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_size<0 || (uint64_t)st.st_size!=f->bytes){close(fd);return 0;}
 p=mmap(0,f->bytes,writable?3:1,2,fd,0);int closed=close(fd);
 if(p==(void *)-1)return 0;
 if(closed || af_sha256(p,f->bytes,digest) || !same(digest,f->sha,32)){
  if(munmap(p,f->bytes))__builtin_trap();return 0;
 }
 return p;
}
static int canonical(void){
 uint8_t digest[32];uint8_t *p=file_map(&boot_ap,1);if(!p)return 0;
 for(size_t i=0;i<COUNT(boot_patches);++i){const BootPatch *r=&boot_patches[i];
  if(r->offset>boot_ap.bytes || r->bytes>boot_ap.bytes-r->offset || !same(p+r->offset,r->after,r->bytes)){
   munmap(p,boot_ap.bytes);return 0;
  }
  bytes(p+r->offset,r->before,r->bytes);
 }
 int good=!af_sha256(p,boot_ap.bytes,digest) && same(digest,boot_original_sha,32);
 return munmap(p,boot_ap.bytes)==0 && good;
}
static void *gap(uintptr_t low,uintptr_t high,size_t n){
 if(!n || (n&4095u) || low>=high || n>high-low || !maps())return 0;
 uintptr_t cursor=(low+4095u)&~(uintptr_t)4095;
 for(size_t i=0;i<=region_count;++i){
  uintptr_t start=i<region_count?regions[i].lo:high;
  if(start>cursor && n<=start-cursor && n<=high-cursor){
   void *p=mmap((void *)cursor,n,3,0x22,-1,0);
   if(p!=(void *)-1 && (uintptr_t)p==cursor)return p;
   if(p!=(void *)-1 && munmap(p,n))__builtin_trap();
  }
  if(i<region_count && regions[i].hi>cursor)cursor=(regions[i].hi+4095u)&~(uintptr_t)4095;
  if(cursor>=high || n>high-cursor)break;
 }
 return 0;
}
static void *symbol(const Loaded *m,const char *name){
 if(!m->base)return 0;
 for(size_t i=0;i<m->spec->symbol_count;++i)if(text_equal(name,m->spec->symbols[i].name))return m->base+m->spec->symbols[i].at;
 return 0;
}
static int load(Loaded *m,const BootModule *spec,int near){
 uint8_t *p=file_map(&spec->file,0);if(!p)return 0;
 void *base=near?gap(ap_base+0x3554ec8u-(1u<<27),ap_base+0x3554d24u+(1u<<27),spec->span):mmap(0,spec->span,3,0x22,-1,0);
 if(!base || base==(void *)-1){munmap(p,spec->file.bytes);return 0;}
 m->spec=spec;m->base=base;
 for(size_t i=0;i<spec->segment_count;++i){const BootSegment *s=&spec->segments[i];
  bytes(m->base+s->va,p+s->offset,s->file_bytes);
 }
 for(size_t i=0;i<spec->reloc_count;++i)*(uintptr_t *)(m->base+spec->relocs[i].at)=(uintptr_t)m->base+spec->relocs[i].add;
 return munmap(p,spec->file.bytes)==0;
}
static int seal(const Loaded *m){
 for(size_t i=0;i<m->spec->segment_count;++i){const BootSegment *s=&m->spec->segments[i];
  uintptr_t page=PAGE(m->base+s->va),end=((uintptr_t)m->base+s->va+s->memory_bytes+4095u)&~(uintptr_t)4095;
  if(s->flags&1)cache((uintptr_t)m->base+s->va,s->file_bytes);
  if(mprotect((void *)page,end-page,(s->flags&1)?5:3))return 0;
 }
 return 1;
}
static int word(uintptr_t at,uint32_t expected,int flags){return protection(at,4)==flags && *(const uint32_t *)at==expected;}
#define UF(name,type) ((type)symbol(&ui,name))
static void disable(void){
 if(!registered)return;
 /* 注册后保持模块与名字入口驻留，由当前原UI拥有者恢复可见描述符。 */
 if((manage_menu_enabled || research_enabled) && !maps())__builtin_trap();
 if(manage_menu_enabled){
  if(!parent_open || protection(ap_base+0x594a7b0u,8)!=3 ||
     UF("af_ap_manage_menu_enable",int (*)(uint32_t))(0)!=AF_OK)__builtin_trap();
  manage_menu_enabled=0;
 }
 (void)UF("af_ap_targets_enable",int (*)(uint32_t))(0);
 (void)UF("af_ap_browser_enable",int (*)(uint32_t))(0);
 (void)UF("af_ap_cards_enable",int (*)(uint32_t))(0);
 (void)UF("af_ap_names_enable",int (*)(uint32_t))(0);
 if(research_enabled){
  if(!descriptor_open || protection(ap_base+0x5858b08u,0x80)!=3 ||
     UF("af_ap_research_enable",int (*)(uint32_t))(0)!=AF_OK)__builtin_trap();
  research_enabled=0;
 }
}
static int fail(int result){
 disable();
 unsigned rollback=!registered;
#ifdef AF_RECIPE_BRIDGE406
 /* Task0启动后原代码页可能已有其他执行者，失败只禁用分流并保持模块驻留。 */
 if(startup_live)rollback=0;
#endif
 if(rollback)for(unsigned i=hook_changed;i;i--){const BootHook *h=&boot_hooks[i-1];
  if(!code(ap_base+h->at,hook_after[i-1],h->before))__builtin_trap();
 }
 if(rollback)hook_changed=0;
 if(parent_open && mprotect((void *)PAGE(ap_base+0x594a7b0u),4096,parent_protection))__builtin_trap();
 if(descriptor_open && mprotect((void *)PAGE(ap_base+0x5858b08u),4096,descriptor_protection))__builtin_trap();
 parent_open=descriptor_open=0;
 last_status=result;return result;
}
/* 只在原Task0/消息任务创建之前写代码页；之后发布过程只改元数据。 */
static int install_ui_hooks(void){
 if(hook_changed)return AF_BUSY;
 uintptr_t base=ap_base,low=0,high=UINTPTR_MAX;
 for(size_t i=0;i<COUNT(boot_hooks);++i){uintptr_t at=base+boot_hooks[i].at;
  if(at-(1u<<27)>low)low=at-(1u<<27);
  if(at+(1u<<27)-4096u<high)high=at+(1u<<27)-4096u;
 }
 for(size_t i=0;i<COUNT(boot_hooks);++i){const BootHook *h=&boot_hooks[i];void *target=symbol(&ui,h->name);
  if(!target)return fail(AF_STALE);
  if(!jump(base+h->at,(uintptr_t)target,h->link,&hook_after[i])){
   if(!island)island=gap(low,high,4096);
   if(!island || i*16+16>4096 || !jump(base+h->at,(uintptr_t)island+i*16,h->link,&hook_after[i]))return fail(AF_IO);
   uint32_t *at=(uint32_t *)((uint8_t *)island+i*16);at[0]=0x58000050u;at[1]=0xd61f0200u;*(uintptr_t *)(at+2)=(uintptr_t)target;
  }
 }
 if(island){cache((uintptr_t)island,4096);if(mprotect(island,4096,5))return fail(AF_IO);}
 if(!maps())return fail(AF_IO);
 for(size_t i=0;i<COUNT(boot_hooks);++i)if(!word(base+boot_hooks[i].at,boot_hooks[i].before,5))return fail(AF_STALE);
 for(size_t i=0;i<COUNT(boot_hooks);++i){if(!code(base+boot_hooks[i].at,boot_hooks[i].before,hook_after[i]))return fail(AF_IO);hook_changed++;}
 return AF_OK;
}
#ifdef AF_RECIPE_BRIDGE406
/* 仅prepare失败可逆回滚；启动后不再把原代码页暂时改成NX。 */
static void startup_restore(unsigned keep){
 if(startup_live)return;
 while(startup_changed>keep){unsigned i=startup_changed-1;const BootHook *h=&boot_startup_hooks[i];
  if(!code(ap_base+h->at,startup_after[i],h->before))__builtin_trap();
  startup_changed=i;
 }
}
static int startup_stop(int result){
 __atomic_store_n(&admission_ready,0,__ATOMIC_RELEASE);
 startup_restore(0);startup_phase=4;startup_result=result;return result;
}
static int startup_main_idle(void *owner){
 if(protection((uintptr_t)owner,0x3bcu)!=3 || !startup_menu_getter)return 0;
 uint32_t screen=*(const uint32_t *)((const uint8_t *)owner+0x3b8u);
 if(!(screen==0x2d4 || screen==0x2d5 || screen==0x2d6 || screen==0x2ed))return 0;
 const uint32_t *menu=startup_menu_getter();
 int flags=menu?protection((uintptr_t)menu,4):-1;
 return (flags==1 || flags==3) && *menu==0x2b36;
}
static int startup_admitted(void){
 return startup_live && startup_phase==2 && startup_busy && startup_thread && startup_thread()==startup_owner &&
        startup_peer_status && startup_peer_status()==AF_OK && startup_capabilities &&
        startup_capabilities()==BOOT_STARTUP_REQUIRED && startup_peer_status()==AF_OK &&
        startup_main_idle((void *)startup_manager);
}
static void startup_poll(void *owner,uintptr_t caller){
 if(startup_phase!=1 || startup_busy)return;
 /* 这是原主循环唯一refresh BL；不能把可伪造的manager地址当作线程资格。 */
 if(caller!=ap_base+0x1ec7390u)return;
 startup_busy=1;
 if(!maps() || protection((uintptr_t)owner,sizeof(uintptr_t))!=3 ||
    *(const uintptr_t *)owner!=ap_base+0x58d2fb8u){startup_stop(AF_STALE);goto done;}
 uintptr_t thread=startup_thread();
 if(!thread || (startup_owner && (thread!=startup_owner || (uintptr_t)owner!=startup_manager))){
  startup_stop(AF_STALE);goto done;
 }
 startup_owner=thread;startup_manager=(uintptr_t)owner;
 int peer=startup_peer_status();
 if(peer==AF_BUSY)goto done; /* HELLO未完成；绝不在AppInit或UI刷新中等待。 */
 if(peer!=AF_OK){startup_stop(peer==AF_IO?AF_IO:AF_STALE);goto done;}
 uint32_t caps=startup_capabilities();
 if(caps!=BOOT_STARTUP_REQUIRED){startup_stop(AF_STALE);goto done;}
 /* 已打开的原18项呈现器不能被扩大容量；等原Main空闲再发布元数据。 */
 if(!startup_main_idle(owner))goto done;
 startup_phase=2;
 __atomic_store_n(&admission_ready,1,__ATOMIC_RELEASE);
 int result=af_bootstrap406_publish();
 if(result!=AF_OK){
  if(result==AF_BUSY)result=startup_peer_status()==AF_IO?AF_IO:AF_STALE;
  startup_stop(result);goto done;
 }
 /* 当前UI拥有者串行恢复机内目录。发布过的context与模块继续驻留，失败不重试。 */
 startup_result=af_bootstrap406_bind_native_storage(-1);startup_phase=3;
done:
 startup_busy=0;
}
static uintptr_t startup_refresh(void *owner){
 uintptr_t caller=(uintptr_t)__builtin_return_address(0);
 uintptr_t result=startup_ui_refresh(owner);
 startup_poll(owner,caller);return result;
}
static int startup_install(void){
 if(startup_phase || startup_changed || COUNT(boot_startup_hooks)!=3)return AF_BUSY;
 startup_ui_refresh=UF("af_ap_refresh",uintptr_t (*)(void *));
 startup_menu_getter=(const uint32_t *(*)(void))(ap_base+0x28a87e8u);
 startup_capabilities=symbol(&requests,"af_ap_runtime_preset_capabilities");
 startup_peer_status=symbol(&requests,"af_ap_runtime_preset_status");
 startup_thread=(uintptr_t (*)(void))dlsym(0,"pthread_self");
 if(!startup_ui_refresh || !startup_capabilities || !startup_peer_status || !startup_thread || !maps() ||
    protection((uintptr_t)startup_ui_refresh,4)!=5 || protection((uintptr_t)startup_menu_getter,4)!=5 ||
    protection((uintptr_t)startup_capabilities,4)!=5 ||
    protection((uintptr_t)startup_peer_status,4)!=5 ||
    protection((uintptr_t)startup_thread,4)!=5)return startup_stop(AF_STALE);
 uintptr_t low=0,high=UINTPTR_MAX;
 for(size_t i=0;i<COUNT(boot_startup_hooks);++i){uintptr_t at=ap_base+boot_startup_hooks[i].at;
  if(at-(1u<<27)>low)low=at-(1u<<27);
  if(at+(1u<<27)-4096u<high)high=at+(1u<<27)-4096u;
 }
 for(size_t i=0;i<COUNT(boot_startup_hooks);++i){const BootHook *h=&boot_startup_hooks[i];
  uintptr_t target=i==2?(uintptr_t)startup_refresh:(uintptr_t)symbol(&requests,h->name);
  if(!target)return startup_stop(AF_STALE);
  if(!jump(ap_base+h->at,target,h->link,&startup_after[i])){
   if(!startup_island)startup_island=gap(low,high,4096);
   if(!startup_island || !jump(ap_base+h->at,(uintptr_t)startup_island+i*16,h->link,&startup_after[i]))return startup_stop(AF_IO);
   uint32_t *at=(uint32_t *)((uint8_t *)startup_island+i*16);
   at[0]=0x58000050u;at[1]=0xd61f0200u;*(uintptr_t *)(at+2)=target;
  }
 }
 if(startup_island){cache((uintptr_t)startup_island,4096);if(mprotect(startup_island,4096,5))return startup_stop(AF_IO);}
 if(!maps())return startup_stop(AF_IO);
 for(size_t i=0;i<COUNT(boot_startup_checks);++i)
  if(!word(ap_base+boot_startup_checks[i].at,boot_startup_checks[i].before,5))return startup_stop(AF_STALE);
 int ui_result=install_ui_hooks();if(ui_result!=AF_OK)return startup_stop(ui_result);
 for(size_t i=0;i<COUNT(boot_startup_hooks);++i){const BootHook *h=&boot_startup_hooks[i];
  if(!code(ap_base+h->at,h->before,startup_after[i]))return startup_stop(AF_IO);
  startup_changed++;
 }
 startup_live=1;startup_phase=1;startup_result=AF_BUSY;return AF_OK;
}
#endif
static void original_registration_observer(void *registry,const void *begin,const void *end){
 af_ap_lifecycle_dispatch(&natural_registration,(AfApRegisterFn)(observer_base+0x1c91e94u),registry,begin,end);
}
int af_bootstrap406_early(uintptr_t base){
 unsigned initial=0;
 if(!__atomic_compare_exchange_n(&ctor_attempted,&initial,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return AF_BUSY;
 if(!base || (base&4095u) || base>UINTPTR_MAX-AF_AP_IMAGE_SPAN || !canonical() || !maps())return AF_STALE;
 /* 这里只读取已重定位的ELF指针，不读取尚未由原构造器初始化的树内容/模型。 */
 if((protection(base+BOOT_CTOR_POINTER,8)!=1 && protection(base+BOOT_CTOR_POINTER,8)!=3) ||
    *(const uintptr_t *)(base+BOOT_CTOR_POINTER)!=base+BOOT_CTOR_START ||
    protection(base+BOOT_CTOR_START,BOOT_CTOR_BYTES)!=5 ||
    !same((const void *)(base+BOOT_CTOR_START),boot_ctor_shim,BOOT_CTOR_BYTES) ||
    !word(base+0x16fbfc0u,0x17ffe964u,5) || !word(base+0x1c91e94u,0xa9bc7bfdu,5) ||
    !word(base+0x16f6610u,0x94166e21u,5) || protection(base+0x5915b80u,8)<1)return AF_STALE;
 uintptr_t registry=*(const uintptr_t *)(base+0x5915b80u);
 if(registry!=base+0x7545f20u || protection(registry,0x30)!=3)return AF_STALE;
 observer_base=base;
 if(af_ap_lifecycle_arm(&natural_registration,base,(void *)registry))return AF_STALE;
 uintptr_t target=(uintptr_t)original_registration_observer;
 if(!jump(base+0x16f6610u,target,1,&observer_word)){
  uintptr_t from=base+0x16f6610u;
  observer_island=gap(from-(1u<<27),from+(1u<<27)-4096u,4096);
  if(!observer_island || !jump(from,(uintptr_t)observer_island,1,&observer_word))return AF_IO;
  uint32_t *code_at=observer_island;code_at[0]=0x58000050u;code_at[1]=0xd61f0200u;*(uintptr_t *)(code_at+2)=target;
  cache((uintptr_t)observer_island,16);if(mprotect(observer_island,4096,5))return AF_IO;
 }
 if(!code(base+0x16f6610u,0x94166e21u,observer_word)){natural_registration.phase=AF_AP_LIFE_FAILED;return AF_IO;}
 observer_installed=1;return AF_OK;
}
int af_bootstrap406(uintptr_t base){
 unsigned initial=0;
 if(!__atomic_compare_exchange_n(&attempted,&initial,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return AF_BUSY;
 if(!base || (base&4095u) || base>UINTPTR_MAX-AF_AP_IMAGE_SPAN)return last_status=AF_INVALID;
 ap_base=base;if(!canonical() || !maps())return last_status=AF_STALE;
 uint32_t expected;
 if(!jump(base+0x17feac0u,base+BOOT_SHIM_START,0,&expected) || !word(base+0x17feac0u,expected,5))return last_status=AF_STALE;
 if(protection(base+BOOT_SHIM_START,BOOT_SHIM_BYTES)!=5 || !same((const void *)(base+BOOT_SHIM_START),boot_shim,BOOT_SHIM_BYTES))return last_status=AF_STALE;
 /* AppInit在正常ELF构造完成后进入。先撤下自己的两处入口，再消费原登记完成回执。 */
 if(!code(base+0x17feac0u,expected,0xa9ba7bfdu))return last_status=AF_IO;
 if(!observer_installed || observer_base!=base || !maps() ||
    protection(natural_registration.registration.registry+0x28u,8)<1)return last_status=AF_STALE;
 if(!code(base+0x16f6610u,observer_word,0x94166e21u))return last_status=AF_STALE;
 observer_installed=0;
 if(af_ap_lifecycle_take(&natural_registration,&natural_receipt))return last_status=AF_STALE;
 if(protection(base+0x16d9740u,0x3554ed8u-0x16d9740u)!=5 ||
    (protection(base+0x5858b08u,0x80)!=1 && protection(base+0x5858b08u,0x80)!=3))return last_status=AF_STALE;
 for(size_t i=0;i<COUNT(boot_checks);++i)
  if(!word(base+boot_checks[i].at,boot_checks[i].before,5))return last_status=AF_STALE;
 for(size_t i=0;i<COUNT(boot_assets);++i){void *p=file_map(&boot_assets[i],0);if(!p)return last_status=AF_STALE;if(munmap(p,boot_assets[i].bytes))return last_status=AF_IO;}
 if(!load(&ui,&boot_ui,0) || !load(&requests,&boot_requests,1))return fail(AF_IO);
 for(size_t i=0;i<COUNT(boot_exit_names);++i){uint32_t *at=symbol(&requests,boot_exit_names[i]);
  if(!at || *at!=0xd42080c0u || !jump((uintptr_t)at,base+boot_exit_targets[i],0,&expected))return fail(AF_STALE);
  *at=expected;
 }
 if(!seal(&ui) || !seal(&requests) || !maps())return fail(AF_IO);
 AfApRequestsBinding request_binding={1,sizeof(request_binding),base,AF_AP_IMAGE_SPAN,base+0x17feac0u,{0}};
 bytes(request_binding.ap_sha256,boot_original_sha,32);
 int (*request_bind)(const AfApRequestsBinding *)=symbol(&requests,"af_ap_requests_bind");
 if(!request_bind || request_bind(&request_binding))return fail(AF_STALE);
 /* 此时只解析请求模块；最后才装接收入口，不能用装载成功代替CP握手。 */
 uintptr_t obj_base=0;static const char *const names[3]={"_ZN2ux6gfxeng10TextSprite9setStringEPKc","_ZN2ux6gfxeng10TextSprite9setStringEj","_ZNK2ux6gfxeng10TextSprite9getStringEv"};
 static const uint32_t offsets[3]={0x16d2a4u,0x16d498u,0x16bc64u};
 obj_handle=dlopen("/usr/lib/libObj.so",2);if(!obj_handle)return fail(AF_IO);
 if(!maps())return fail(AF_IO);
 for(unsigned i=0;i<3;++i){void *entry=dlsym(obj_handle,names[i]);DlInfo d;
  if(!entry || !dladdr(entry,&d))return fail(AF_STALE);
#ifdef AF_TARGET_GLIBC225
  uintptr_t found=(uintptr_t)d.base;
#else
  uintptr_t found=(uintptr_t)d.dli_fbase;
#endif
  if(!found || (found&4095u) || (obj_base && obj_base!=found) || (uintptr_t)entry!=found+offsets[i] || protection((uintptr_t)entry,16)!=5)return fail(AF_STALE);obj_base=found;
 }
 AfApBinding binding={1,sizeof(binding),base,AF_AP_IMAGE_SPAN,base+0x17feac0u,{0}};bytes(binding.ap_sha256,boot_original_sha,32);
 if(UF("af_ap_bind",int (*)(const AfApBinding *))(&binding))return fail(AF_STALE);
 labels=symbol(&ui,"af_ap_labels");catalog=symbol(&ui,"af_ap_catalog");manager=symbol(&ui,"af_ap_manager");
 if(!labels || !catalog || !manager)return fail(AF_STALE);
 UF("af_labels_init",void (*)(AfLabels *))(labels);
 AfApNamesBinding nb={1,sizeof(nb),base,obj_base,labels};
 if(UF("af_ap_names_bind",int (*)(const AfApNamesBinding *))(&nb))return fail(AF_STALE);
 if(!maps())return fail(AF_IO);
 for(size_t i=0;i<COUNT(boot_checks);++i)if(!word(base+boot_checks[i].at,boot_checks[i].before,5))return fail(AF_STALE);
 prepared=1;
#ifdef AF_RECIPE_BRIDGE406
 int startup=startup_install();if(startup!=AF_OK)return fail(startup);
#endif
 return last_status=AF_OK;
}
static int native_imaging_resolve(void *context,AfApImagingBinding *out){
 if(context!=&ap_base || !out)return AF_INVALID;
 /* 保持原产品准入；未装消息gate或未协商时不制造就绪。 */
 if(!__atomic_load_n(&installed,__ATOMIC_ACQUIRE) || !admission_ready)return AF_BUSY;
 int (*resolve)(uintptr_t,AfApImagingBinding *)=symbol(&requests,"af_imaging406_binding");
 return resolve?resolve(ap_base,out):AF_STALE;
}
int af_bootstrap406_publish(void){
 if(__atomic_load_n(&installed,__ATOMIC_ACQUIRE) || !prepared || !admission_ready)return AF_BUSY;
#ifdef AF_RECIPE_BRIDGE406
 if(!startup_admitted())return AF_BUSY;
#endif
 uintptr_t base=ap_base;
#ifdef AF_RECIPE_BRIDGE406
 /* 所有代码入口在原任务启动前已安装。活跃期只核对，不再写RX页。 */
 if(!maps() || hook_changed!=COUNT(boot_hooks) || startup_changed!=COUNT(boot_startup_hooks))return fail(AF_STALE);
 for(size_t i=0;i<COUNT(boot_hooks);++i)
  if(!word(base+boot_hooks[i].at,hook_after[i],5))return fail(AF_STALE);
 for(size_t i=0;i<COUNT(boot_startup_hooks);++i)
  if(!word(base+boot_startup_hooks[i].at,startup_after[i],5))return fail(AF_STALE);
#else
 int hook_result=install_ui_hooks();if(hook_result!=AF_OK)return hook_result;
#endif
 /* 原registry必须完成原构造；不可重放清空树的构造段。 */
 if(!maps() || protection(base+0x5915b80u,8)<1)return fail(AF_STALE);
 uintptr_t registry=*(const uintptr_t *)(base+0x5915b80u);
 if(!registry || protection(registry+0x28u,8)<1 || *(const uintptr_t *)(registry+0x28u)!=5591)return fail(AF_STALE);
 descriptor_protection=protection(base+0x5858b08u,0x80);parent_protection=protection(base+0x594a7b0u,0x80);
 if((descriptor_protection!=1 && descriptor_protection!=3) || (parent_protection!=1 && parent_protection!=3))return fail(AF_STALE);
 if(mprotect((void *)PAGE(base+0x5858b08u),4096,3))return fail(AF_IO);
 descriptor_open=1;
 if(UF("af_ap_after_original_registration",int (*)(const AfApRegistration *))(&natural_receipt))return fail(AF_STALE);registered=1;
 AfApManageMenuBinding mb={1,sizeof(mb),base,manager,catalog};
 AfApTargetsBinding tb={AF_AP_TARGETS_VERSION,sizeof(tb),base,catalog,catalog,UF("af_ap_manage_ui_chosen",int (*)(void *,const AfApTargetChoice *))};
 AfApBrowserBinding bb={1,sizeof(bb),base};
 AfApCardsBinding cb={AF_AP_CARDS_VERSION,sizeof(cb),base};
 if(UF("af_ap_manage_menu_bind",int (*)(const AfApManageMenuBinding *))(&mb) || UF("af_ap_manage_menu_register",int (*)(void))() ||
    UF("af_ap_targets_bind",int (*)(const AfApTargetsBinding *))(&tb) || UF("af_ap_targets_register",int (*)(void))() ||
    UF("af_ap_browser_bind",int (*)(const AfApBrowserBinding *))(&bb) || UF("af_ap_browser_register",int (*)(void))() ||
    UF("af_ap_cards_bind",int (*)(const AfApCardsBinding *))(&cb) || UF("af_ap_cards_register",int (*)(void))())return fail(AF_STALE);
 AfApManagePicker picker={1,sizeof(picker),catalog,UF("af_ap_manage_ui_open",int (*)(void *,uint32_t,uint32_t)),(AF_MANAGE_CAP_PERSIST&~AF_MANAGE_CAP(AF_MANAGE_SAVE))|AF_MANAGE_CAP(AF_MANAGE_IMPORT)|AF_MANAGE_CAP(AF_MANAGE_EXPORT),0};
 if(UF("af_ap_manage_picker_bind",int (*)(const AfApManagePicker *))(&picker) ||
    UF("af_ap_targets_enable",int (*)(uint32_t))(1) || UF("af_ap_browser_enable",int (*)(uint32_t))(1) || UF("af_ap_cards_enable",int (*)(uint32_t))(1))return fail(AF_STALE);
 if(UF("af_ap_research_enable",int (*)(uint32_t))(1))return fail(AF_STALE);
 research_enabled=1;
 if(UF("af_ap_names_enable",int (*)(uint32_t))(1))return fail(AF_STALE);
 if(mprotect((void *)PAGE(base+0x594a7b0u),4096,3))return fail(AF_IO);parent_open=1;
 if(UF("af_ap_manage_menu_enable",int (*)(uint32_t))(1))return fail(AF_IO);
 manage_menu_enabled=1;
 AfApImagingProvider imaging_source={AF_AP_IMAGING_PROVIDER_VERSION,sizeof(imaging_source),&ap_base,native_imaging_resolve};
 if(UF("af_ap_imaging_provider_bind",int (*)(const AfApImagingProvider *))(&imaging_source))return fail(AF_STALE);
 if(mprotect((void *)PAGE(base+0x594a7b0u),4096,parent_protection) || mprotect((void *)PAGE(base+0x5858b08u),4096,descriptor_protection))__builtin_trap();
 parent_open=descriptor_open=0;
 __atomic_store_n(&installed,1,__ATOMIC_RELEASE);return last_status=AF_OK;
}
int af_bootstrap406_status(void){return last_status;}
int af_bootstrap406_startup_status(void){
#ifdef AF_RECIPE_BRIDGE406
 return startup_result;
#else
 return AF_EMPTY;
#endif
}
int af_bootstrap406_reference_status(void){return reference_import_result;}
int af_bootstrap406_bind_storage(int parent,int library){
 if(!installed || repository_context || parent<0 || library< -1)return AF_BUSY;
 void *p=file_map(&boot_repository,0);if(!p)return AF_STALE;if(munmap(p,boot_repository.bytes))return AF_IO;
 repository_handle=dlopen(boot_repository.path,2);if(!repository_handle)return AF_IO;
 void *(*open_service)(int,AfCatalog *,AfLabels *,int *)=dlsym(repository_handle,"af_repository_service_open");
 int (*bind_library)(void *,int)=dlsym(repository_handle,"af_repository_service_bind_library");
 uint32_t (*caps)(void *)=dlsym(repository_handle,"af_repository_service_capabilities");
 int (*pump)(void *,AfApManage *)=dlsym(repository_handle,"af_repository_service_pump");
 if(!open_service || !bind_library || !caps || !pump)return AF_STALE;
 int status=AF_IO;repository_context=open_service(parent,catalog,labels,&status);
 if(!repository_context)return status;
 if(library>=0 && bind_library(repository_context,library))return AF_IO;
 /* 先初始化CUBE转换，再捕获UI能力；模型失败仍保留电脑配方导入及保存菜单。 */
 int (*bind_reference)(void *)=dlsym(repository_handle,"af_reference_import_bind");
 reference_import_result=bind_reference?bind_reference(repository_context):AF_EMPTY;
 #ifdef AF_RECIPE_BRIDGE406
 /* 完整配方的源与发送器均须确实存在；旧构建不宣告LUT发送能力。 */
 int (*bind_recipe)(const AfImaging406RecipeSource *)=symbol(&requests,"af_imaging406_bind_recipe_source");
 int (*capture_recipe)(void *,uint32_t,const AfPreset *,uint64_t,uint64_t,AfRecipeTx *)=
     dlsym(repository_handle,"af_repository_service_recipe_capture");
 if(!bind_recipe||!capture_recipe)return AF_STALE;
 {
  AfImaging406RecipeSource source={AF_IMAGING406_RECIPE_SOURCE_VERSION,sizeof(source),repository_context,capture_recipe};
  if(bind_recipe(&source)!=AF_OK)return AF_STALE;
 }
 #endif
 AfApManageService service={1,sizeof(service),repository_context,pump,caps(repository_context),0};
 return UF("af_ap_manage_service_bind",int (*)(const AfApManageService *))(&service);
}
int af_bootstrap406_bind_native_storage(int library){
 /* 产品准入未成立时连目录资格检查也不执行，更不能创建仓库标记。 */
 if(!installed || repository_context || native_storage_parent>=0 || library< -1)return AF_BUSY;
 int parent=-1;
 if(af_storage406_open(&parent)!=AF_STORAGE406_OK)return AF_IO;
 int result=af_bootstrap406_bind_storage(parent,library);
 /* 与驻留context成对持有；发布后不再执行会改变成功回执的关闭操作。 */
 if(repository_context){
  native_storage_parent=parent;
  /* SD资格失败不撤销已经发布的body服务；两类回执独立。 */
  if(result==AF_OK)native_media_result=af_bootstrap406_bind_native_media(0);
  return result;
 }
 if(close(parent)){native_storage_parent=parent;return AF_IO;}
 return result;
}
static int native_media_snapshot(void *context,uint8_t output[AF_FSYS406_SNAPSHOT_BYTES]){
 if(context!=&ap_base || !installed)return AF_MANAGE_NOT_READY;
 AfMediaSnapshot406 snapshot;
 int result=af_ap_media_snapshot406(ap_base,AF_AP_IMAGE_SPAN,&snapshot);
 if(!result)bytes(output,snapshot.bytes,sizeof(snapshot.bytes));return result;
}
static int native_media_utf8(void *context){
 if(context!=&fsys_base || !installed || !fsys_base)return AF_MANAGE_NOT_READY;
 /* DSO保持驻留，但每次仍重读映射权限；不得先解引用未知GOT或模块指针。 */
 if(!maps() || !fsys_codec_mapping(fsys_base))return AF_STALE;
 return af_fsys406_utf8_policy(fsys_base,AF_FSYS406_LIBRARY_SPAN);
}
static int native_media_select(void *context,uint32_t slot){
 if(context!=&ap_base||!native_media_cards_bound)return AF_MANAGE_NOT_READY;
 return af_bootstrap406_bind_native_media(slot);
}
int af_bootstrap406_bind_native_media(unsigned slot){
 if(!installed || !repository_context)return native_media_result=AF_BUSY;
 if(slot>1)return native_media_result=AF_INVALID;
 if(native_media_bound&&(!native_media_importer_bound||!native_media_cards_bound))return native_media_result=AF_MANAGE_NOT_READY;
 int (*bind)(const AfApMediaProviderBinding *)=UF("af_ap_media_provider_bind",int (*)(const AfApMediaProviderBinding *));
 int (*rebind)(const AfApMediaProviderBinding *)=UF("af_ap_media_provider_rebind",int (*)(const AfApMediaProviderBinding *));
 int (*bind_importer)(const AfApMediaProviderImporter *)=UF("af_ap_media_provider_importer_bind",int (*)(const AfApMediaProviderImporter *));
 int (*bind_cards)(const AfApMediaCardService *)=UF("af_ap_media_card_service_bind",int (*)(const AfApMediaCardService *));
 if(!bind||!rebind||!bind_importer||!bind_cards)return native_media_result=AF_STALE;
 /* 完整文件身份、动态导出归属、原前像及执行权限必须一致。 */
 void *p=file_map(&boot_fsys,0);if(!p)return native_media_result=AF_STALE;
 if(munmap(p,boot_fsys.bytes))return native_media_result=AF_IO;
 if(!fsys_handle)fsys_handle=dlopen(boot_fsys.path,2);
 if(!fsys_handle || !maps())return native_media_result=AF_IO;
 void *functions[5];uintptr_t base=0;
 for(unsigned i=0;i<5;++i){
  DlInfo info;functions[i]=dlsym(fsys_handle,boot_fsys_exports[i].name);
  if(!functions[i] || !dladdr(functions[i],&info))return native_media_result=AF_STALE;
#ifdef AF_TARGET_GLIBC225
  uintptr_t found=(uintptr_t)info.base;
#else
  uintptr_t found=(uintptr_t)info.dli_fbase;
#endif
  if(!found||(found&4095u)||found>UINTPTR_MAX-AF_FSYS406_LIBRARY_SPAN)return native_media_result=AF_STALE;
  if(!i)base=found;
  if(found!=base ||
     (uintptr_t)functions[i]!=base+boot_fsys_exports[i].at)return native_media_result=AF_STALE;
 }
 for(unsigned i=0;i<COUNT(boot_fsys_checks);++i)
  if(!word(base+boot_fsys_checks[i].at,boot_fsys_checks[i].before,5))return native_media_result=AF_STALE;
 if((fsys_base&&fsys_base!=base)||!fsys_codec_mapping(base))return native_media_result=AF_STALE;
 fsys_base=base;
 if(!native_media[slot].initialized){
  AfFsys406Binding b={AF_FSYS406_VERSION,sizeof(b),slot,0,&ap_base,native_media_snapshot,
   {(int32_t (*)(const char *,uint64_t *,uint32_t))functions[0],
    (int32_t (*)(uint64_t,void *,int32_t))functions[1],(int32_t (*)(uint64_t))functions[2],
    (int32_t (*)(const char *,uint8_t,void *))functions[3],(int32_t (*)(void *))functions[4]},
   &fsys_base,native_media_utf8};
  int result=af_fsys406_init(&native_media[slot],&b);if(result)return native_media_result=result;
 }
 if(!native_media_source){
  p=mmap(0,AF_MEDIA_SOURCE_MAX,3,0x22,-1,0);
  if(!p || p==(void *)-1)return native_media_result=AF_IO;
  native_media_source=p;
 }
 AfApMediaProviderBinding binding={AF_AP_MEDIA_VERSION,sizeof(binding),{0},native_media_source,AF_MEDIA_SOURCE_MAX};
 int result=af_fsys406_provider(&native_media[slot],&binding.provider);
 if(result)return native_media_result=result;
 if(native_media_bound)return native_media_result=rebind(&binding);
 int (*importer)(void *,AfApMediaProviderImporter *)=dlsym(repository_handle,"af_repository_service_media_provider_importer");
 if(!importer)return native_media_result=AF_STALE;
 AfApMediaProviderImporter service;
 result=importer(repository_context,&service);if(result)return native_media_result=result;
 result=bind(&binding);
 if(result)return native_media_result=result;
 native_media_bound=1;
 result=bind_importer(&service);if(result)return native_media_result=result;
 native_media_importer_bound=1;
 AfApMediaCardService cards={AF_AP_MEDIA_VERSION,sizeof(cards),&ap_base,native_media_select};
 result=bind_cards(&cards);if(!result)native_media_cards_bound=1;
 return native_media_result=result;
}
int af_bootstrap406_media_status(void){return native_media_result;}
#ifdef AF_BOOTSTRAP_HOST_TEST
int af_bootstrap406_test_canonical(void){return canonical();}
#endif
