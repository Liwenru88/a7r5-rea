/* 仅限固定 AP 指纹的独立 QEMU 客体，原文件和业务代码保持不变。 */
static const int aspect406_ranges[3][3] = {{0,1,1},{0,5,1},{0,15,1}};
static unsigned long aspect406_base;
static unsigned int aspect406_enabled;
static unsigned long (*aspect406_original_guide)(void *);
static unsigned int aspect406_guide_calls;

static unsigned long aspect406_guide(void *object) {
    unsigned long result=aspect406_original_guide(object);
    unsigned int count=++aspect406_guide_calls;
    const unsigned char *p=object;
    if(count<=12 || (count%100)==0) {
        char text[180];
        snprintf(text,sizeof text,"calls=%u object=%p visible=%u,%u rect=%d,%d,%d,%d type=%u",
                 count,object,p[0x204],p[0x21c],*(int *)(p+0x208),*(int *)(p+0x20c),
                 *(int *)(p+0x210),*(int *)(p+0x214),p[0x21d]);
        record("A7R5_ASPECT406_GUIDE_DRAW ",text);
    }
    return result;
}

static void aspect406_fail(const char *reason) {
    record("A7R5_ASPECT406_FAILED ",reason);
    __builtin_trap();
}
static void aspect406_write16(unsigned long base,unsigned long offset) {
    unsigned short *p=(void *)(base+offset);
    void *page=(void *)((unsigned long)p&~4095UL);
    if(mprotect(page,4096,3))aspect406_fail("support page writable failed");
    *p=1;
    if(mprotect(page,4096,1))aspect406_fail("support page protection failed");
    char text[128];
    snprintf(text,sizeof text,"VA=%#lx size=2 before=0 after=1 column=16",offset);
    record("A7R5_ASPECT406_WRITE ",text);
}
static void aspect406_install(void *symbol) {
    Dl_info info;
    if(aspect406_enabled || !real_dladdr(symbol,&info) ||
       (unsigned long)symbol-(unsigned long)info.dli_fbase!=0x17feac0UL)
        aspect406_fail("AP anchor or duplicate install");
    unsigned long b=(unsigned long)info.dli_fbase;
    const unsigned long desc[3]={0x58a4690,0x58a2570,0x58a4750};
    const unsigned long rows[3]={0x3f9b900,0x3f7a380,0x3f94c00};
    const unsigned int counts[3]={2,6,16};
    if(*(unsigned int *)(b+0x29051dc)!=0xb9400023U ||
       *(unsigned int *)(b+0x3fdfa00)!=0x194 ||
       *(unsigned int *)(b+0x3fdfa08)!=0x0200a0d7 ||
       *(unsigned short *)(b+0x3fdfa64)!=0)
        aspect406_fail("validator or parent entry fingerprint");
    /* 先核对全部前像，避免指纹错误时只改了部分数据。 */
    for(unsigned int i=0;i<3;i++) {
        const unsigned long *r=(void *)(b+0x5560700+i*24);
        if(r[0]!=b+0x2905250 || r[1] || r[2] ||
           *(unsigned short *)(b+desc[i]+0x4c))
            aspect406_fail("registration or descriptor fingerprint");
        for(unsigned int j=0;j<counts[i];j++) {
            unsigned long row=b+rows[i]+j*128;
            if(*(unsigned int *)(row+0x38)!=0x645+i ||
               *(unsigned int *)(row+0x34)!=j ||
               *(unsigned short *)(row+0x64))
                aspect406_fail("option identity or support fingerprint");
        }
    }
    for(unsigned int i=0;i<3;i++) {
        unsigned long *r=(void *)(b+0x5560700+i*24);
        void *page=(void *)((unsigned long)r&~4095UL);
        if(mprotect(page,4096,3))aspect406_fail("registration writable failed");
        r[0]=b+0x29051dc;
        r[1]=(unsigned long)aspect406_ranges[i];
        if(mprotect(page,4096,1))aspect406_fail("registration protection failed");
        char text[160];
        snprintf(text,sizeof text,"APID=%#x validator=+0x29051dc range=%d,%d,%d count=0",
                 0x645+i,aspect406_ranges[i][0],aspect406_ranges[i][1],aspect406_ranges[i][2]);
        record("A7R5_ASPECT406_REGISTRATION ",text);
        aspect406_write16(b,desc[i]+0x4c);
        for(unsigned int j=0;j<counts[i];j++)aspect406_write16(b,rows[i]+j*128+0x64);
    }
    aspect406_write16(b,0x3fdfa64);
    aspect406_base=b;
    aspect406_enabled=1;
    unsigned long *guide=(void *)(b+0x57837f0);
    if(*guide!=b+0x182e138)aspect406_fail("guide draw vtable fingerprint");
    aspect406_original_guide=(void *)*guide;
    void *page=(void *)((unsigned long)guide&~4095UL);
    if(mprotect(page,4096,3))aspect406_fail("guide trace page writable failed");
    *guide=(unsigned long)aspect406_guide;
    if(mprotect(page,4096,1))aspect406_fail("guide trace page protection failed");
    record("A7R5_ASPECT406_INSTALLED ","3 registrations; 3 descriptors; 24 options; 1 parent; RAM only; native mutex retained");
}
static void aspect406_observe(void) {
    if(!aspect406_enabled)return;
    unsigned long b=aspect406_base;
    unsigned int model=((unsigned int (*)(void))(b+0x1bccec4))();
    if(model!=16)aspect406_fail("runtime model column differs");
    /* 这三个原函数返回当前值的地址，不能将地址截断后作为枚举值。 */
    int on=*((const int *(*)(void))(b+0x28ad8f8))();
    int ratio=*((const int *(*)(void))(b+0x28ad920))();
    int opacity=*((const int *(*)(void))(b+0x28ad948))();
    static int seen,previous[3];
    if(!seen || on!=previous[0] || ratio!=previous[1] || opacity!=previous[2]) {
        previous[0]=on;previous[1]=ratio;previous[2]=opacity;seen=1;
        char text[140];
        snprintf(text,sizeof text,"model=%u switch=%d ratio=%d opacity=%d",model,on,ratio,opacity);
        record("A7R5_ASPECT406_STATE ",text);
        int system_mode=*((const int *(*)(void))(b+0x28a3c28))();
        unsigned long *meta=((unsigned long *(*)(void))(b+0x28ad90c))();
        snprintf(text,sizeof text,"system_mode=%d guide_calls=%u switch_meta=%#lx,%#lx,%#lx",
                 system_mode,aspect406_guide_calls,meta[0],meta[1],meta[2]);
        record("A7R5_ASPECT406_REFRESH ",text);
    }
}
