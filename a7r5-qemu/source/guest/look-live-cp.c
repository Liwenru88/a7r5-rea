/* 每次选择均运行原 CP 全量选择器、矩阵初始化及 Gamma 构造函数。 */
#define cp_probe_main old_cp_batch_main
#include "look-reference-cp.c"
#undef cp_probe_main
static void copy(void *to,const void *from,unsigned n) {
    u8 *d=to;const u8 *s=from;while(n--)*d++=*s++;
}
static void setup(unsigned color,unsigned movie,unsigned fixed) {
    zero(PTR(0x03000000),0x20000);
    WORD(0x03000000)=0x03001000;WORD(0x03000004)=0x03002000;
    WORD(0x03003000)=0x03003800;WORD(0x03003800)=0x03001000;
    WORD(0x03003004)=0x03002000;WORD(0x03003008)=0x03004000;
    WORD(0x0300300c)=0x03005000;WORD(0x03003010)=0x03007000;
    WORD(0x03003014)=0x0300b000;WORD(0x030056b0)=0x03009000;
    WORD(0x0300301c)=0x0300d000;
    WORD(0x03000008)=0x0300e000;WORD(0x0300000c)=0x0300f000;
    WORD(0x0300001c)=0x0300e000;
    PTR(0x03001000)[0x18]=movie?0:2;
    PTR(0x03001000)[1]=1;
    PTR(0x03001000)[0x2e]=color;
    copy(PTR(0x16b3414),PTR(fixed?0x04010000:0x04000000),0x7000);
    copy(PTR(0x16b0f14),PTR(0x04020000),8192);
}
#ifndef JOINT_STAGE_ONLY
void cp_probe_main(void) {
    initialize_inline_matrix();
    volatile u32 *request=(void*)0x04100000;
    unsigned marker=request[0],level=request[1],fixed=request[2],movie=request[3];
    write0("LOOK_LIVE_BEGIN\n");
    /* 同次启动独立构造 ST 和所选外观；均不沿用前次结果。 */
    for(unsigned pass=0;pass<2;pass++) {
        unsigned color=pass?marker:0;
        setup(color,movie,fixed);
        ((void(*)(void*,void*))0x232fe1)(PTR(0x03000000),PTR(0x03003000));
        line('S',pass,color,PTR(0x03004000),0x190);
        ((void(*)(void*,void*))0x234345)(PTR(0x03000000),PTR(0x03003000));
        line('B',pass,color,PTR(0x0300417c),6);
        line('H',pass,color,PTR(0x030041a0),66);
        _Alignas(8) u16 cal[256];zero(cal,sizeof(cal));
        copy(cal+0xd0,PTR(0x0300417c),6);
        u32 context[2]={0x03001000,(u32)cal};_Alignas(8) u8 matrix[64];
        unsigned profile=PTR(0x03004000)[1];
        _Alignas(8) u8 cc1[64];zero(cc1,sizeof(cc1));
        ((void(*)(void*,u32,void*))0x71e671)(cc1,profile,PTR(0x03000000));
        line('C',pass,color,cc1,48);
        _Alignas(8) u8 secondary[40];zero(secondary,sizeof(secondary));
        ((void(*)(void*,u32,u32,void*))0x71e9c9)(secondary,profile,0,PTR(0x03000000));
        line('D',pass,color,secondary,32);
        ((void(*)(void*,void*))0x231eb9)(PTR(0x03000000),PTR(0x03003000));
        line('P',pass,color,PTR(0x03004042),16);
        ((void(*)(void*,void*))0x71f675)(PTR(0x03000000),PTR(0x03003000));
        line('N',pass,color,PTR(0x03004182),2);
        for(unsigned slot=0;slot<16;slot++) {
            for(unsigned i=0;i<64;i++)matrix[i]=0xa5;
            ((void(*)(void*,u32,void*,u32))0x71e41f)(matrix,slot,context,profile);
            for(unsigned i=54;i<64;i++)if(matrix[i]!=0xa5)done(87);
            line('M',pass,slot,matrix,54);
        }
        _Alignas(8) u8 src[96],dst[96];zero(src,96);zero(dst,96);
        WORD((u32)src+0x10)=color;src[8]=movie;src[0xb]=1;
        ((void(*)(void*,void*))0xaa81cb)(src,dst);
        line('G',pass,color,dst,96);line('I',pass,color,src,96);
        /* 原厂消费者产生真实非等距横轴与输出曲线，未替换依赖函数。 */
        zero(PTR(0x03010000),0x1000);
        ((void(*)(u32,void*,void*))0x41363d)(0,dst,PTR(0x03010000));
        line('X',pass,color,PTR(0x03010018),516);
        line('Y',pass,color,PTR(0x0301024c),516);
        if(color>=249 && color<=254) {
            /* 候选挂钩使用调用点保存的寄存器，输出真实硬件排列银行。 */
            PTR(0x03002000)[3]=1;look_select();
            line('T',pass,color,PTR(0x03004184),8);
            PTR(0x03001000)[0x2f]=level;
            ((void(*)(void*,void*))0x231655)(PTR(0x03000000),PTR(0x03003000));
            line('L',pass,color,PTR(0x03009000),1620);
        }
    }
    write0("LOOK_LIVE_END\n");done(0);
}
#endif
