/* 创意外观指令窗口；提供显式夹具，不启动 CP/RTOS 或像素 ISP。 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
static void write0(const char *s) {
    register u32 r0 __asm__("r0")=4;
    register const char *r1 __asm__("r1")=s;
    __asm__ volatile("svc #0xab":"+r"(r0):"r"(r1):"memory");
}
static void hex(char **p,u32 v,unsigned n) {
    const char *h="0123456789abcdef";
    for(unsigned i=n;i;i--)*(*p)++=h[(v>>((i-1)*4))&15];
}
static void zero(void *p,unsigned n) {u8 *b=p;while(n--)*b++=0;}
static void line(char tag,u32 a,u32 b,const void *raw,unsigned n) {
    char s[3400],*p=s;*p++=tag;*p++=' ';hex(&p,a,8);*p++=' ';hex(&p,b,8);*p++=' ';
    const u8 *v=raw;for(unsigned i=0;i<n;i++)hex(&p,v[i],2);
    *p++='\n';*p=0;write0(s);
}
static __attribute__((noreturn)) void done(u32 code) {
    u32 args[2]={0x20026,code};register u32 r0 __asm__("r0")=0x20;
    register u32 *r1 __asm__("r1")=args;
    __asm__ volatile("svc #0xab":"+r"(r0):"r"(r1):"memory");for(;;){}
}
void cp_exception_main(u32 a,u32 b,u32 c,u32 d) {
    u32 v[4]={a,b,c,d};line('E',a,b,v,16);done(86);
}
/* 固定寄存器是 CP helper 的原调用约定；保存宿主测试调用者寄存器。 */
extern void look_select(void);
__asm__(".thumb\n.global look_select\n.thumb_func\nlook_select:\n"
 "push {r4-r11,lr}\nsub sp,#4\n"
 "movw r5,#0x4000\nmovt r5,#0x0300\n"
 "movw r9,#0\nmovt r9,#0x0300\n"
 "movw r10,#0x1000\nmovt r10,#0x0300\n"
 "movw r8,#0x3000\nmovt r8,#0x0300\n"
 "movs r0,#0\nmovs r1,#0\nmovs r2,#0\n"
 "movw r3,#0xf4c1\nmovt r3,#0xbe\nblx r3\n"
 "add sp,#4\npop {r4-r11,pc}\n");
#define PTR(a) ((u8 *)(a))
#define WORD(a) (*(u32 *)(a))
/* 仅等长候选的函数夹具调用实际CP复制器；不等于完整引导已经执行。 */
extern void inline_boot_copy(void);
__asm__(".thumb\n.global inline_boot_copy\n.thumb_func\ninline_boot_copy:\n"
 "push {r4,lr}\nmovw r4,#0x8000\nmovt r4,#0x12\n"
 "movw ip,#0x8f41\nmovt ip,#0x10\nblx ip\npop {r4,pc}\n");
static void initialize_inline_matrix(void) {
    if(WORD(0x04100010)==1) {
        inline_boot_copy();inline_boot_copy();
        for(unsigned i=0;i<2304;i++)if(PTR(0x11d4000)[i])done(92);
    }
}
void cp_probe_main(void) {
    /* 原 CP 函数的独立参数区，位于普通 RAM，不提供 MMIO 或核间应答。 */
    zero(PTR(0x03000000),0x20000);
    WORD(0x03000000)=0x03001000;WORD(0x03000004)=0x03002000;
    PTR(0x03002000)[3]=1;
    WORD(0x03003004)=0x03003800;WORD(0x03003008)=0x03004000;
    WORD(0x0300300c)=0x03005000;WORD(0x03003010)=0x03007000;
    WORD(0x03003014)=0x0300b000;WORD(0x030056b0)=0x03009000;
    write0("LOOK_CP_BEGIN\n");
    for(unsigned flag=0;flag<2;flag++)for(unsigned marker=249;marker<=254;marker++) {
        PTR(0x03001000)[1]=flag;PTR(0x03001000)[0x2e]=marker;look_select();
        line('S',marker,flag,PTR(0x03004184),8);
        for(unsigned level=1;level<=8;level++) {
            PTR(0x03001000)[0x2f]=level;
            ((void(*)(void*,void*))0x231655)(PTR(0x03000000),PTR(0x03003000));
            line('L',marker,flag*8+level,PTR(0x03009000),1620);
        }
    }
    /* 基线/修复两份同源矩阵属性，三光源端点由原函数完整输出。 */
    u16 cal[256];zero(cal,sizeof(cal));cal[0xd0]=cal[0xd1]=cal[0xd2]=256;
    u32 context[2]={0,(u32)cal};u8 output[64];
    for(unsigned fixed=0;fixed<2;fixed++) {
        u8 *prop=PTR(fixed?0x04010000:0x04000000);
        for(unsigned i=0;i<0x7000;i++)PTR(0x16b3414)[i]=prop[i];
        const unsigned profiles[5]={0,54,55,56,57};
        for(unsigned n=0;n<5;n++)for(unsigned slot=0;slot<16;slot++) {
            unsigned profile=profiles[n];
            ((void(*)(void*,u32,void*,u32))0x71e41f)(output,slot,context,profile);
            line('M',profile,fixed*16+slot,output,54);
        }
    }
    /* 原 Gamma 全量与局部归一化，色彩源缓冲区应保持不变。 */
    for(unsigned route=0;route<2;route++)for(unsigned movie=0;movie<2;movie++)
      for(unsigned color=0;color<=254;color++) {
        if(color>21 && color<249)continue;
        u8 src[96],dst[96];zero(src,96);zero(dst,96);
        WORD((u32)src+0x10)=color;src[8]=movie;src[0xb]=1;
        if(route) {src[0]=1;WORD((u32)src+4)=color;}
        if(route)((void(*)(void*,void*))0xaa8689)(src,dst);
        else ((void(*)(void*,void*))0xaa81cb)(src,dst);
        line('G',color,route*2+movie,dst,96);line('I',color,route*2+movie,src,96);
      }
    write0("LOOK_CP_END\n");done(0);
}
