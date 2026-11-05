/* 仅在新的隔离4.06客体中使用；原Application_System_Init仍直接返回给调用方。 */
#include "af_ap_ui.h"
#include "af_sha256.h"
#include "af_ap_names.h"
#include "af_ap_browser.h"
#include "af_ap_media.h"
#include "ui406-hooks.h"
extern long lseek(int,long,int);
extern int dlclose(void *);
extern char *dlerror(void);
extern int unlink(const char *);
static unsigned long ui406_base;
static unsigned int ui406_installed,ui406_seen;
static void *ui406_module,*ui406_island,*ui406_obj;
static int (*ui406_enable)(unsigned int);
static int (*ui406_unbind)(void);
static int (*ui406_names_enable)(unsigned int);
static int (*ui406_labels_publish)(AfLabels *,unsigned int,unsigned long,const char *,size_t);
static int (*ui406_label_refresh)(unsigned int);
static AfLabels *ui406_labels;
static unsigned long ui406_name_generation;
static AfCatalog *ui406_catalog;
static AfApManage *ui406_manager;
static int (*ui406_manage_configure)(const AfApManageRequest *);
static int (*ui406_manage_result)(void);
static unsigned int (*ui406_manage_focus)(void);
static unsigned int (*ui406_nested_state)(void),(*ui406_nested_screen)(void);
static int (*ui406_nested_result)(void);
static unsigned int (*ui406_targets_stage)(void);
static unsigned int (*ui406_media_phase_query)(void);
static int (*ui406_media_result_query)(void),(*ui406_media_snapshot_query)(AfApMediaInfo *);
static const char *(*ui406_media_name_query)(void);
static int ui406_media_directory=-1;static void *ui406_media_source;
static void *ui406_repository_module,*ui406_repository_context;
static int (*ui406_read)(const AfCatalog *,unsigned int,int,AfPreset *);
static int (*ui406_dirty)(const AfCatalog *,unsigned int);
static unsigned int ui406_fixture_seeded;
static AfPreset ui406_fixture_initial,ui406_fixture_saved;
static unsigned int ui406_reset_active;
static AfCatalog ui406_reset_catalog;
static unsigned int ui406_reset_native[163],ui406_reset_ui_base;
static void ui406_stop(const char *message);
struct ui406_saved { unsigned long node,record;unsigned int key; };
static struct ui406_saved ui406_before[5591];

static int ui406_same(const void *a,const void *b,unsigned long count) {
    const unsigned char *x=a,*y=b;
    for(unsigned long i=0;i<count;i++)if(x[i]!=y[i])return 0;
    return 1;
}
static int ui406_file(const char *path,unsigned long size,const unsigned char wanted[32]) {
    int fd=open(path,0x20000|0x80000);unsigned char digest[32];
    if(fd<0)return 0;
    if(lseek(fd,0,2)!=(long)size){close(fd);return 0;}
    void *p=mmap(0,size,1,2,fd,0);int closed=close(fd);
    if(p==(void *)-1)return 0;
    int good=!closed && af_sha256(p,size,digest)==0 && ui406_same(digest,wanted,32);
    if(munmap(p,size))good=0;
    return good;
}
static int ui406_protection(unsigned long address) {
    int fd=open("/proc/self/maps",0);char block[4096],line[512];
    unsigned long count=0,length=0;int found=-1;long got;
    if(fd<0)return -1;
    while((got=read(fd,block,sizeof block))>0) {
        count+=(unsigned long)got;if(count>262144){found=-1;break;}
        for(long i=0;i<got;i++) {
            if(block[i]!='\n') {if(length+1>=sizeof line){close(fd);return -1;}line[length++]=block[i];continue;}
            line[length]=0;length=0;unsigned long start,end;char mode[5]={0};
            if(sscanf(line,"%lx-%lx %4s",&start,&end,mode)==3 && start<=address && address<end)
                found=(mode[0]=='r'?1:0)|(mode[1]=='w'?2:0)|(mode[2]=='x'?4:0);
        }
    }
    if(close(fd))return -1;
    return found;
}
static int ui406_branch(unsigned long from,unsigned long to,int link,unsigned int *word) {
    long delta=(long)to-(long)from;
    if((from|to)&3 || delta<-(1L<<27) || delta>=(1L<<27))return 0;
    *word=(link?0x94000000U:0x14000000U)|((unsigned long)(delta/4)&0x3ffffffU);return 1;
}
static void *ui406_gap(unsigned long low,unsigned long high) {
    int fd=open("/proc/self/maps",0);char block[4096],line[512];
    unsigned long cursor=(low+4095)&~4095UL,total=0,length=0;long got;
    if(fd<0)return 0;
    while((got=read(fd,block,sizeof block))>0) {
        total+=(unsigned long)got;if(total>262144)break;
        for(long i=0;i<got;i++) {
            if(block[i]!='\n'){if(length+1>=sizeof line){close(fd);return 0;}line[length++]=block[i];continue;}
            line[length]=0;length=0;unsigned long start,end;
            if(sscanf(line,"%lx-%lx",&start,&end)!=2){close(fd);return 0;}
            if(end<=cursor)continue;
            if(start>cursor && cursor+4096<=start && cursor+4096<=high) {
                /* 只请求真实空闲页；内核不采纳提示时释放，不覆盖任何已有映射。 */
                void *p=mmap((void *)cursor,4096,3,0x22,-1,0);
                if(p!=(void *)-1 && (unsigned long)p==cursor){close(fd);return p;}
                if(p!=(void *)-1 && munmap(p,4096))ui406_stop("unaccepted island mapping cannot be released");
            }
            if(end>cursor)cursor=(end+4095)&~4095UL;
            if(cursor+4096>high){close(fd);return 0;}
        }
    }
    if(close(fd))return 0;
    if(cursor+4096<=high) {
        void *p=mmap((void *)cursor,4096,3,0x22,-1,0);
        if(p!=(void *)-1 && (unsigned long)p==cursor)return p;
        if(p!=(void *)-1 && munmap(p,4096))ui406_stop("final island mapping cannot be released");
    }
    return 0;
}
static int ui406_code(unsigned long address,unsigned int expected,unsigned int value,int protection) {
    unsigned int *p=(void *)address;void *page=(void *)(address&~4095UL);
    if(*p!=expected || ui406_protection(address)!=protection || !(protection&4))return 0;
    if(mprotect(page,4096,(protection|2)&~4))return 0;
    *p=value;clear_cache_range(p,4);
    if(mprotect(page,4096,protection))ui406_stop("written instruction page cannot restore protection");
    return 1;
}
static int ui406_tree(unsigned long registry,int after) {
    unsigned long stack[64],node=*(unsigned long *)(registry+0x10),depth=0,count=0,old=0,new_count=0;
    unsigned int previous=0;
    while(node || depth) {
        while(node) {if(depth==64)return 0;stack[depth++]=node;node=*(unsigned long *)(node+0x10);}
        node=stack[--depth];unsigned int key=*(unsigned int *)(node+0x20);
        unsigned long record=*(unsigned long *)(node+0x28);
        if(count && key<=previous)return 0;previous=key;
        if(!after) {
            if(count>=5591)return 0;
            ui406_before[count]=(struct ui406_saved){node,record,key};
        } else if(old<5591 && key==ui406_before[old].key) {
            if(node!=ui406_before[old].node || record!=ui406_before[old].record)return 0;
            old++;
        } else {
            unsigned int wanted=after==2 && new_count>=19?AF_MANAGE_MENU_CLEAR+(unsigned int)new_count-19:
                new_count<43?0x15d9+(unsigned int)new_count:0x1620+(unsigned int)new_count-43;
            unsigned long maximum=after>=3?111UL:after==2?21UL:14UL;
            if(new_count>=maximum || key!=wanted)return 0;new_count++;
        }
        count++;if(count>(after>=3?5702UL:after==2?5612UL:5605UL))return 0;node=*(unsigned long *)(node+0x18);
    }
    if(count!=*(unsigned long *)(registry+0x28))return 0;
    return after?(count==(after>=3?5702UL:after==2?5612UL:5605UL) && old==5591 && new_count==(after>=3?111UL:after==2?21UL:14UL)):count==5591;
}
static void ui406_stop(const char *message) {
    record("A7R5_UI406_CONFLICT ",message);__builtin_trap();
}
static void ui406_install(void *symbol) {
    if(ui406_seen++){record("A7R5_UI406_REJECTED ","duplicate init anchor");return;}
    Dl_info info;char text[220];unsigned long b,registry;int bound=0,registered=0,changed=0,descriptor_protection=-1;
    const char *stage="resolve entry symbols";
    if(!real_dladdr(symbol,&info) || (unsigned long)symbol-(unsigned long)info.dli_fbase!=0x17feac0) {
        record("A7R5_UI406_REJECTED ","AP anchor mismatch");return;
    }
    b=(unsigned long)info.dli_fbase;
    snprintf(text,sizeof text,"phase=Application_System_Init-dlsym tid=%ld base=%#lx ui_thread=%u screen_created=%u",
             syscall(178),b,ui_thread_id,create_screen_returned);record("A7R5_UI406_BEGIN ",text);
    if(ui_thread_id || create_screen_returned){record("A7R5_UI406_REJECTED ","UI already initialized");return;}
    record("A7R5_UI406_HASH_BEGIN ","AP read-only file");
    if(!ui406_file("/usr/lib/appFw.so",97368304,ui406_ap_sha) ||
       !ui406_file("/usr/lib/libObj.so",2888984,ui406_obj_sha) ||
       !ui406_file("/tmp/images/MYingHeiC-GB18030-SJ_wIcon.ltt",UI406_FONT_0_BYTES,ui406_font_0_sha) ||
       !ui406_file("/tmp/images/MYingHeiC-Big5-SJ_wIcon.ltt",UI406_FONT_1_BYTES,ui406_font_1_sha) ||
       !ui406_file("/tmp/images/Sony_DI_Icons.ttf",UI406_FONT_2_BYTES,ui406_font_2_sha) ||
       !ui406_file("/simulation/af-ui-dynamic.so",UI406_MODULE_BYTES,ui406_module_sha)) {
        record("A7R5_UI406_REJECTED ","AP or module SHA-256 mismatch");return;
    }
    record("A7R5_UI406_HASH_OK ","AP, same-package libObj and dynamic module complete file digests");
    registry=*(unsigned long *)(b+0x5915b80);
    if(!registry || !ui406_tree(registry,0)){record("A7R5_UI406_REJECTED ","original 5591-row registry not ready");return;}
    for(unsigned int i=0;i<UI406_HOOK_COUNT;i++) {
        struct ui406_hook *h=&ui406_hooks[i];h->address=b+h->offset;
        h->protection=ui406_protection(h->address);
        if(*(unsigned int *)h->address!=h->before || h->protection!=5) {
            record("A7R5_UI406_REJECTED ","hook preimage or RX page differs");return;
        }
    }
    ui406_module=real_dlopen("/simulation/af-ui-dynamic.so",2);
    if(!ui406_module){record("A7R5_UI406_REJECTED ",dlerror());return;}
    int (*bind)(const AfApBinding *)=real_dlsym(ui406_module,"af_ap_bind");
    void (*attach)(void *,const void *,const void *)=real_dlsym(ui406_module,"af_ap_register");
    ui406_enable=real_dlsym(ui406_module,"af_ap_research_enable");ui406_unbind=real_dlsym(ui406_module,"af_ap_unbind");
    int (*names_bind)(const AfApNamesBinding *)=real_dlsym(ui406_module,"af_ap_names_bind");
    void (*labels_init)(AfLabels *)=real_dlsym(ui406_module,"af_labels_init");
    ui406_names_enable=real_dlsym(ui406_module,"af_ap_names_enable");
    ui406_labels=real_dlsym(ui406_module,"af_ap_labels");
    ui406_labels_publish=real_dlsym(ui406_module,"af_labels_publish");
    ui406_label_refresh=real_dlsym(ui406_module,"af_ap_label_refresh");
    int (*manage_bind)(const AfApManageMenuBinding *)=real_dlsym(ui406_module,"af_ap_manage_menu_bind");
    int (*manage_register)(void)=real_dlsym(ui406_module,"af_ap_manage_menu_register");
    int (*manage_enable)(unsigned int)=real_dlsym(ui406_module,"af_ap_manage_menu_enable");
    int (*service_bind)(const AfApManageService *)=real_dlsym(ui406_module,"af_ap_manage_service_bind");
    int (*picker_bind)(const AfApManagePicker *)=real_dlsym(ui406_module,"af_ap_manage_picker_bind");
    int (*ui_open)(void *,unsigned int,unsigned int)=real_dlsym(ui406_module,"af_ap_manage_ui_open");
    int (*ui_chosen)(void *,const AfApTargetChoice *)=real_dlsym(ui406_module,"af_ap_manage_ui_chosen");
    int (*target_bind)(const AfApTargetsBinding *)=real_dlsym(ui406_module,"af_ap_targets_bind");
    int (*target_register)(void)=real_dlsym(ui406_module,"af_ap_targets_register");
    int (*target_enable)(unsigned int)=real_dlsym(ui406_module,"af_ap_targets_enable");
    int (*browser_bind)(const AfApBrowserBinding *)=real_dlsym(ui406_module,"af_ap_browser_bind");
    int (*browser_register)(void)=real_dlsym(ui406_module,"af_ap_browser_register");
    int (*browser_enable)(unsigned int)=real_dlsym(ui406_module,"af_ap_browser_enable");
    int (*media_bind)(const AfApMediaBinding *)=real_dlsym(ui406_module,"af_ap_media_bind");
    ui406_targets_stage=real_dlsym(ui406_module,"af_ap_targets_stage");
    ui406_nested_state=real_dlsym(ui406_module,"af_ap_manage_ui_state");
    ui406_nested_screen=real_dlsym(ui406_module,"af_ap_manage_ui_screen");
    ui406_nested_result=real_dlsym(ui406_module,"af_ap_manage_ui_result");
    ui406_media_phase_query=real_dlsym(ui406_module,"af_ap_media_phase");
    ui406_media_result_query=real_dlsym(ui406_module,"af_ap_media_result");
    ui406_media_snapshot_query=real_dlsym(ui406_module,"af_ap_media_snapshot");
    ui406_media_name_query=real_dlsym(ui406_module,"af_ap_media_name");
    if(!picker_bind || !ui_open || !ui_chosen || !target_bind || !target_register || !target_enable ||
       !browser_bind || !browser_register || !browser_enable || !media_bind || !ui406_nested_state ||
       !ui406_nested_screen || !ui406_nested_result || !ui406_targets_stage || !ui406_media_phase_query ||
       !ui406_media_result_query || !ui406_media_snapshot_query || !ui406_media_name_query)goto rejected;

    ui406_catalog=real_dlsym(ui406_module,"af_ap_catalog");ui406_manager=real_dlsym(ui406_module,"af_ap_manager");
    ui406_manage_configure=real_dlsym(ui406_module,"af_ap_manage_menu_configure");
    ui406_manage_result=real_dlsym(ui406_module,"af_ap_manage_menu_result");
    ui406_manage_focus=real_dlsym(ui406_module,"af_ap_manage_menu_current");
    ui406_read=real_dlsym(ui406_module,"af_read");ui406_dirty=real_dlsym(ui406_module,"af_dirty");
    if(!bind || !attach || !ui406_enable || !ui406_unbind || !names_bind || !labels_init ||
       !ui406_names_enable || !ui406_labels || !ui406_labels_publish || !ui406_label_refresh ||
       !manage_bind || !manage_register || !manage_enable || !service_bind || !ui406_catalog ||
       !ui406_manager || !ui406_manage_configure || !ui406_read || !ui406_dirty)goto rejected;
    stage="resolve same-package Obj base";
    ui406_obj=real_dlopen("/usr/lib/libObj.so",2);
    if(!ui406_obj)goto rejected;
    const char *obj_names[3]={"_ZN2ux6gfxeng10TextSprite9setStringEPKc",
        "_ZN2ux6gfxeng10TextSprite9setStringEj","_ZNK2ux6gfxeng10TextSprite9getStringEv"};
    const unsigned int obj_offsets[3]={0x16d2a4,0x16d498,0x16bc64};
    unsigned long obj_base=0;
    for(unsigned int i=0;i<3;i++) {
        void *entry=real_dlsym(ui406_obj,obj_names[i]);Dl_info location;
        if(!entry || !real_dladdr(entry,&location) || !location.dli_fbase ||
           (unsigned long)entry-(unsigned long)location.dli_fbase!=obj_offsets[i] ||
           (obj_base && obj_base!=(unsigned long)location.dli_fbase) || ui406_protection((unsigned long)entry)!=5)
            goto rejected;
        obj_base=(unsigned long)location.dli_fbase;
    }
    if((unsigned long)ui406_labels%_Alignof(AfLabels) ||
       ui406_protection((unsigned long)ui406_labels)!=3 ||
       ui406_protection((unsigned long)ui406_labels+sizeof(*ui406_labels)-1)!=3)goto rejected;
    stage="resolve hook symbols and allocate island";
    for(unsigned int i=0;i<UI406_HOOK_COUNT;i++) {
        struct ui406_hook *h=&ui406_hooks[i];h->target=(unsigned long)real_dlsym(ui406_module,h->name);
        if(!h->target){record("A7R5_UI406_MISSING_SYMBOL ",h->name);goto rejected;}
        if(ui406_protection(h->target)!=5){record("A7R5_UI406_MODULE_PERM ",h->name);goto rejected;}
        if(!ui406_branch(h->address,h->target,h->link,&h->after)) {
            if(!ui406_island) {
                snprintf(text,sizeof text,"name=%s source=%#lx target=%#lx delta=%ld",h->name,h->address,h->target,(long)h->target-(long)h->address);
                record("A7R5_UI406_FAR_TARGET ",text);
                unsigned long low=0,high=~0UL;
                for(unsigned int j=0;j<UI406_HOOK_COUNT;j++) {
                    unsigned long address=b+ui406_hooks[j].offset;
                    if(address-(1UL<<27)>low)low=address-(1UL<<27);
                    if(address+(1UL<<27)-4096<high)high=address+(1UL<<27)-4096;
                }
                ui406_island=ui406_gap(low,high);
                snprintf(text,sizeof text,"low=%#lx high=%#lx mapped=%p",low,high,ui406_island);record("A7R5_UI406_ISLAND ",text);
                if(!ui406_island)goto rejected;
            }
            unsigned long island=(unsigned long)ui406_island+i*16;
            if(!ui406_branch(h->address,island,h->link,&h->after)){record("A7R5_UI406_UNREACHABLE_ISLAND ",h->name);goto rejected;}
            unsigned int *stub=(void *)island;stub[0]=0x58000050;stub[1]=0xd61f0200;
            *(unsigned long *)(stub+2)=h->target;
        }
    }
    void *rows_symbol=real_dlsym(ui406_module,"af_ap_rows");
    if(!rows_symbol || ui406_protection((unsigned long)rows_symbol)!=3){record("A7R5_UI406_MODULE_PERM ","af_ap_rows must be RW");goto rejected;}
    if(ui406_island){clear_cache_range(ui406_island,4096);if(mprotect(ui406_island,4096,5))goto rejected;}
    stage="bind source context";
    for(unsigned int i=0;i<UI406_CHECK_COUNT;i++) {
        unsigned int actual=*(unsigned int *)(b+ui406_checks[i][0]);
        if(actual!=ui406_checks[i][1]) {
            snprintf(text,sizeof text,"offset=%#x expected=%#x actual=%#x",ui406_checks[i][0],ui406_checks[i][1],actual);
            record("A7R5_UI406_BIND_PREIMAGE ",text);
        }
    }
    AfApBinding binding={1,sizeof binding,b,AF_AP_IMAGE_SPAN,(unsigned long)symbol,{0}};
    for(unsigned int i=0;i<32;i++)binding.ap_sha256[i]=ui406_ap_sha[i];
    int bind_result=bind(&binding);
    snprintf(text,sizeof text,"result=%d binding_bytes=%u span=%#lx descriptor_count=%u descriptor_rows=%#lx expected_rows=%#lx",
             bind_result,binding.bytes,(unsigned long)binding.mapped_bytes,*(unsigned int *)(b+0x5858b08+0x54),
             *(unsigned long *)(b+0x5858b08+0x58),b+0x3f4a280);record("A7R5_UI406_BIND ",text);
    if(bind_result)goto rejected;bound=1;
    labels_init(ui406_labels);
    AfApNamesBinding names_binding={1,sizeof names_binding,b,obj_base,ui406_labels};
    if(names_bind(&names_binding))goto rejected;
    snprintf(text,sizeof text,"obj_base=%#lx labels=%p bytes=%lu before_hooks=1",obj_base,ui406_labels,sizeof(*ui406_labels));
    record("A7R5_UI406_NAMES_BOUND ",text);
    stage="descriptor protection";
    descriptor_protection=ui406_protection(b+0x5858b08);
    if(descriptor_protection<1 || descriptor_protection&4)goto rejected;
    stage="install inbound instructions";
    for(unsigned int i=0;i<UI406_HOOK_COUNT;i++) {
        struct ui406_hook *h=&ui406_hooks[i];
        if(!ui406_code(h->address,h->before,h->after,h->protection))goto rejected;
        changed=i+1;
    }
    if(mprotect((void *)((b+0x5858b08)&~4095UL),4096,descriptor_protection|2))goto rejected;
    stage="late registry append and list enable";
    /* 原静态构造器已经运行；只调用幂等注册器，绝不重放清空树的构造段。 */
    attach((void *)registry,(void *)(b+0x5030590),(void *)(b+0x5046300));registered=1;
    if(!ui406_tree(registry,1))goto rejected;
    stage="management bind and native registry append";
    unsigned long cache_flag=*(unsigned long *)(b+0x5966518);
    snprintf(text,sizeof text,"initialized=%u flag_offset=%#lx before_management_register=1",
        *(const unsigned char *)cache_flag,cache_flag-b);record("A7R5_UI406_MENU_CACHE ",text);
    AfApManageMenuBinding management={1,sizeof management,b,ui406_manager,ui406_catalog};
    if(manage_bind(&management) || manage_register() || !ui406_tree(registry,2))goto rejected;
    stage="target and media browser bind and registry append";
    AfApTargetsBinding targets={AF_AP_TARGETS_VERSION,sizeof targets,b,ui406_catalog,ui406_catalog,ui_chosen};
    AfApBrowserBinding browser={1,sizeof browser,b};
    if(target_bind(&targets) || browser_bind(&browser) || target_register() || browser_register() ||
       !ui406_tree(registry,3) || target_enable(1) || browser_enable(1))goto rejected;

    if(getenv("A7R5_UI406_STORAGE")) {
        stage="real repository service bind";
        if(!ui406_file("/simulation/libaf_repository.so",UI406_REPOSITORY_BYTES,ui406_repository_sha))goto rejected;
        stage="repository service dlopen";
        ui406_repository_module=real_dlopen("/simulation/libaf_repository.so",2);
        if(!ui406_repository_module) {record("A7R5_UI406_REPO_DLOPEN_ERROR ",dlerror());goto rejected;}
        stage="repository service exported symbols";
        void *(*repository_open)(int,AfCatalog *,AfLabels *,int *)=real_dlsym(ui406_repository_module,"af_repository_service_open");
        unsigned int (*capabilities)(void *)=real_dlsym(ui406_repository_module,"af_repository_service_capabilities");
        int (*pump)(void *,AfApManage *)=real_dlsym(ui406_repository_module,"af_repository_service_pump");
        if(!repository_open || !capabilities || !pump)goto rejected;
        stage="repository private tmpfs directory";
        /* Linux AArch64常量来自af_target_posix.h，不能使用宿主x86的目录标志。 */
        int directory=open("/tmp/a7r5-custom-filters-lab",040000|0100000|02000000),status=-99;
        if(directory<0)goto rejected;
        int (*fxstat)(int,int,void *)=real_dlsym(0,"__fxstat");unsigned long metadata[16]={0};
        if(!fxstat || fxstat(0,directory,metadata))ui406_stop("private parent stat ABI failed");
        unsigned int populated=0;
        for(unsigned int i=0;i<AF_USERS;i++)if(ui406_catalog->slots[i].present ||
            ui406_catalog->slots[i].saved_revision || ui406_catalog->slots[i].pending.request)populated++;
        snprintf(text,sizeof text,"directory_mode=%#x directory_uid=%u catalog_populated=%u pid=%ld",
            *(unsigned int *)((char *)metadata+16),*(unsigned int *)((char *)metadata+24),populated,syscall(172));
        record("A7R5_UI406_REPO_ARGUMENTS ",text);
        ui406_repository_context=repository_open(directory,ui406_catalog,ui406_labels,&status);
        if(close(directory) || !ui406_repository_context) {
            snprintf(text,sizeof text,"status=%d context=%p",status,ui406_repository_context);
            record("A7R5_UI406_REPO_REJECTED ",text);goto rejected;
        }
        unsigned int caps=capabilities(ui406_repository_context);
        AfApManageService service={1,sizeof service,ui406_repository_context,pump,caps,0};
        /* 同一ABI的旧服务仍可保存/创建；未声明CLEAR能力时只禁用该行。 */
        if((caps!=0x0bu && caps!=0x1bu && caps!=AF_MANAGE_CAP_PERSIST) || service_bind(&service))goto rejected;
        snprintf(text,sizeof text,"status=%d capabilities=%#x private_tmpfs_parent=1 source_memory_seed=0 CP=disabled",status,caps);
        record("A7R5_UI406_REPO_READY ",text);
    }
    unsigned int picker_caps=AF_MANAGE_CAP(AF_MANAGE_COPY)|AF_MANAGE_CAP(AF_MANAGE_CREATE)|AF_MANAGE_CAP(AF_MANAGE_CLEAR)|AF_MANAGE_CAP(AF_MANAGE_RENAME);
    if(getenv("A7R5_UI406_MEDIA")) {
        stage="explicit test RAM media directory bind";
        if(!ui406_repository_module)goto rejected;
        AfApMediaScan scan=real_dlsym(ui406_repository_module,"af_media_scan");
        AfApMediaRead media_read=real_dlsym(ui406_repository_module,"af_media_read");
        void *(*allocate)(unsigned long,unsigned long)=real_dlsym(0,"calloc");
        if(!scan || !media_read || !allocate)goto rejected;
        ui406_media_directory=open("/tmp/a7r5-explicit-lut-library",040000|0100000|02000000);
        ui406_media_source=allocate(1,AF_MEDIA_SOURCE_MAX);
        if(ui406_media_directory<0 || !ui406_media_source)goto rejected;
        AfApMediaBinding media={1,sizeof media,ui406_media_directory,0,scan,media_read,ui406_media_source,AF_MEDIA_SOURCE_MAX};
        if(media_bind(&media))goto rejected;
        picker_caps|=AF_MANAGE_CAP(AF_MANAGE_IMPORT);
        record("A7R5_UI406_MEDIA_READY ","explicit_directory=/tmp/a7r5-explicit-lut-library source=guest_RAM_library_fixture scan=real read=double_checked conversion_capability=0 buffer=4MiB");
    }
    AfApManagePicker picker={1,sizeof picker,ui406_catalog,ui_open,picker_caps,0};
    if(picker_bind(&picker))goto rejected;
    if(getenv("A7R5_UI406_SEED_C07")) {
        int (*install)(AfCatalog *,unsigned int,const AfPreset *,int)=real_dlsym(ui406_module,"af_install");
        ui406_catalog=real_dlsym(ui406_module,"af_ap_catalog");
        ui406_read=real_dlsym(ui406_module,"af_read");ui406_dirty=real_dlsym(ui406_module,"af_dirty");
        if(!install || !ui406_catalog || !ui406_read || !ui406_dirty)ui406_stop("fixture symbols unavailable");
        AfPreset preset={0};preset.params[6]=3;
        /* 只在此独立实验内装入一个有标识的ST纯参数夹具；不是产品默认值或保存。 */
        unsigned char before[32],after[32];
        if(af_sha256(ui406_catalog,sizeof(*ui406_catalog),before))ui406_stop("fixture prehash failed");
        AfSlot first_six[6];for(unsigned int i=0;i<6;i++)first_six[i]=ui406_catalog->slots[i];
        unsigned long next=ui406_catalog->next_request;
        if(install(ui406_catalog,7,&preset,0))ui406_stop("C07 fixture install failed");
        for(unsigned int i=0;i<6;i++)if(!ui406_same(&first_six[i],&ui406_catalog->slots[i],sizeof(AfSlot)))
            ui406_stop("fixture changed old six slots");
        for(unsigned int i=0;i<20;i++)if(i!=6 && ui406_catalog->slots[i].present)ui406_stop("fixture filled another slot");
        if(next!=ui406_catalog->next_request || af_sha256(ui406_catalog,sizeof(*ui406_catalog),after) || ui406_same(before,after,32))
            ui406_stop("fixture ownership or state unchanged");
        ui406_fixture_seeded=1;record("A7R5_UI406_FIXTURE ","slot=C07 base=ST params=0,0,0,0,0,0,3,0 memory_only=1 CP=disabled save=disabled");
        ui406_fixture_initial=ui406_catalog->slots[6].initial;
        ui406_fixture_saved=ui406_catalog->slots[6].saved;
    }
    if(ui406_enable(1))goto rejected;
    if(ui406_names_enable(1))goto rejected;
    stage="management parent publication";
    int management_protection=ui406_protection(b+0x594a7b0);
    if(management_protection<1 || (management_protection&4) ||
       mprotect((void *)((b+0x594a7b0)&~4095UL),4096,management_protection|2) || manage_enable(1))goto rejected;
    if(mprotect((void *)((b+0x594a7b0)&~4095UL),4096,management_protection))ui406_stop("management descriptor protection restore failed");
    if(mprotect((void *)((b+0x5858b08)&~4095UL),4096,descriptor_protection))ui406_stop("descriptor protection restore failed");
    ui406_base=b;ui406_installed=1;
    snprintf(text,sizeof text,"base=%#lx nodes=5702 original_nodes_preserved=5591 new_nodes=111 hooks=%u rows=33 island=%p CP=disabled repository=%s management_rows=6",
             b,UI406_HOOK_COUNT,ui406_island,getenv("A7R5_UI406_STORAGE")?"bound":"unavailable");record("A7R5_UI406_READY ",text);return;
rejected:
    snprintf(text,sizeof text,"stage=%s bound=%d registered=%d changed=%d descriptor_protection=%d",stage,bound,registered,changed,descriptor_protection);
    record("A7R5_UI406_REJECT_STAGE ",text);
    /* 注册以后原对象可能持有私有文字标记；保留入口并停止，不能热恢复sprite BL。 */
    if(registered)ui406_stop("registered module cannot detach; retain all name entry points");
    for(int i=changed-1;i>=0;i--) {
        struct ui406_hook *h=&ui406_hooks[i];
        if(!ui406_code(h->address,h->after,h->before,h->protection))ui406_stop("instruction rollback ownership conflict");
    }
    if(ui406_island){if(munmap(ui406_island,4096))ui406_stop("island rollback failed");ui406_island=0;}
    if(!registered && bound && ui406_unbind())ui406_stop("preinit unbind failed");
    if(!registered){if(dlclose(ui406_module))ui406_stop("preinit dlclose failed");ui406_module=0;}
    if(ui406_obj){if(dlclose(ui406_obj))ui406_stop("preinit Obj dlclose failed");ui406_obj=0;}
    record("A7R5_UI406_REJECTED ",registered?"hooks restored; registered module resident":"preinit loader rejected and released");
}
/* 仅本客体的显式名称文档夹具；原UI线程处理固定请求，不写产品或机内存储。 */
static void ui406_name_fixture_poll(void) {
    if(!ui406_fixture_seeded || !getenv("A7R5_UI406_NAMES_FIXTURE"))return;
    const char *paths[3]={"/tmp/a7r5-ui406-name-E","/tmp/a7r5-ui406-name-Z","/tmp/a7r5-ui406-name-T"};
    const char commands[3]={'E','Z','T'};char command=0;
    for(unsigned int i=0;i<3;i++) {
        int fd=open(paths[i],0);if(fd<0)continue;
        if(command || close(fd) || unlink(paths[i]))ui406_stop("conflicting name fixture requests");
        command=commands[i];
    }
    if(!command)return;
    const char *name=0;unsigned long count=0;
    if(command=='E'){name="Film C07";count=8;}
    else if(command=='Z'){name="暖光·城市";count=14;}
    else if(command!='T')ui406_stop("unknown name fixture request");
    unsigned long generation=ui406_name_generation+1;
    if(!generation || ui406_labels_publish(ui406_labels,7,generation,name,count) || ui406_label_refresh(7))
        ui406_stop("name fixture publication or refresh rejected");
    ui406_name_generation=generation;
    char text[220];snprintf(text,sizeof text,"action=%c slot=7 generation=%lu bytes=%lu tid=%u memory_document_fixture=1 label_refresh=1 save=disabled",
        command,generation,count,ui_thread_id);record("A7R5_UI406_NAME_FIXTURE ",text);
}
static void ui406_reset_native_read(unsigned int values[163]) {
    const unsigned int offsets[10]={0x28ae4b0,0x28c54cc,0x28c5544,0x28c556c,0x28c5594,
        0x28c55bc,0x28c55e4,0x28c560c,0x28c5634,0x28c565c};
    for(unsigned int i=0,position=0;i<10;i++) {
        const unsigned int *(*get)(void)=(void *)(ui406_base+offsets[i]);const unsigned int *p=get();
        for(unsigned int j=0;j<(i?18:1);j++)values[position++]=p[j];
    }
}
/* 显式测试请求在原UI线程采集/核对，不定位或改写对话框指针、焦点与返回值。 */
static void ui406_reset_fixture_poll(void) {
    if(!ui406_fixture_seeded || !getenv("A7R5_UI406_NAMES_FIXTURE"))return;
    const char *paths[3]={"/tmp/a7r5-ui406-reset-arm","/tmp/a7r5-ui406-reset-cancel","/tmp/a7r5-ui406-reset-confirm"};
    const char commands[3]={'A','C','F'};char command=0;
    for(unsigned int i=0;i<3;i++) {
        int fd=open(paths[i],0);if(fd<0)continue;int closed=close(fd);
        if(command || closed || unlink(paths[i]))ui406_stop("conflicting reset fixture requests");
        command=commands[i];
    }
    if(!command)return;
    const unsigned int *(*current)(void)=(void *)(ui406_base+0x28a87e8);
    const unsigned int *(*label)(void)=(void *)(ui406_base+0x28c5684);
    if(*current()!=0x15d9)ui406_stop("reset fixture current slot differs");
    if(command=='A') {
        if(ui406_reset_active)ui406_stop("reset fixture already armed");
        ui406_reset_catalog=*ui406_catalog;ui406_reset_native_read(ui406_reset_native);
        ui406_reset_ui_base=*label();ui406_reset_active=1;
        record("A7R5_UI406_RESET_FIXTURE ","action=A snapshot_only=1 original_arrays=163 private_catalog=1 UI_thread=1");return;
    }
    if(!ui406_reset_active)ui406_stop("reset fixture missing pre-input snapshot");
    unsigned int values[163];ui406_reset_native_read(values);
    if(!ui406_same(values,ui406_reset_native,sizeof values))ui406_stop("reset changed native690 or original arrays");
    static AfCatalog expected;expected=ui406_reset_catalog;
    if(command=='F')expected.slots[6].working=expected.slots[6].initial;
    if(!ui406_same(&expected,ui406_catalog,sizeof expected))ui406_stop("reset or cancel changed wrong private state");
    unsigned int expected_base=command=='F'?0x84c:ui406_reset_ui_base;
    if(*label()!=expected_base)ui406_stop("reset native1700 base UI differs");
    char text[220];snprintf(text,sizeof text,"action=%c expected=%s original_arrays_unchanged=1 native690=%u private_catalog_exact=1 base_ui_property=%#x tid=%u expectation_not_focus_observation=1 save=disabled",
        command,command=='F'?"confirm":"cancel",values[0],*label(),ui_thread_id);
    record("A7R5_UI406_RESET_FIXTURE ",text);ui406_reset_active=0;
}
/* 固定字段只读摘要；仅由原UI拥有者的STORE_SNAPSHOT调用，不提供任意地址读取。 */
static void ui406_keyboard_snapshot(const char *reason) {
    static const struct {unsigned int getter,bytes,preimage;} fields[14]={
        {0x28cb488,256,0x9002b1a0},{0x28cb4b0,256,0x9002b1a0},
        {0x28cb4d8,4,0x9002b1a0},{0x28cb500,4,0x9002b1a0},
        {0x28cb528,4,0x9002b1a0},{0x28cb550,4,0x9002b1a0},
        {0x28cb578,4,0x9002b1a0},{0x28cb5a0,16,0x9002b1a0},
        {0x28cc1a8,4,0xf002b180},{0x28cbaa0,47,0x9002b1a0},
        {0x28cbac8,47,0x9002b1a0},{0x28c4cac,4,0xf002b1c0},
        {0x28a8adc,47,0xf002b2a0},{0x28a8b04,47,0xf002b2a0}
    };
    unsigned char keyboard[548],temporary[98],saved[98],digest[3][32];
    unsigned char *const output[3]={keyboard,temporary,saved};
    const unsigned int capacity[3]={sizeof keyboard,sizeof temporary,sizeof saved};
    unsigned int used[3]={0};
    if(!ui406_base)ui406_stop("keyboard observer missing locked AP");
    for(unsigned int i=0;i<14;i++) {
        unsigned int group=i<8?0:i<11?1:2;
        unsigned long at=ui406_base+fields[i].getter;
        if(*(const unsigned int *)at!=fields[i].preimage || fields[i].bytes>capacity[group]-used[group])
            ui406_stop("keyboard observer source or fixed size differs");
        const unsigned char *(*get)(void)=(void *)at;const unsigned char *value=get();
        if(!value)ui406_stop("keyboard observer fixed getter returned null");
        for(unsigned int j=0;j<fields[i].bytes;j++)output[group][used[group]++]=value[j];
    }
    const char *const tag[3]={"A7R5_UI406_KEYBOARD_MODEL_STATE ",
        "A7R5_UI406_NATIVE_NAME_TEMP_STATE ","A7R5_UI406_NATIVE_NAME_SAVED_STATE "};
    for(unsigned int group=0;group<3;group++) {
        if(used[group]!=capacity[group] || af_sha256(output[group],used[group],digest[group]))
            ui406_stop("keyboard observer fixed digest failed");
        char hex[65],text[260];for(unsigned int i=0;i<32;i++)snprintf(hex+i*2,3,"%02x",digest[group][i]);
        snprintf(text,sizeof text,"reason=%s bytes=%u sha256=%s tid=%u source_query_only=1",reason,used[group],hex,ui_thread_id);
        record(tag[group],text);
    }
}

static void ui406_manage_snapshot(const char *reason) {
    char text[640];unsigned int native[163];unsigned char sha[32],catalog_sha[32];
    ui406_reset_native_read(native);if(af_sha256(native,sizeof native,sha))ui406_stop("management native read hash failed");
    char hex[65];for(unsigned int i=0;i<32;i++)snprintf(hex+i*2,3,"%02x",sha[i]);
    if(af_sha256(ui406_catalog,sizeof(*ui406_catalog),catalog_sha))ui406_stop("catalog observation hash failed");
    char catalog_hex[65];for(unsigned int i=0;i<32;i++)snprintf(catalog_hex+i*2,3,"%02x",catalog_sha[i]);
    snprintf(text,sizeof text,"reason=%s native690=%u original163_sha256=%s phase=%u ticket=%lu result=%d generation=%lu durable=%u tid=%u CP=disabled catalog_sha256=%s op=%u source=%u target=%u overwrite=%u",
        reason,native[0],hex,ui406_manager->phase,ui406_manager->job.ticket,ui406_manager->receipt.result,
        ui406_manager->receipt.generation,ui406_manager->receipt.durable,ui_thread_id,catalog_hex,
        ui406_manager->job.request.op,ui406_manager->job.request.source_slot,ui406_manager->job.request.target_slot,ui406_manager->job.request.overwrite);
    record("A7R5_UI406_STORE_STATE ",text);
    /* 不增加旧ABI的字符串导入；短路比较同时保护较短的phase标签。 */
    if(reason[0]=='S' && reason[1]=='N' && reason[2]=='A' && reason[3]=='P' &&
       reason[4]=='S' && reason[5]=='H' && reason[6]=='O' && reason[7]=='T' && !reason[8])
        ui406_keyboard_snapshot(reason);
    if(!ui406_manage_result || !ui406_manage_focus)ui406_stop("management observer symbols absent");
    snprintf(text,sizeof text,"result=%d focus=%u source_query_only=1",ui406_manage_result(),ui406_manage_focus());
    record("A7R5_UI406_MANAGE_CALLBACK_STATE ",text);
    const unsigned int *(*root_get)(void)=(void *)(ui406_base+0x28a8720);
    snprintf(text,sizeof text,"stage=%u result=%d physical=%#x group3b2=%#x menu3b7=%#x screen3bc=%#x source_query_only=1",
        ui406_nested_state(),ui406_nested_result(),ui406_nested_screen(),*root_get(),
        *(((const unsigned int *(*)(void))(ui406_base+0x28a87e8))()),
        *(((const unsigned int *(*)(void))(ui406_base+0x28a88ac))()));
    record("A7R5_UI406_NESTED_STATE ",text);
    snprintf(text,sizeof text,"stage=%u binding_version=%u choice_version=%u choice_bytes=%lu",ui406_targets_stage(),AF_AP_TARGETS_VERSION,AF_AP_TARGET_CHOICE_VERSION,sizeof(AfApTargetChoice));
    record("A7R5_UI406_TARGETS_STATE ",text);
    AfApMediaInfo media_info={0};int media_snapshot=ui406_media_snapshot_query(&media_info);
    char media_sha[65]={0};const char *media_name=ui406_media_name_query();
    if(!media_snapshot)for(unsigned int i=0;i<32;i++)snprintf(media_sha+i*2,3,"%02x",media_info.source.sha256[i]);
    snprintf(text,sizeof text,"phase=%u result=%d snapshot=%d generation=%lu index=%u bytes=%u sha256=%s name=%s conversion_unavailable=1 source_query_only=1",
        ui406_media_phase_query(),ui406_media_result_query(),media_snapshot,media_info.generation,
        media_info.index,media_info.source.bytes,media_sha,media_name?media_name:"");
    record("A7R5_UI406_MEDIA_STATE ",text);
    unsigned long utility=*(unsigned long *)(ui406_base+0x591f9a8)+0x10;
    unsigned int ids[16]={0};
    unsigned int (*items)(void *,unsigned int,unsigned int *,unsigned int)=(void *)(ui406_base+0x1bcf3fc);
    unsigned int number=items(&utility,0x7f,ids,16);
    unsigned long cache=*(unsigned long *)(ui406_base+0x5947a28);
    const unsigned char *flags=(void *)(cache+AF_MANAGE_MENU_ROOT*24);
    snprintf(text,sizeof text,"group=0x7f count=%u ids=%#x,%#x,%#x,%#x,%#x,%#x,%#x,%#x descriptor_count=%u descriptor_rows=%#lx management_cache=%u,%u,%u,%u,%u source_query_only=1",
        number,ids[0],ids[1],ids[2],ids[3],ids[4],ids[5],ids[6],ids[7],
        *(unsigned int *)(ui406_base+0x5895280+0x54),*(unsigned long *)(ui406_base+0x5895280+0x58),
        flags[0],flags[1],flags[2],flags[3],flags[4]);
    record("A7R5_UI406_MAIN_MENU_QUERY ",text);
    const unsigned int *(*product_get)(void)=(void *)(ui406_base+0x28a06cc);
    unsigned int (*family)(void)=(void *)(ui406_base+0x17ffd0c);
    unsigned int (*column)(void)=(void *)(ui406_base+0x1bd7314);
    unsigned int (*alias)(unsigned int)=(void *)(ui406_base+0x1bd8eb8);
    unsigned int (*main_visible)(void *,unsigned int)=(void *)(ui406_base+0x1bd0090);
    snprintf(text,sizeof text,"product_model=%u product_cache=%u family=%u product_column=%u alias7e=%#x alias7f=%#x alias1e0=%#x alias1e6=%#x alias_root=%#x main_root=%u source_query_only=1",
        *product_get(),*(unsigned int *)(ui406_base+0x598e7a8),family(),column(),
        alias(0x7e),alias(0x7f),alias(0x1e0),alias(0x1e6),alias(AF_MANAGE_MENU_ROOT),main_visible(&utility,AF_MANAGE_MENU_ROOT));
    record("A7R5_UI406_PRODUCT_MENU_QUERY ",text);
    const unsigned int *(*page_get)(void)=(void *)(ui406_base+0x28a88ac);
    const unsigned int *(*menu_get)(void)=(void *)(ui406_base+0x28a87e8);
    snprintf(text,sizeof text,"current_menu=%#x logical_page=%#x main7e=%u main7f=%u main1e0=%u main1e6=%u source_query_only=1",
        *menu_get(),*page_get(),main_visible(&utility,0x7e),main_visible(&utility,0x7f),
        main_visible(&utility,0x1e0),main_visible(&utility,0x1e6));
    record("A7R5_UI406_LOGICAL_MENU_QUERY ",text);
    for(unsigned int i=0;i<AF_USERS;i++)if(ui406_catalog->slots[i].present) {
        const AfSlot *s=&ui406_catalog->slots[i];
        snprintf(text,sizeof text,"slot=%u revision=%lu initial_base=%u saved_base=%u working_base=%u saved=%d,%d,%d,%d,%d,%d,%d,%d working=%d,%d,%d,%d,%d,%d,%d,%d dirty=%d pending=%lu",
            i+1,s->saved_revision,s->initial.base,s->saved.base,s->working.base,
            s->saved.params[0],s->saved.params[1],s->saved.params[2],s->saved.params[3],
            s->saved.params[4],s->saved.params[5],s->saved.params[6],s->saved.params[7],
            s->working.params[0],s->working.params[1],s->working.params[2],s->working.params[3],
            s->working.params[4],s->working.params[5],s->working.params[6],s->working.params[7],
            ui406_dirty(ui406_catalog,i+1),s->pending.request);
        record("A7R5_UI406_STORE_SLOT ",text);
    }
}
static void ui406_manage_observe(void) {
    static unsigned long ticket=~0UL;static unsigned int phase=~0U;
    if(!ui406_repository_context)return;
    const char *commands[2]={"COPY20","SNAPSHOT"};
    const char *paths[2]={"/tmp/a7r5-ui406-manage-COPY20","/tmp/a7r5-ui406-manage-SNAPSHOT"};
    for(unsigned int i=0;i<2;i++) {
        int fd=open(paths[i],0);if(fd<0)continue;
        if(close(fd) || unlink(paths[i]))ui406_stop("management fixture request close failed");
        int result=0;
        if(!i) {
            AfApManageRequest request={0};request.op=AF_MANAGE_COPY;request.source_slot=7;
            request.target_slot=20;request.name_bytes=3;request.name[0]='C';request.name[1]='2';request.name[2]='0';
            result=ui406_manage_configure(&request);
        }
        char text[200];snprintf(text,sizeof text,"action=%s result=%d configuration_only=%u source=7 target=20 tid=%u",
            commands[i],result,!i,ui_thread_id);record("A7R5_UI406_MANAGE_FIXTURE ",text);
        ui406_manage_snapshot(commands[i]);
    }
    if(ticket!=ui406_manager->job.ticket || phase!=ui406_manager->phase) {
        ticket=ui406_manager->job.ticket;phase=ui406_manager->phase;ui406_manage_snapshot("phase");
    }
}
static void ui406_observe(void) {
    static unsigned int previous=0xffffffff;
    static AfPreset old_preset;
    static unsigned int old_valid;
    if(!ui406_installed || ui_thread_id!=(unsigned int)syscall(178))return;
    ui406_name_fixture_poll();
    ui406_reset_fixture_poll();
    ui406_manage_observe();
    const unsigned int *(*current)(void)=(void *)(ui406_base+0x28a87e8);
    unsigned int menu=*current();
    if(menu!=previous) {
        previous=menu;char text[160];
        snprintf(text,sizeof text,"menu=%#x rows=%u tid=%u selection_is_not_CP_ack=1",menu,
                 *(unsigned int *)(ui406_base+0x5858b08+0x54),ui_thread_id);
        record("A7R5_UI406_SELECTION ",text);
        if((menu>=0x84c && menu<=0x85e) || (menu>=0x15d9 && menu<=0x15e6)) {
            unsigned long table=*(unsigned long *)(ui406_base+0x591f9a8)+0x10;
            unsigned int (*parent)(void *,unsigned int)=(void *)(ui406_base+0x1bdb0b0);
            unsigned int (*index)(unsigned int)=(void *)(ui406_base+0x1bd5e40);
            snprintf(text,sizeof text,"menu=%#x parent=%#x index=%d",menu,parent(&table,menu),(int)index(menu));
            record("A7R5_UI406_PARENT ",text);
            if(captured_manager) for(unsigned int i=0;i<15;i++) {
                unsigned long view=*(unsigned long *)(captured_manager+0x338+i*8);
                if(!view || *(unsigned long *)view!=ui406_base+0x58ca670)continue;
                unsigned long records=*(unsigned long *)(view+0x48);
                if(!records || *(unsigned int *)(records+0x90)!=0x1c)continue;
                unsigned long data=*(unsigned long *)(records+0x98);
                if(!data)continue;
                unsigned int count=*(unsigned int *)(data+0xd30),selected=*(unsigned int *)(data+0xd38);
                snprintf(text,sizeof text,"count=%u selected=%u primary=%#x alternate=%#x text=%#x",count,selected,
                    selected<32?*(unsigned int *)(data+0x30+selected*4):0,
                    selected<32?*(unsigned int *)(data+0x430+selected*4):0,
                    selected<32?*(unsigned int *)(data+0x830+selected*4):0);
                record("A7R5_UI406_LIST_MODEL ",text);
            }
        }
    }
    if(ui406_fixture_seeded && menu==0x15d9) {
        AfPreset preset;
        if(ui406_read(ui406_catalog,7,0,&preset))ui406_stop("fixture cannot read C07");
        if(!ui406_same(&ui406_catalog->slots[6].initial,&ui406_fixture_initial,sizeof(AfPreset)) ||
           !ui406_same(&ui406_catalog->slots[6].saved,&ui406_fixture_saved,sizeof(AfPreset)))
            ui406_stop("working edit changed fixture initial or saved");
        for(unsigned int i=0;i<20;i++)if(i!=6 && ui406_catalog->slots[i].present)
            ui406_stop("working edit changed another private slot");
        if(!old_valid || !ui406_same(&preset,&old_preset,sizeof preset)) {
            old_preset=preset;old_valid=1;char text[320];
            const unsigned int *(*selector)(void)=(void *)(ui406_base+0x28ae4b0);
            const unsigned int *(*label)(void)=(void *)(ui406_base+0x28c5684);
            unsigned int option=~0U;
            if(captured_manager)for(unsigned int i=0;i<15;i++) {
                void *view=*(void **)(captured_manager+0x338+i*8);
                if(view && *(unsigned long *)view==ui406_base+0x58ca720) {
                    unsigned int (*selected)(void *)=(void *)(ui406_base+0x220b4e0);
                    option=selected(view);
                    unsigned long records=*(unsigned long *)((char *)view+0x90);
                    if(records && *(unsigned int *)(records+0xf0)==0x11) {
                        const unsigned int *data=*(const unsigned int **)(records+0xf8);
                        if(data) {
                            char diagnostic[200];
                            unsigned int image=~0U;
                            if(*(unsigned int *)(records+0x280)==0) {
                                const unsigned int *image_data=*(const unsigned int **)(records+0x288);
                                if(image_data)image=image_data[15];
                            }
                            snprintf(diagnostic,sizeof diagnostic,"slot=7 base=%u focus30=%#x focus34=%#x image_resource=%#x",preset.base,data[12],data[13],image);
                            record("A7R5_UI406_BASE_VIEW ",diagnostic);
                        }
                    }
                    break;
                }
            }
            snprintf(text,sizeof text,"slot=7 base=%u params=%d,%d,%d,%d,%d,%d,%d,%d dirty=%d native_selector=%u base_ui_property=%#x parameter_option=%u initial_saved_unchanged=1 other_private_slots_empty=1 memory_only=1 CP=disabled save=disabled",
                preset.base,preset.params[0],preset.params[1],preset.params[2],preset.params[3],
                preset.params[4],preset.params[5],preset.params[6],preset.params[7],ui406_dirty(ui406_catalog,7),*selector(),*label(),option);
            record("A7R5_UI406_WORKING ",text);
        }
    }
}
