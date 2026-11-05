/* AArch64转换器无设备联验：公开模型数值由构建器按固定夹具生成。 */
#include "../native/af_grid.h"
extern void *memset(void *,int,size_t);
extern const AfGridModel af_grid_test_model;
static AfGridWork work;
static float values[24];
static int8_t grid[AF_GRID_BYTES];
static AfGridSample train[27],holdout[8];
AfGridFit af_grid_target_fit;
AfGridReport af_grid_target_metrics;
int8_t af_grid_target_result[AF_GRID_BYTES];
uint32_t af_grid_target_report[8];
static int cancel(void *context,uint32_t completed,uint32_t total) {
    (void)context;(void)total;return completed==2;
}
#define CHECK(v) do {++af_grid_target_report[1];if (!(v)) return __LINE__;} while (0)
uint32_t af_grid_target_check(void) {
    AfCube cube={0};unsigned n=0;
    const char identity[]="LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n";
    const char transformed[]="LUT_3D_SIZE 2\n.035 .01 .023\n.975 .01 .023\n.035 .97 .023\n.975 .97 .023\n.035 .01 .973\n.975 .01 .973\n.035 .97 .973\n.975 .97 .973\n";
    memset(af_grid_target_report,0,sizeof(af_grid_target_report));
    af_grid_target_report[0]=0x47313831u;
    for (unsigned r=0;r<3;++r) for (unsigned g=0;g<3;++g) for (unsigned b=0;b<3;++b) {
        train[n]=(AfGridSample){{.15f+.35f*r,.15f+.35f*g,.15f+.35f*b},1,0};++n;
    }
    n=0;
    for (unsigned r=0;r<2;++r) for (unsigned g=0;g<2;++g) for (unsigned b=0;b<2;++b) {
        holdout[n]=(AfGridSample){{.3f+.4f*r,.3f+.4f*g,.3f+.4f*b},1,r==g && g==b?1u:2u};++n;
    }
    CHECK(af_cube_parse(identity,sizeof(identity)-1,&cube,values,24,(AfCubeLimits){33,4096})==0);
    CHECK(af_grid_fit(&af_grid_test_model,1,&cube,train,27,24,.001f,grid,&work,&af_grid_target_fit,0,0)==0);
    for (unsigned i=0;i<AF_GRID_BYTES;++i) CHECK(grid[i]==0);
    CHECK(af_grid_report(&af_grid_test_model,&cube,grid,holdout,8,&work,&af_grid_target_metrics)==0);
    CHECK(af_grid_target_metrics.delta_e76[2]==0);
    CHECK(af_cube_parse(transformed,sizeof(transformed)-1,&cube,values,24,(AfCubeLimits){33,4096})==0);
    CHECK(af_grid_fit(&af_grid_test_model,1,&cube,train,27,48,.001f,grid,&work,&af_grid_target_fit,0,0)==0);
    CHECK(af_grid_target_fit.quantized_mse<af_grid_target_fit.zero_mse);
    af_grid_target_report[2]=af_grid_target_fit.iterations;
    CHECK(af_grid_report(&af_grid_test_model,&cube,grid,holdout,8,&work,&af_grid_target_metrics)==0);
    CHECK(af_grid_target_metrics.samples==8 && af_grid_target_metrics.gray_samples==2 && af_grid_target_metrics.skin_samples==6);
    af_grid_target_report[3]=af_grid_target_metrics.samples;
    for (unsigned i=0;i<AF_GRID_BYTES;++i) af_grid_target_result[i]=grid[i];
    memset(grid,55,sizeof(grid));
    CHECK(af_grid_fit(&af_grid_test_model,1,&cube,train,27,24,.001f,grid,&work,&af_grid_target_fit,cancel,0)==AF_GRID_CANCELLED);
    for (unsigned i=0;i<AF_GRID_BYTES;++i) CHECK(grid[i]==55);
    af_grid_target_report[4]=1;af_grid_target_report[5]=(uint32_t)sizeof(work);
    CHECK(af_grid_fit(&af_grid_test_model,17,&cube,train,27,24,.001f,grid,&work,&af_grid_target_fit,0,0)==AF_INVALID);
    CHECK(af_grid_fit(&af_grid_test_model,0,&cube,train,27,24,.001f,grid,&work,&af_grid_target_fit,0,0)==AF_INVALID);
    af_grid_target_report[6]=1;af_grid_target_report[7]=AF_GRID_BYTES;
    return 0;
}
