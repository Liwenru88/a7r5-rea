/* 两个ST域的所有非空曲线列；条件由夹具明确设置，不代表机身模式绑定。 */
#define JOINT_STAGE_ONLY 1
#include "look-live-cp.c"
void cp_probe_main(void) {
    initialize_inline_matrix();
    write0("JOINT_STAGE_BEGIN\n");
    for(unsigned slot=0;slot<6;slot++)for(unsigned domain=0;domain<2;domain++) {
        unsigned marker=249+slot;setup(marker,0,0);
        _Alignas(8) u8 secondary[40];zero(secondary,sizeof(secondary));
        ((void(*)(void*,u32,u32,void*))0x71e9c9)(secondary,0,domain,PTR(0x03000000));
        line('D',slot,domain,secondary,32);
        for(unsigned column=0;column<7;column++) {
            if(domain && column!=6)continue;
            _Alignas(8) u8 src[96],dst[96];zero(src,96);zero(dst,96);
            WORD((u32)src+0x10)=marker;src[0xb]=1;
            ((void(*)(void*,void*))0xaa81cb)(src,dst);
            WORD((u32)dst+0x30)=51+2*slot+domain;dst[0x38]=column;
            zero(PTR(0x03010000),0x1000);
            ((void(*)(u32,void*,void*))0x41363d)(0,dst,PTR(0x03010000));
            line('Y',slot,domain*7+column,PTR(0x0301024c),516);
        }
    }
    for(unsigned slot=0;slot<6;slot++)for(unsigned update=0;update<2;update++) {
        _Alignas(8) u8 src[96],dst[96];zero(src,96);zero(dst,96);
        src[0]=update;WORD((u32)src+4)=249+slot;
        ((void(*)(void*,void*))0xaa8689)(src,dst);
        line('R',slot,update,dst,96);
    }
    /* A7R5新增外观不得覆盖已有FL2/FL3视频曲线49、50。 */
    for(unsigned original=49;original<=50;original++) {
        setup(0,0,0);
        _Alignas(8) u8 src[96],dst[96];zero(src,96);zero(dst,96);src[0xb]=1;
        ((void(*)(void*,void*))0xaa81cb)(src,dst);
        WORD((u32)dst+0x30)=original;dst[0x38]=6;
        zero(PTR(0x03010000),0x1000);
        ((void(*)(u32,void*,void*))0x41363d)(0,dst,PTR(0x03010000));
        line('O',original,6,PTR(0x0301024c),516);
    }
    write0("JOINT_STAGE_END\n");done(0);
}
