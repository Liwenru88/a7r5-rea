/* 独立客体启动模型夹具：原UI线程、原语言setter/资源银行，不改语言权限或Backup。 */
#include "locale28-backup.h"
static unsigned long locale28_base;
static unsigned int locale28_applied,locale28_observed,locale28_backup_rejections,locale28_last_rejections;
static void *locale28_island;
static long (*locale28_original_backup)(unsigned long,unsigned long,const void *);
static void locale28_stop(const char *message) { record("A7R5_LOCALE28_CONFLICT ",message);__builtin_trap(); }
static long locale28_backup_boundary(unsigned long group,unsigned long key,const void *data) {
    if(key==0x02cf03feUL) {
        if(group!=0x2cfUL || !data)locale28_stop("language Backup request signature differs");
        unsigned int count=__atomic_add_fetch(&locale28_backup_rejections,1,__ATOMIC_RELAXED);
        char text[180];snprintf(text,sizeof text,"group=%#lx key=%#lx count=%u result=-1 backend_delegated=0 no_persistence_ack=1",group,key,count);
        record("A7R5_LOCALE28_BACKUP_REJECT ",text);return -1;
    }
    return locale28_original_backup(group,key,data);
}
static void locale28_install(void *symbol) {
    Dl_info info;if(locale28_base || !ui406_installed || !real_dladdr(symbol,&info) ||
       (unsigned long)symbol-(unsigned long)info.dli_fbase!=0x17feac0 ||
       ui406_base!=(unsigned long)info.dli_fbase || ui_thread_id || create_screen_returned)
        locale28_stop("locale fixture must be prepared before original UI");
    unsigned long base=(unsigned long)info.dli_fbase;
    if(*(unsigned int *)(base+0x16db040)!=0xb0021590 ||
       *(unsigned int *)(base+0x1c7a31c)!=0xa9b97bfd ||
       *(unsigned int *)(base+0x1bd72e4)!=0xa9be7bfd ||
       *(unsigned int *)(base+0x28b0464)!=0xf002b260 ||
       *(unsigned int *)(base+0x3f3cb80+4)!=0xb9b ||
       *(unsigned int *)(base+0x3f3cb80+0x34)!=25 ||
       *(unsigned int *)(base+0x3f3cb80+0x38)!=0x75b ||
       *(unsigned int *)(base+0x5837b80+0x54)!=34 ||
       *(unsigned long *)(base+0x5837b80+0x58)!=base+0x3f3bf00 ||
       *(unsigned long *)(base+0x5837b80+0x80)!=base+0x1c7a31c)
        locale28_stop("fixed language descriptor or native setter preimage differs");
    if(!ui406_file("/usr/lib/libbackup.so",LOCALE28_BACKUP_BYTES,locale28_backup_sha))locale28_stop("same-package Backup library differs");
    static const unsigned char icon_sha[32]={0x66,0xb5,0x40,0xe1,0xbb,0x37,0x2f,0xc6,0x62,0x48,0xe7,0x3e,0xb6,0x4d,0x21,0x27,0x9b,0x2b,0xf8,0x5c,0xdd,0x09,0x03,0xea,0x5b,0xa1,0x19,0x56,0xfc,0x22,0x27,0xb9};
    if(!ui406_file("/tmp/images/Sony_DI_Icons.ttf",621792,icon_sha))locale28_stop("same-package linked Icons font missing or differs");
    record("A7R5_LOCALE28_FONT_DEPENDENCY ","original_GB18030_Big5_Icons_complete_file_SHA_ok=1 copied_after_tmpfs=1");
    locale28_original_backup=real_dlsym(0,"Backup_write");Dl_info backup;
    if(!locale28_original_backup || !real_dladdr((void *)locale28_original_backup,&backup) ||
       !backup.dli_sname || !same_name(backup.dli_sname,"Backup_write"))locale28_stop("original Backup API unresolved");
    unsigned int jump;
    if(!ui406_branch(base+0x16db040,(unsigned long)locale28_backup_boundary,0,&jump)) {
        unsigned long source=base+0x16db040;
        locale28_island=ui406_gap(source-(1UL<<27),source+(1UL<<27)-4096);
        if(!locale28_island)locale28_stop("cannot allocate owned fixture island");
        unsigned int *code=locale28_island;code[0]=0x58000050;code[1]=0xd61f0200;
        *(unsigned long *)(code+2)=(unsigned long)locale28_backup_boundary;clear_cache_range(code,16);
        if(mprotect(code,4096,5) || !ui406_branch(source,(unsigned long)code,0,&jump))locale28_stop("fixture island RX or branch failed");
    }
    locale28_base=base;
    if(!ui406_code(base+0x16db040,0xb0021590,jump,5))locale28_stop("Backup boundary install rejected");
    record("A7R5_LOCALE28_INSTALLED ","product_hooks=41 fixture_hooks=1 first_CreateScreen_model_fixture=1 language_permission_unchanged=1 language_Backup_write_returns_failure=1");
}
static void locale28_apply_model(void) {
    if(!locale28_base || locale28_applied)return;
    if(!ui_thread_id || (unsigned int)syscall(178)!=ui_thread_id || create_screen_returned)
        locale28_stop("locale fixture must run on first original CreateScreen UI thread");
    locale28_applied=1;
    const unsigned int *(*get)(void)=(void *)(locale28_base+0x28b0464);
    void (*banks)(unsigned int)=(void *)(locale28_base+0x1bd72e4);
    void (*setter)(unsigned int)=(void *)(locale28_base+0x1c7a31c);
    unsigned int before=*get();
    /* 顺序复用原语言菜单动作1c9d0e4；model来自已执行的原选择器，不取名字排列。 */
    banks(0xb9b);setter(*(unsigned int *)(locale28_base+0x3f3cb80+0x34));
    unsigned int value=*get();if(value!=25)locale28_stop("native language setter readback differs");
    char text[220];snprintf(text,sizeof text,"before=%u model=%u menu=0xb9b property=0x75b UI_tid=%u bank_switch=original setter=original backup_source_modified=0 permissions_changed=0",
        before,value,ui_thread_id);record("A7R5_LOCALE28_MODEL ",text);
}
static void locale28_observe(void) {
    if(!locale28_base || !locale28_applied || !ui_thread_id || !create_screen_returned ||
       (unsigned int)syscall(178)!=ui_thread_id)return;
    const unsigned int *(*get)(void)=(void *)(locale28_base+0x28b0464);
    if(*get()!=25)locale28_stop("original model lost locale fixture");
    unsigned int count=__atomic_load_n(&locale28_backup_rejections,__ATOMIC_RELAXED);
    if(!locale28_observed || count!=locale28_last_rejections) {
        locale28_observed=1;locale28_last_rejections=count;char text[150];
        snprintf(text,sizeof text,"model=25 property=0x75b language_Backup_requests_rejected=%u language_Backup_backend_calls=0 UI_tid=%u",count,ui_thread_id);
        record("A7R5_LOCALE28_OBSERVED ",text);
    }
}
