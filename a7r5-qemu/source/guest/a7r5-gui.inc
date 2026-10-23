/* A7R5 的透明生命周期探针；只替换已核对的功能槽，不碰析构槽。 */
static void *a7r5_create_screen(void *a0, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7) {
    char text[200];
    ui_thread_id = (unsigned int)syscall(178);
    __atomic_add_fetch(&create_screen_active, 1, __ATOMIC_RELEASE);
    snprintf(text,sizeof text,"tid=%u this=%p id=%lu count=%lu orientation=%lu",ui_thread_id,a0,(unsigned long)a1,(unsigned long)a3,(unsigned long)a4);
    record("A7R5_CREATE_SCREEN_ENTER ",text);
    void *r=real_create_screen(a0,a1,a2,a3,a4,a5,a6,a7);
    __atomic_add_fetch(&create_screen_returned,1,__ATOMIC_RELEASE);
    __atomic_sub_fetch(&create_screen_active,1,__ATOMIC_RELEASE);
    record("A7R5_CREATE_SCREEN_RETURN ","original view completed");
    return r;
}
static void (*a7r5_original_open)(void *,const unsigned int *,const unsigned int *,const unsigned int *,unsigned int,unsigned int);
typedef void (*a7r5_apply_t)(void *,const unsigned int *,const unsigned int *,const unsigned int *,unsigned int,unsigned int,unsigned int,unsigned int,unsigned int);
static a7r5_apply_t a7r5_original_apply;
static unsigned int a7r5_apply_depth;
#include "native-privacy-notice.inc"
static void (*a7r5_original_menu_init)(void *,const unsigned int *);
static void a7r5_menu_init(void *o,const unsigned int *id) {
    char text[180];
    snprintf(text,sizeof text,"this=%p id=%#x vptr=%#lx manager=%p",o,*id,*(unsigned long *)o,*(void **)((char *)o+0x180));
    record("A7R5_MENU_INIT_ENTER ",text);
    a7r5_original_menu_init(o,id);
    record("A7R5_MENU_INIT_RETURN ","original rep_menu_controller init completed");
}
static void a7r5_apply_capture(void *o,const unsigned int *a,const unsigned int *b,const unsigned int *c,unsigned int d,unsigned int e,unsigned int f,unsigned int g,unsigned int h) {
    captured_manager=(unsigned long)o;
    char text[180];
    snprintf(text,sizeof text,"manager=%p tid=%ld from=%#x to=%#x restore=%#x flags=%u,%u,%u,%u,%u",o,syscall(178),*a,*b,*c,d,e,f,g,h);
    record("A7R5_MANAGER_APPLY ",text);
    __atomic_add_fetch(&a7r5_apply_depth,1,__ATOMIC_RELEASE);
    a7r5_original_apply(o,a,b,c,d,e,f,g,h);
    __atomic_sub_fetch(&a7r5_apply_depth,1,__ATOMIC_RELEASE);
    record("A7R5_MANAGER_APPLY_RETURN ","original apply stack unwound");
}
static unsigned long a7r5_draw_frame(void *o) {
    unsigned long r=real_draw_framebuffer(o);
    static unsigned int frames,attempted;
    unsigned int n=__atomic_add_fetch(&frames,1,__ATOMIC_RELAXED);
    if (n<=8) record("A7R5_FRAME_COMPLETED ","original drawFramebuffer returned");
    if (!attempted && getenv("A7R5_APPLY_MENU") && create_screen_returned && !create_screen_active &&
        !__atomic_load_n(&a7r5_apply_depth,__ATOMIC_ACQUIRE) &&
        (unsigned int)syscall(178)==ui_thread_id && captured_manager) {
        attempted=1;
        unsigned long m=captured_manager;
        unsigned int current=*(unsigned int *)(m+0x3b8);
        unsigned long ctl=*(unsigned long *)(m+0x398);
        char text[180];
        snprintf(text,sizeof text,"manager=%#lx current=%#x controller=%#lx tid=%u",m,current,ctl,ui_thread_id);
        record("A7R5_MENU_APPLY_GATE ",text);
        unsigned long table=*(unsigned long *)(appfw_base+0x5915668);
        const unsigned int *desc=(const unsigned int *)(table+0x354*96);
        snprintf(text,sizeof text,"table=appFw+%#lx kind=%u group=%u flags=%#x id=%#x ctor=+%#lx menuGOT=+%#lx",table-appfw_base,desc[6],desc[5],desc[7],desc[8],
                 *(unsigned long *)((char *)desc+8)-appfw_base,*(unsigned long *)(appfw_base+0x59650a0)-appfw_base);
        record("A7R5_MENU_DESCRIPTOR ",text);
        if (*(unsigned long *)m!=appfw_base+0x58d2fb8 || current!=0x315 || !ctl) {
            record("A7R5_MENU_APPLY_REFUSED ","boot manager state differs"); return r;
        }
        unsigned int from=0x4cf,to=0x354,restore=0x4cf;
        a7r5_original_apply((void *)m,&from,&to,&restore,0,1,0,0,0);
        unsigned long after=*(unsigned long *)(m+0x398);
        snprintf(text,sizeof text,"current=%#x controller=%#lx vptr=appFw+%#lx init=appFw+%#lx",*(unsigned int *)(m+0x3b8),after,
                 after?*(unsigned long *)after-appfw_base:0,after?*(unsigned long *)(*(unsigned long *)after+32)-appfw_base:0);
        record("A7R5_MENU_AFTER ",text);
        record("A7R5_MENU_APPLY_RETURN ","original framework lifecycle returned");
    }
    a7r5_privacy_notice_poll();
    return r;
}
static void a7r5_open_screen(void *o,const unsigned int *a,const unsigned int *b,const unsigned int *c,unsigned int d,unsigned int e) {
    captured_manager=(unsigned long)o;
    char text[200];
    snprintf(text,sizeof text,"manager=%p from=%#x to=%#x restore=%#x flags=%u,%u",o,a?*a:0,b?*b:0,c?*c:0,d,e);
    record("A7R5_MANAGER_OPEN ",text);
    a7r5_original_open(o,a,b,c,d,e);
}
static void a7r5_gui_install(unsigned long base) {
    a7r5_input_trace_install(base);
    unsigned long *view=(unsigned long *)(base+0x57830a8UL);
    unsigned long *manager=(unsigned long *)(base+0x58d2fd0UL);
    if (*view!=base+0x182b41cUL || *manager!=base+0x1d15b50UL) {
        record("A7R5_PATCH_FAILED ","GUI vtable fingerprint"); __builtin_trap();
    }
    real_create_screen=(void *)*view;
    a7r5_original_open=(void *)*manager;
    if (mprotect((void *)((unsigned long)view&~4095UL),4096,3) ||
        mprotect((void *)((unsigned long)manager&~4095UL),4096,3)) __builtin_trap();
    *view=(unsigned long)a7r5_create_screen;
    *manager=(unsigned long)a7r5_open_screen;
    unsigned long *menu_init=(unsigned long *)(base+0x58d30b0);
    if (*menu_init!=base+0x20cb130) __builtin_trap();
    if (mprotect((void *)((unsigned long)menu_init&~4095UL),4096,3)) __builtin_trap();
    a7r5_original_menu_init=(void *)*menu_init;
    *menu_init=(unsigned long)a7r5_menu_init;
    unsigned int *entry=(unsigned int *)(base+0x1ec6240);
    const unsigned int expected[4]={0xd10703ff,0x53001ca5,0xa9027bfd,0x910083fd};
    for (unsigned int i=0;i<4;++i) if (entry[i]!=expected[i]) __builtin_trap();
    unsigned int *stub=mmap(0,4096,3,0x22,-1,0);
    if (stub==(void *)-1) __builtin_trap();
    for (unsigned int i=0;i<4;++i) stub[i]=entry[i];
    stub[4]=0x58000050;stub[5]=0xd61f0200;
    *(unsigned long *)(stub+6)=(unsigned long)entry+16;
    clear_cache_range(stub,32);
    if(mprotect(stub,4096,5)) __builtin_trap();
    a7r5_original_apply=(void *)stub;
    void *page=(void *)((unsigned long)entry&~4095UL);
    if(mprotect(page,4096,7)) __builtin_trap();
    entry[0]=0x58000050;entry[1]=0xd61f0200;
    *(unsigned long *)(entry+2)=(unsigned long)a7r5_apply_capture;
    clear_cache_range(entry,16);
    if(mprotect(page,4096,5)) __builtin_trap();
    if (!real_draw_framebuffer) __builtin_trap();
    if (mprotect((void *)(base+0x598d000),4096,3)) __builtin_trap();
    *(unsigned long *)(base+0x598d4d0)=(unsigned long)a7r5_draw_frame;
    start_headless_osd();
    record("A7R5_GUI_PROBES ","view slot2 and manager slot3; original methods forwarded");
}
