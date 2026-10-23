/* 直接调用不修改的 CP 矩阵函数；仅构造输入，不实现替代色彩计算。 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
static void host_write(const char *text) {
    register u32 r0 __asm__("r0")=4;
    register const char *r1 __asm__("r1")=text;
    /* ARM A-profile Thumb 使用 SVC；BKPT #0xab 是 M-profile 的入口。 */
    __asm__ volatile("svc #0xab" : "+r"(r0) : "r"(r1) : "memory");
}
static void hex(char **at,u32 value,unsigned digits) {
    const char *symbols="0123456789abcdef";
    for(unsigned i=digits;i;i--)*(*at)++=symbols[(value>>((i-1)*4))&15];
}
static void text(char **at,const char *source) {while(*source)*(*at)++=*source++;}
static void zero(volatile u8 *p,unsigned count) {for(unsigned i=0;i<count;i++)p[i]=0;}

__attribute__((noreturn)) void cp_exception_main(u32 fault,u32 address,u32 link,u32 status) {
    char line[128],*at=line;text(&at,"CP_NATIVE_EXCEPTION fault=");hex(&at,fault,8);
    text(&at," address=");hex(&at,address,8);text(&at," link=");hex(&at,link,8);
    text(&at," status=");hex(&at,status,8);*at++='\n';*at=0;host_write(line);
    u32 arguments[2]={0x20026,86};
    register u32 r0 __asm__("r0")=0x20;register u32 *r1 __asm__("r1")=arguments;
    __asm__ volatile("svc #0xab" : "+r"(r0) : "r"(r1) : "memory");
    for(;;)__asm__ volatile("wfi");
}

__attribute__((noreturn)) void cp_probe_main(void) {
    volatile u8 *property=(void *)0x016b3414;
    zero(property,0x7000);
    for(unsigned profile=0;profile<52;profile++)property[0x196+profile]=profile&3;
    for(unsigned bank=0;bank<4;bank++)for(unsigned group=0;group<3;group++)
        for(unsigned slot=0;slot<16;slot++)for(unsigned k=0;k<6;k++) {
            u16 value=(u16)((int)((bank*211+group*71+slot*17+k*31)&1023)-512);
            volatile u16 *item=(void *)(property+0x1e0+bank*768+group*192+slot*12+k*2);
            *item=value;
        }
    const u32 slots[4]={0,15,16,0xffffffff};
    const u16 calibration[3][3]={{0,0,0},{256,256,256},{65535,32768,12345}};
    u16 calibration_input[256];u32 context[2]={0,(u32)calibration_input};
    u8 output[64];unsigned cases=0;
    typedef void (*matrix_function)(void *,u32,void *,u32);
    matrix_function matrix=(matrix_function)(0x108000 + 0x61641e + 1);
    host_write("CP_NATIVE_MATRIX_BEGIN version=1 synthetic_parameters=1\n");
    for(unsigned index=0;index<258;index++) {
        u32 profile=index==257?0xffffffff:index;
        for(unsigned slot=0;slot<4;slot++)for(unsigned cal=0;cal<3;cal++) {
            zero((void *)calibration_input,sizeof calibration_input);
            for(unsigned i=0;i<3;i++)calibration_input[0xd0+i]=calibration[cal][i];
            for(unsigned i=0;i<64;i++)output[i]=0xa5;
            matrix(output,slots[slot],context,profile);
            char line[240],*at=line;
            text(&at,"CP_MATRIX profile=");hex(&at,profile,8);
            text(&at," slot=");hex(&at,slots[slot],8);
            text(&at," calibration=");hex(&at,cal,1);text(&at," data=");
            for(unsigned i=0;i<64;i++)hex(&at,output[i],2);
            *at++='\n';*at=0;host_write(line);cases++;
        }
    }
    char line[80],*at=line;text(&at,"CP_NATIVE_MATRIX_END cases=");hex(&at,cases,8);
    *at++='\n';*at=0;host_write(line);
    u32 arguments[2]={0x20026,0};
    register u32 r0 __asm__("r0")=0x20;
    register u32 *r1 __asm__("r1")=arguments;
    __asm__ volatile("svc #0xab" : "+r"(r0) : "r"(r1) : "memory");
    for(;;)__asm__ volatile("wfi");
}
