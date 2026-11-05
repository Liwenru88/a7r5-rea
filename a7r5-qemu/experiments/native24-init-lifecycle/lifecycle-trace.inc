/* 只观察原厂任务生命周期与完整初始化请求，不改变生产返回或完成位。 */
static void *lifecycle_init_original,*lifecycle_shutdown_original,*lifecycle_lookup_original;
static void *lifecycle_suspend_original;
static unsigned lifecycle_capture_sequence;
static void lifecycle_capture(unsigned destination,const unsigned char *p,unsigned bytes){
    if(!n12_mailbox || destination!=0x90030001u || bytes!=2400 || !p ||
       p[0]!=5 || p[1] || p[2]!=0x63 || p[3]!=0x40 ||
       !real_get_source || real_get_source((void *)p)!=0x80020002u)return;
    /* 0x3000..0x3fff独立于请求／回复区和2476字节只读状态区。 */
    volatile unsigned char *out=n12_mailbox+0x3000;
    __atomic_store_n((unsigned *)out,0,__ATOMIC_RELEASE);
    *(volatile unsigned *)(out+4)=++lifecycle_capture_sequence;
    *(volatile unsigned *)(out+8)=bytes;*(volatile unsigned *)(out+12)=destination;
    *(volatile unsigned *)(out+16)=real_get_source((void *)p);
    for(unsigned i=0;i<bytes;i++)out[32+i]=p[i];
    __atomic_store_n((unsigned *)out,0x43494e31u,__ATOMIC_RELEASE);
    char text[128];snprintf(text,sizeof(text),"sequence=%u bytes=%u observed_only=1",lifecycle_capture_sequence,bytes);
    record("A7R5_LIFECYCLE_INIT_CAPTURE ",text);
}
static unsigned long lifecycle_init_execute(void *object){
    char text[128];snprintf(text,sizeof(text),"tid=%ld object=%p command=0x32",syscall(178),object);
    record("A7R5_LIFECYCLE_INIT_ENTER ",text);
    unsigned long result=((unsigned long(*)(void *))lifecycle_init_original)(object);
    record("A7R5_LIFECYCLE_INIT_RETURN ",text);return result;
}
static unsigned long lifecycle_shutdown_set(const unsigned *value){
    char text[160];snprintf(text,sizeof(text),"factor=%#x type=%#x next=%#x caller=%#lx",value[0],value[1],value[2],(unsigned long)__builtin_return_address(0)-n12_base);
    record("A7R5_LIFECYCLE_SHUTDOWN_SET ",text);
    return ((unsigned long(*)(const unsigned *))lifecycle_shutdown_original)(value);
}
static unsigned long lifecycle_task_lookup(void *manager,unsigned command){
    unsigned long value=((unsigned long(*)(void *,unsigned))lifecycle_lookup_original)(manager,command);
    if(command==0x4d8u){char text[128];snprintf(text,sizeof(text),"command=%#x object=%#lx",command,value);record("A7R5_LIFECYCLE_TASK_LOOKUP ",text);}
    return value;
}
static void lifecycle_suspend(void *object){
    unsigned long caller=(unsigned long)__builtin_return_address(0)-n12_base;
    if(!object && caller==0x2771884UL){
        record("A7R5_LIFECYCLE_ABSENT_STILL_TASK ","command=0x4d8 caller=0x2771884");
        return;
    }
    ((void(*)(void *))lifecycle_suspend_original)(object);
}
static void lifecycle_install(void){
    static const unsigned char init[16]={0xfd,0x7b,0xb6,0xa9,0xfd,3,0,0x91,0xf7,0x63,3,0xa9,0xb7,0xc3,1,0x91};
    static const unsigned char shutdown[16]={0xfd,0x7b,0xb9,0xa9,0xfd,3,0,0x91,0xf3,0x53,1,0xa9,0xf3,3,0,0xaa};
    static const unsigned char lookup[16]={0xfd,0x7b,0xbc,0xa9,0xfd,3,0,0x91,0xf5,0x5b,2,0xa9,0xf5,3,0,0xaa};
    lifecycle_init_original=n12_trace_trampoline(0x33f182cUL,lifecycle_init_execute,init);
    lifecycle_shutdown_original=n12_trace_trampoline(0x2b50914UL,lifecycle_shutdown_set,shutdown);
    lifecycle_lookup_original=n12_trace_trampoline(0x321f17cUL,lifecycle_task_lookup,lookup);
    if(getenv("A7R5_N12_SHUTDOWN_LIFECYCLE")){
        static const unsigned char suspend[16]={0xfd,0x7b,0xbc,0xa9,0xfd,3,0,0x91,0xf3,0x53,1,0xa9,0xf3,3,0,0xaa};
        if(*(const unsigned *)(n12_base+0x2771880UL)==0x9435d25fu)
            lifecycle_suspend_original=n12_trace_trampoline(0x34e61fcUL,lifecycle_suspend,suspend);
        record("A7R5_LIFECYCLE_SHUTDOWN_GUARD ",lifecycle_suspend_original?"enabled":"signature_mismatch");
    }
}
