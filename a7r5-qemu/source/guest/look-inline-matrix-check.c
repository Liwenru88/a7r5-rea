/* 内嵌与设置路径等价验证；仅清除合成 BSS、加载参数，不模拟 ISP。 */
#define cp_probe_main unused_batch_main
#include "look-reference-cp.c"
#undef cp_probe_main

extern unsigned checked_matrix(void *,u32,void *,u32);
__asm__(".thumb\n.global checked_matrix\n.thumb_func\nchecked_matrix:\n"
 "push {r4-r11,lr}\nsub sp,#4\n"
 "movs r4,#0x44\nmovs r5,#0x55\nmovs r6,#0x66\nmovs r7,#0x77\n"
 "mov.w r8,#0x88\nmov.w r9,#0x99\nmov.w r10,#0xaa\nmov.w r11,#0xbb\n"
 "movw ip,#0xe41f\nmovt ip,#0x71\nblx ip\n"
 "cmp r4,#0x44\nbne 1f\ncmp r5,#0x55\nbne 1f\n"
 "cmp r6,#0x66\nbne 1f\ncmp r7,#0x77\nbne 1f\n"
 "cmp r8,#0x88\nbne 1f\ncmp r9,#0x99\nbne 1f\n"
 "cmp r10,#0xaa\nbne 1f\ncmp r11,#0xbb\nbne 1f\n"
 "movs r0,#0\nb 2f\n1: movs r0,#1\n2: add sp,#4\npop {r4-r11,pc}\n");

static u32 property_hash(void) {
    u32 n=2166136261u;
    for(unsigned i=0;i<0x7000;i++)n=(n^PTR(0x16b3414)[i])*16777619u;
    return n;
}

void cp_probe_main(void) {
    unsigned mode=WORD(0x04100000);
    if(mode==3) {
        /* 仅隔离完整性负例：原始文件不变，在客体暂存区破坏一个字节。 */
        PTR(0x11d4000)[0]^=1;
        inline_boot_copy();
        done(93); /* 正确行为是拒绝返回，不能带损坏矩阵继续启动。 */
    }
    if(mode>2)done(89);
    initialize_inline_matrix();
    /* 原 BSS 清零范围；候选表必须位于其外，不能依赖未清 BSS 中的载入残留。 */
    zero(PTR(0x1197000),0x8a2448);
    u8 *source=PTR(mode==1?0x04010000:0x04000000);
    for(unsigned i=0;i<0x7000;i++)PTR(0x16b3414)[i]=source[i];
    if(mode==2) {
        /* 目标设置故意为未知内容，验证内嵌读取不再取这些设置。 */
        for(unsigned p=54;p<58;p++)PTR(0x16b3414)[0x196+p]=31;
        for(unsigned i=0x43e0;i<0x4fe0;i++)PTR(0x16b3414)[i]=0x6d;
    }
    u32 before=property_hash(), count=0;
    /* QEMU 默认内存属性要求字访问对齐；每行补为8字节，不依赖非对齐载入。 */
    _Alignas(4) const u16 cals[4][4]={{0,0,0,0},{256,256,256,0},{1024,1024,1024,0},{65535,32768,12345,0}};
    const u32 controls[4]={0,15,16,0xffffffff};
    u16 cal[256];u32 context[2]={0,(u32)cal};u8 output[64];
    write0("MATRIX_INLINE_CHECK_BEGIN\n");
    for(unsigned index=0;index<258;index++) {
        u32 profile=index==257?0xffffffff:index;
        unsigned target=profile>=54 && profile<=57;
        for(unsigned s=0;s<(target?18:4);s++)for(unsigned c=0;c<(target?4:3);c++) {
            u32 slot=target?(s==17?0xffffffff:s):controls[s];
            unsigned ci=target?c:(c==2?3:c);
            zero(cal,sizeof cal);for(unsigned i=0;i<3;i++)cal[0xd0+i]=cals[ci][i];
            for(unsigned i=0;i<64;i++)output[i]=0xa5;
            if(checked_matrix(output,slot,context,profile))done(90);
            line('M',profile,count++,output,64);
        }
    }
    if(property_hash()!=before)done(91);
    line('F',count,before,&before,4);
    write0("MATRIX_INLINE_CHECK_END\n");done(0);
}
