/* 仅观察原生E4及九个分派；跳板执行完整原指令，不写生产完成状态。 */
static void *n12_e4_original;
static void *n12_dispatch_original[9];
static void *n12_enqueue_original;
static void *n12_ui_original;
static unsigned long n12_trace_ui(unsigned long controller,unsigned long message,unsigned long event){
    if(event==0x20f0000UL)return ((unsigned long(*)(unsigned long,unsigned long,unsigned long))n12_ui_original)(controller,message,event);
    char s[240];volatile unsigned *g=(void *)(n12_base+0x8eba610UL);
    snprintf(s,sizeof(s),"tid=%ld controller=%#lx event=%#lx focus=%u status=%u pending=%u command=%u",syscall(178),controller,event,g[2],g[3],g[4],((unsigned(*)(void))(n12_base+0x8e97270UL))());
    record("N12_UI_ENTER ",s);
    unsigned long value=((unsigned long(*)(unsigned long,unsigned long,unsigned long))n12_ui_original)(controller,message,event);
    snprintf(s,sizeof(s),"tid=%ld controller=%#lx event=%#lx focus=%u status=%u pending=%u command=%u",syscall(178),controller,event,g[2],g[3],g[4],((unsigned(*)(void))(n12_base+0x8e97270UL))());
    record("N12_UI_RETURN ",s);return value;
}
static unsigned long n12_trace_enqueue(void *manager,void *object,unsigned command,unsigned mode,unsigned flag) {
    char s[220];
    if(command==0xe4){
        unsigned long *vtable=*(void **)object;
        const int *map=*(void **)(n12_base+0x594a2c0UL);
        snprintf(s,sizeof(s),"tid=%ld manager=%p object=%p command=%#x mode=%u flag=%u queue_index=%d vtable=%p execute=%#lx",
            syscall(178),manager,object,command,mode,flag,map[command],vtable,vtable[2]);record("A7R5_N12_ENQUEUE_ENTER ",s);
    }
    unsigned long value=((unsigned long(*)(void *,void *,unsigned,unsigned,unsigned))n12_enqueue_original)(manager,object,command,mode,flag);
    if(command==0xe4){
        record("A7R5_N12_ENQUEUE_RETURN ",s);
        const int *map=*(void **)(n12_base+0x594a2c0UL);
        unsigned char *q=(unsigned char *)manager+0x320+0x90*map[command];
        ((void(*)(void *))(n12_base+0x17fc5d4UL))(q+0x18);
        void *active=*(void **)(q+0x78);
        unsigned active_command=active?((unsigned(*)(void *))(n12_base+0x30bed98UL))(active):0;
        unsigned long active_execute=active?(*(unsigned long **)active)[2]:0;
        snprintf(s,sizeof(s),"manager=%p queue=%p pending=%lu active=%p active_command=%#x active_execute=%#lx",
            manager,q,*(unsigned long *)(q+0x10),active,active_command,active_execute);
        /* 0x17fc630接收RAII守卫，不能传入裸mutex；此处使用pthread_mutex_unlock PLT。 */
        ((int(*)(void *))(n12_base+0x16dc620UL))(q+0x18);record("A7R5_N12_QUEUE_STATE ",s);
    }
    return value;
}
static void n12_trace_execute(void *object) {
    unsigned serial=*(volatile unsigned *)(n12_base+0x8eb9d18UL);
    unsigned long exact=*(volatile unsigned long *)(n12_base+0x8eb9d70UL);
    char s[160];snprintf(s,sizeof(s),"tid=%ld object=%p serial=%u private=%u",syscall(178),object,serial,serial&&exact==(unsigned long)object);
    record("A7R5_N12_E4_ENTER ",s);
    ((void(*)(void *))n12_e4_original)(object);
    record("A7R5_N12_E4_RETURN ",s);
}
#define N12_DISPATCH(N) \
static unsigned long n12_dispatch_##N(void *params,void *result) { \
    char s[160];snprintf(s,sizeof(s),"tid=%ld index=%u params=%p result=%p",syscall(178),N,params,result); \
    record("A7R5_N12_DISPATCH_ENTER ",s); \
    unsigned long value=((unsigned long(*)(void *,void *))n12_dispatch_original[N])(params,result); \
    record("A7R5_N12_DISPATCH_RETURN ",s);return value; \
}
N12_DISPATCH(0) N12_DISPATCH(1) N12_DISPATCH(2) N12_DISPATCH(3) N12_DISPATCH(4)
N12_DISPATCH(5) N12_DISPATCH(6) N12_DISPATCH(7) N12_DISPATCH(8)
static void *n12_trace_trampoline(unsigned long at,void *target,const unsigned char prologue[16]) {
    unsigned char *source=(void *)(n12_base+at);
    for(unsigned i=0;i<16;i++)if(source[i]!=prologue[i])__builtin_trap();
    unsigned char *code=mmap(0,4096,3,0x22,-1,0);if(code==(void *)-1)__builtin_trap();
    for(unsigned i=0;i<16;i++)code[i]=source[i];
    ((unsigned *)code)[4]=0x58000050;((unsigned *)code)[5]=0xd61f0200;
    *(unsigned long *)(code+24)=n12_base+at+16;
    clear_cache_range(code,32);if(mprotect(code,4096,5))__builtin_trap();
    n12_detour(at,target);return code;
}
static void n12_trace_install(void) {
    static const unsigned char execute[16]={0xfd,0x7b,0xba,0xa9,0xfd,3,0,0x91,0xf3,0x53,1,0xa9,0xf3,3,0,0xaa};
    static const unsigned char dispatch[16]={0xfd,0x7b,0xbe,0xa9,0xfd,3,0,0x91,0xf3,0x53,1,0xa9,0xf3,3,0,0xaa};
    static const unsigned char enqueue[16]={0xfd,0x7b,0xb7,0xa9,0xfd,3,0,0x91,0xf5,0x5b,2,0xa9,0xb6,0x43,2,0x91};
    static const unsigned char ui[16]={0xfd,0x7b,0xbc,0xa9,0xf8,0x5f,1,0xa9,0xfd,3,0,0x91,0xf6,0x57,2,0xa9};
    n12_e4_original=n12_trace_trampoline(0x348292cUL,n12_trace_execute,execute);
    void *functions[9]={n12_dispatch_0,n12_dispatch_1,n12_dispatch_2,n12_dispatch_3,n12_dispatch_4,
                       n12_dispatch_5,n12_dispatch_6,n12_dispatch_7,n12_dispatch_8};
    for(unsigned n=0;n<9;n++)n12_dispatch_original[n]=n12_trace_trampoline(0x350927cUL+64*n,functions[n],dispatch);
    n12_enqueue_original=n12_trace_trampoline(0x326d098UL,n12_trace_enqueue,enqueue);
    const unsigned char *entry=(const void *)(n12_base+0x8e996bcUL);
    if(*(const unsigned *)entry==(0x14000000u|((0x8e9fb00u-0x8e996bcu)/4))){
        for(unsigned i=4;i<16;i++)if(entry[i]!=ui[i])__builtin_trap();
        record("A7R5_N12_E4_MENU_COMPAT ","independent AP event guard present; original E4 retained");
    }else n12_ui_original=n12_trace_trampoline(0x8e996bcUL,n12_trace_ui,ui);
}
static void native12_trace_send(unsigned id,void *message) {
    if(!n12_mailbox||!message||!real_msg_size||(id!=0x90030001&&id!=0x92840747&&id!=0x90040193&&id!=0x909a015a))return;
    unsigned size=real_msg_size(message),shown=size<64?size:64;char hex[129],s[300];
    const unsigned char *p=message;const char digits[]="0123456789abcdef";
    for(unsigned i=0;i<shown;i++){hex[2*i]=digits[p[i]>>4];hex[2*i+1]=digits[p[i]&15];}hex[2*shown]=0;
    snprintf(s,sizeof(s),"tid=%ld dest=%#x source=%#x size=%u payload=%s",syscall(178),id,
             real_get_source?real_get_source(message):0,size,hex);record("A7R5_N12_NATIVE_TX ",s);
}
