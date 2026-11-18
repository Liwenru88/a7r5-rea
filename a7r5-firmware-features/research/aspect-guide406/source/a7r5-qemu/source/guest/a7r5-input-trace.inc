/* 透明观测输入注册与订阅；不创建事件、不增删原厂订阅。 */
static int (*a7r5_input_original_callback)(void *,int *,void (*)(int,void *));
static void (*a7r5_input_original_event)(int,void *);
static void a7r5_input_event(int id,void *event) {
    if (event) {
        const unsigned int *w=event;
        char text[260];
        snprintf(text,sizeof text,"id=%d words=%#x,%#x,%#x,%#x,%#x,%#x,%#x,%#x tid=%ld",
            id,w[0],w[1],w[2],w[3],w[4],w[5],w[6],w[7],syscall(178));
        record("KEY_TRACE_APP_CALLBACK ",text);
    }
    a7r5_input_original_event(id,event);
}
int a7r5_input_set_callback(void *,int *,void (*)(int,void *))
    __asm__("_ZN10InfraInput11SetCallbackEPiPFviP16_InfraInputEventE");
int a7r5_input_set_callback(void *self,int *id,void (*callback)(int,void *)) {
    if (!real_dlsym) initialize();
    if (!a7r5_input_original_callback)
        a7r5_input_original_callback=real_dlsym((void *)-1,"_ZN10InfraInput11SetCallbackEPiPFviP16_InfraInputEventE");
    if (!a7r5_input_original_callback) __builtin_trap();
    void (*forward)(int,void *)=callback;
    if (getenv("A7R5_INPUT_TRACE") && appfw_base &&
        (unsigned long)callback==appfw_base+0x1800da4) {
        a7r5_input_original_event=callback;
        forward=a7r5_input_event;
    }
    int result=a7r5_input_original_callback(self,id,forward);
    if (getenv("A7R5_INPUT_TRACE")) {
        char text[220]; Dl_info info;
        unsigned long offset=0;
        const char *module="?";
        if (callback && real_dladdr && real_dladdr((void *)callback,&info) && info.dli_fbase) {
            offset=(unsigned long)callback-(unsigned long)info.dli_fbase;
            module=info.dli_fname;
        }
        snprintf(text,sizeof text,"self=%p id=%d callback=%s+%#lx result=%d",self,id?*id:-1,module,offset,result);
        record("KEY_TRACE_CALLBACK_REGISTER ",text);
    }
    return result;
}
static int (*a7r5_input_original_keylist)(void *,int,const void *,int);
int a7r5_input_set_keylist(void *,int,const void *,int)
    __asm__("_ZN10InfraInput15SetEventKeyListEiP18_InfraInputKeyListi");
int a7r5_input_set_keylist(void *self,int id,const void *list,int count) {
    if (!real_dlsym) initialize();
    if (!a7r5_input_original_keylist)
        a7r5_input_original_keylist=real_dlsym((void *)-1,"_ZN10InfraInput15SetEventKeyListEiP18_InfraInputKeyListi");
    if (!a7r5_input_original_keylist) __builtin_trap();
    int result=a7r5_input_original_keylist(self,id,list,count);
    if (getenv("A7R5_INPUT_TRACE")) {
        char text[240];
        snprintf(text,sizeof text,"id=%d count=%d result=%d",id,count,result);
        record("KEY_TRACE_SUBSCRIBE ",text);
        if (list && count>0 && count<=2048) {
            const unsigned int *items=list;
            for (int i=0;i<count;++i) {
                unsigned int code=items[i*3];
                if (code==0x7095 || code==0x1f7 || code==0x1f9 || code==0x1ab) {
                    snprintf(text,sizeof text,"id=%d key=%#x field1=%#x field2=%#x result=%d",
                        id,code,items[i*3+1],items[i*3+2],result);
                    record("KEY_TRACE_SUBSCRIBE_KEY ",text);
                }
            }
        }
    }
    return result;
}
static unsigned int (*a7r5_input_original_play)(void *,const void *);
typedef unsigned int (*a7r5_input_group_t)(void *,const void *,unsigned int);
static a7r5_input_group_t a7r5_input_original_group[7];
static unsigned int a7r5_input_group(unsigned int index,void *self,const void *event,unsigned int code) {
    char text[220];
    snprintf(text,sizeof text,"category=%u self=%p screen=%#x event=%#x tid=%ld",index,self,
        *(const unsigned int *)((const char *)self+0x18),code,syscall(178));
    record("KEY_TRACE_GROUP ",text);
    return a7r5_input_original_group[index](self,event,code);
}
#define A7R5_INPUT_GROUP(N) static unsigned int a7r5_input_group_##N(void *self,const void *event,unsigned int code) { return a7r5_input_group(N,self,event,code); }
A7R5_INPUT_GROUP(0)
A7R5_INPUT_GROUP(1)
A7R5_INPUT_GROUP(2)
A7R5_INPUT_GROUP(3)
A7R5_INPUT_GROUP(4)
A7R5_INPUT_GROUP(5)
A7R5_INPUT_GROUP(6)
#undef A7R5_INPUT_GROUP
static unsigned int (*a7r5_input_original_fn)(void *,const void *);
static unsigned int a7r5_input_fn(void *self,const void *event) {
    char text[200];
    unsigned long properties=appfw_base+0x7effa98;
    snprintf(text,sizeof text,"self=%p screen=%#x guards=%u,%u tid=%ld",self,
        *(const unsigned int *)((const char *)self+0x18),*(const unsigned int *)(properties+0xd798),
        *(const unsigned int *)(properties+0xd9c0),syscall(178));
    record("KEY_TRACE_FN_HANDLER ",text);
    unsigned int result=a7r5_input_original_fn(self,event);
    snprintf(text,sizeof text,"result=%u",result);record("KEY_TRACE_FN_RETURN ",text);
    return result;
}
static void (*a7r5_input_original_normalize)(void *,void **,void *);
static void (*a7r5_input_original_filter_a)(void *,unsigned int *);
static void (*a7r5_input_original_filter_b)(void *,unsigned int *);
static void a7r5_input_filter_a(void *self,unsigned int *event) {
    unsigned int before=event[2];
    if (before==0x2020000 || before==0x2020003) {
        const unsigned long offsets[13]={0x154a0,0x155c8,0x15480,0xa0b00,0xc5b0,0x349d0,0x183b8,0x183d8,0x14b18,0x1a180,0xa7100,0x8ce08,0xa74f8};
        unsigned long properties=appfw_base+0x7effa98;
        char text[500];unsigned int used=0;
        for(unsigned int i=0;i<13;++i)
            used+=snprintf(text+used,sizeof text-used,"%#lx:%u%s",offsets[i],
                *(const unsigned int *)(properties+offsets[i]),i==12?"":",");
        record("KEY_TRACE_FILTER_STATE ",text);
    }
    a7r5_input_original_filter_a(self,event);
    if (before>=0x2020000 && before<=0x2020004) {
        char text[220];unsigned long properties=appfw_base+0x7effa98;
        snprintf(text,sizeof text,"before=%#x after=%#x type=%u gates=%u,%u",before,event[2],event[0],
            *(const unsigned int *)(properties+0x154a0),*(const unsigned int *)(properties+0x155c8));
        record("KEY_TRACE_FILTER_A ",text);
    }
}
static void a7r5_input_filter_b(void *self,unsigned int *event) {
    unsigned int before=event[2];
    a7r5_input_original_filter_b(self,event);
    if (before>=0x2020000 && before<=0x2020004) {
        char text[180];
        snprintf(text,sizeof text,"before=%#x after=%#x type=%u",before,event[2],event[0]);
        record("KEY_TRACE_FILTER_B ",text);
    }
}
static unsigned int (*a7r5_input_original_process)(void *,const unsigned int *,unsigned int,unsigned int);
static unsigned int a7r5_input_process(void *self,const unsigned int *input,unsigned int first,unsigned int second) {
    char text[260];
    if(getenv("A7R5_INPUT_TRACE")) {
    snprintf(text,sizeof text,"key=%#x status=%#x previous=%#x flags=%u,%u fn_down=%u menu_down=%u screen=%#x",
        input[0],input[2],input[3],first,second,
        *((const unsigned char *)self+0x164),*((const unsigned char *)self+0x165),
        *(const unsigned int *)((const char *)self+0x3b8));
    record("KEY_TRACE_PROCESS ",text);
    }
    unsigned int result=a7r5_input_original_process(self,input,first,second);
    if(getenv("A7R5_INPUT_COMPLETIONS")) {
        /* 原处理函数返回后记录当前帧序号；宿主必须等到它之后的新帧。 */
        unsigned char header[16];unsigned long sequence=0;
        int fd=open(HOSD_PATH,0);
        if(fd>=0) {
            long n=read(fd,header,sizeof header);int closed=close(fd);
            if(n==sizeof header && !closed && !__builtin_memcmp(header,"HOSDAP02",8))
                for(int i=7;i>=0;--i)sequence=(sequence<<8)|header[8+i];
        }
        snprintf(text,sizeof text,"key=%#x status=%#x frame_sequence=%lu result=%u",input[0],input[2],sequence,result);
        record("A7R5_INPUT_COMPLETED ",text);
    }
    return result;
}
static void (*a7r5_input_original_translate)(void *,void *,void *,void *,const unsigned int *);
static void a7r5_input_translate(void *self,void *a,void *b,void *c,const unsigned int *input) {
    unsigned int key=input[0],state=input[2];
    a7r5_input_original_translate(self,a,b,c,input);
    char text[220];
    snprintf(text,sizeof text,"key=%#x status=%#x events=%#x,%#x,%#x",key,state,
        *(const unsigned int *)a,*(const unsigned int *)b,*(const unsigned int *)c);
    record("KEY_TRACE_TRANSLATED ",text);
}
static void a7r5_input_normalize(void *self,void **message,void *event) {
    a7r5_input_original_normalize(self,message,event);
    const unsigned int *w=event;
    if (w && !w[0]) {
        char text[260];
        snprintf(text,sizeof text,"words=%#x,%#x,%#x,%#x,%#x,%#x,%#x,%#x,%#x,%#x tid=%ld",
            w[0],w[1],w[2],w[3],w[4],w[5],w[6],w[7],w[8],w[9],syscall(178));
        record("KEY_TRACE_NORMALIZED ",text);
    }
}
static unsigned int a7r5_input_play(void *self,const void *event) {
    char text[300];
    unsigned long properties=appfw_base+0x7effa98;
    snprintf(text,sizeof text,"self=%p screen=%#x guards=%u,%u,%u,%u,%u tid=%ld",
        self,*(const unsigned int *)((const char *)self+0x18),
        *(const unsigned int *)(properties+0xd798),*(const unsigned int *)(properties+0xd9c0),
        *(const unsigned char *)(properties+0x1a5a8),*(const unsigned int *)(properties+0xbea8),
        *(const unsigned int *)(properties+0xbec8),syscall(178));
    record("KEY_TRACE_PLAY_HANDLER ",text);
    unsigned int result=a7r5_input_original_play(self,event);
    snprintf(text,sizeof text,"result=%u",result);record("KEY_TRACE_PLAY_RETURN ",text);
    return result;
}
static void *a7r5_input_trace_entry(unsigned long address,const unsigned int expected[4],void *wrapper) {
    unsigned int *entry=(unsigned int *)address;
    for (unsigned int i=0;i<4;++i)if(entry[i]!=expected[i])__builtin_trap();
    unsigned int *stub=mmap(0,4096,3,0x22,-1,0);
    if(stub==(void *)-1)__builtin_trap();
    for(unsigned int i=0;i<4;++i)stub[i]=entry[i];
    stub[4]=0x58000050;stub[5]=0xd61f0200;
    *(unsigned long *)(stub+6)=(unsigned long)entry+16;
    clear_cache_range(stub,32);
    if(mprotect(stub,4096,5))__builtin_trap();
    void *page=(void *)((unsigned long)entry&~4095UL);
    if(mprotect(page,4096,7))__builtin_trap();
    entry[0]=0x58000050;entry[1]=0xd61f0200;
    *(unsigned long *)(entry+2)=(unsigned long)wrapper;
    clear_cache_range(entry,16);
    if(mprotect(page,4096,5))__builtin_trap();
    return stub;
}
static void a7r5_input_trace_install(unsigned long base) {
    const unsigned int process[4]={0xd111c3ff,0xa9bb7bfd,0x910003fd,0xa90153f3};
    if (!getenv("A7R5_INPUT_TRACE")) {
        if(getenv("A7R5_INPUT_COMPLETIONS")) {
            a7r5_input_original_process=a7r5_input_trace_entry(base+0x1ec7704,process,a7r5_input_process);
            record("A7R5_INPUT_COMPLETION_READY ","original process forwarded; detailed trace disabled");
        }
        return;
    }
    unsigned long *slot=(unsigned long *)(base+0x5826fe8);
    if (*slot!=base+0x1b66fc8) __builtin_trap();
    if (mprotect((void *)((unsigned long)slot&~4095UL),4096,3)) __builtin_trap();
    a7r5_input_original_play=(void *)*slot;
    *slot=(unsigned long)a7r5_input_play;
    unsigned long *fn_slot=(unsigned long *)(base+0x5826fb8);
    if (*fn_slot!=base+0x1b66ee8) __builtin_trap();
    a7r5_input_original_fn=(void *)*fn_slot;
    *fn_slot=(unsigned long)a7r5_input_fn;
    const unsigned long slots[7]={0x5826ec0,0x5826ee8,0x5826f10,0x5826f38,0x5826f60,0x5826f88,0x5826fb0};
    const unsigned long methods[7]={0x1b43308,0x1b43368,0x1b433c8,0x1b43428,0x1b43488,0x1b434e8,0x1b43548};
    const a7r5_input_group_t wrappers[7]={a7r5_input_group_0,a7r5_input_group_1,a7r5_input_group_2,a7r5_input_group_3,a7r5_input_group_4,a7r5_input_group_5,a7r5_input_group_6};
    for(unsigned int i=0;i<7;++i) {
        unsigned long *entry=(unsigned long *)(base+slots[i]);
        if(*entry!=base+methods[i])__builtin_trap();
        a7r5_input_original_group[i]=(void *)*entry;
        *entry=(unsigned long)wrappers[i];
    }
    if (mprotect((void *)((unsigned long)slot&~4095UL),4096,1)) __builtin_trap();
    /* 仅复制已核对、无 PC 相对寻址的四条序言，原转换逻辑完整执行。 */
    const unsigned int expected[4]={0xa9bc7bfd,0x910003fd,0xa90363f7,0xaa0003f7};
    a7r5_input_original_normalize=a7r5_input_trace_entry(base+0x1801488,expected,a7r5_input_normalize);
    const unsigned int translate[4]={0xa9bb7bfd,0x910003fd,0xa90153f3,0xaa0103f3};
    a7r5_input_original_translate=a7r5_input_trace_entry(base+0x17fa6e8,translate,a7r5_input_translate);
    a7r5_input_original_process=a7r5_input_trace_entry(base+0x1ec7704,process,a7r5_input_process);
    const unsigned int filter_a[4]={0xa9ba7bfd,0x910003fd,0xa90153f3,0x910163b4};
    a7r5_input_original_filter_a=a7r5_input_trace_entry(base+0x1802264,filter_a,a7r5_input_filter_a);
    const unsigned int filter_b[4]={0xa9b97bfd,0x910003fd,0xa90153f3,0xaa0103f4};
    a7r5_input_original_filter_b=a7r5_input_trace_entry(base+0x17f9fe8,filter_b,a7r5_input_filter_b);
}
