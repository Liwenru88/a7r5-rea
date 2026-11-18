/* 与主机共用的目标参数契约；原CP整函数对照由独立执行器完成。 */
#include "../native/af_color406.h"
uint32_t af_color406_target_report[4];
#define CHECK(v) do {++af_color406_target_report[1];if (!(v)) return __LINE__;} while (0)
uint32_t af_color406_target_check(void) {
    static const int16_t expected[27]={1004,-1,-2,-3,1030,-4,-5,-6,1068,1016,-7,-8,-9,1042,-10,-11,-12,1080,
        1028,-13,-14,-15,1054,-16,-17,-18,1092};
    static const int16_t primary[24]={-7,2,-9,8,201,212,241,254,-3,7,-3,15,209,221,251,265,5,15,5,23,217,229,259,273};
    uint16_t raw[24],cal[3]={1001,1023,1057},metadata[8];int16_t adjust[8]={-3,5,-7,9,201,211,239,251};
    int16_t out[27],delta[27],source[27];
    af_color406_target_report[0]=0x43323331;af_color406_target_report[1]=0;
    for (unsigned i=0;i<24;++i) raw[i]=(uint16_t)(i+1);
    CHECK(af_color406_matrix(raw,cal,out)==AF_OK);
    for (unsigned i=0;i<27;++i) CHECK(out[i]==expected[i]);
    for (unsigned i=0;i<24;++i) raw[i]=(uint16_t)((int)i-4);
    for (unsigned i=0;i<8;++i) metadata[i]=(uint16_t)(32768+i);
    CHECK(af_color406_primary(raw,adjust,out)==AF_OK);
    for (unsigned i=0;i<24;++i) CHECK(out[i]==primary[i]);
    CHECK(af_color406_secondary(raw,adjust,metadata,out)==AF_OK);
    for (unsigned i=0;i<8;++i) {CHECK(out[i]==primary[i]);CHECK(out[i+8]==-32768+(int)i);}
    for (unsigned i=0;i<27;++i) {source[i]=32760;delta[i]=16;out[i]=12345;}
    CHECK(af_color406_add(source,delta,27,out)==AF_OK);
    for (unsigned i=0;i<27;++i) CHECK(out[i]==-32760);
    CHECK(af_color406_matrix(raw,cal,(int16_t *)raw)==AF_INVALID);
    CHECK(af_color406_add(source,delta,26,out)==AF_INVALID);
    for (unsigned i=0;i<27;++i) CHECK(out[i]==-32760);
    {
        uint8_t bytes[8]={128,255,0,127,128,255,0,127};uint16_t weights[4]={128,0,0,0};
        static const int16_t wanted[8]={-128,-1,0,127,128,255,0,127};
        CHECK(af_color406_adjust(bytes,out)==AF_OK);
        for (unsigned i=0;i<8;++i) CHECK(out[i]==wanted[i]);
        CHECK(af_color406_adjust(bytes,(int16_t *)(void *)bytes)==AF_INVALID);
        for (unsigned i=0;i<27;++i) source[i]=i<9?-1:i<18?0:32767;
        CHECK(af_color406_matrix_blend(source,weights,out)==AF_OK);
        for (unsigned i=0;i<9;++i) CHECK(out[i]==0);
        weights[3]=128;
        CHECK(af_color406_matrix_blend(source,weights,out)==AF_OK);
        for (unsigned i=0;i<9;++i) CHECK(out[i]==-1);
        weights[1]=weights[2]=256;
        CHECK(af_color406_matrix_blend(source,weights,out)==AF_INVALID);
        for (unsigned i=0;i<9;++i) CHECK(out[i]==-1);
        CHECK(af_color406_matrix_blend(source,weights,source)==AF_INVALID);
    }
    af_color406_target_report[2]=27;af_color406_target_report[3]=24;
    return 0;
}
