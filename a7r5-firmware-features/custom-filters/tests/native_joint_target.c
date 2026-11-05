/* 合成四组件耦合后端，只验搜索/量化契约，不表示CP像素模型。 */
#include "../native/af_joint.h"
extern void *memset(void *,int,size_t);
static AfJointWork work;
static AfJointRecipe seed,output;
static AfGridSample training[8];
static float values[24];
AfJointFit af_joint_target_fit;
uint32_t af_joint_target_report[8];
float af_joint_target_metrics[2];
static const uint8_t cp[32]={0x18,0xb2,0x65,0xc5,0x89,0xeb,0x42,0x01,0xd3,0xb3,0x68,0x08,0x57,0xd8,0x97,0xb6,
    0x93,0xd0,0x6c,0x6d,0xd4,0x91,0xd7,0x95,0xdb,0xb3,0xa6,0x16,0xd6,0x18,0x2e,0x97};
int af_joint_synthetic_predict(void *context,const AfJointRecipe *r,const float *rgb,float *out) {
    float gain=(float)r->gamma[128]/131072;
    (void)context;
    out[0]=rgb[0]*gain+r->matrix[0]*(rgb[1]-rgb[0])/1024;
    out[1]=rgb[1]*gain+r->cc1[0]*(rgb[2]-rgb[1])/1024;
    out[2]=rgb[2]*gain+r->grid[0]*rgb[0]*rgb[2]/256;
    return AF_OK;
}
static int cancelled(void *context,uint32_t completed,uint32_t total) {
    (void)context;(void)total;return completed==3;
}
#define CHECK(v) do {++af_joint_target_report[1];if (!(v)) return __LINE__;} while (0)
uint32_t af_joint_target_check(void) {
    AfCube cube={2,{0,0,0},{1,1,1},values};
    AfJointOptions options={65,256,16,16,16,4};
    AfJointModel model={0};unsigned n=0;
    memset(af_joint_target_report,0,sizeof(af_joint_target_report));
    af_joint_target_report[0]=0x4a323031u;
    memset(&seed,0,sizeof(seed));
    for (unsigned i=0;i<129;++i) seed.gamma[i]=i*1024;
    model.schema=model.base_mask=model.domain=1;model.components=15;
    for (unsigned i=0;i<32;++i) model.cp_sha256[i]=cp[i];
    model.model_sha256[0]=0x20;model.predict=af_joint_synthetic_predict;
    for (unsigned b=0;b<2;++b) for (unsigned g=0;g<2;++g) for (unsigned r=0;r<2;++r) {
        /* 目标由独立公式生成，包含乘积项，2维CUBE可精确插值。 */
        values[n*3]=(float)r*1.015625f+((float)g-r)/64;
        values[n*3+1]=(float)g*1.015625f+((float)b-g)/64;
        values[n*3+2]=(float)b*1.015625f+(float)(r*b)/64;
        training[n]=(AfGridSample){{.1f+.6f*r,.15f+.55f*g,.12f+.5f*b},1,0};++n;
    }
    CHECK(af_joint_fit(&model,0,&cube,training,8,&seed,&options,&work,&output,&af_joint_target_fit,0,0)==AF_OK);
    CHECK(af_joint_valid(&output)==AF_OK);
    CHECK(af_joint_target_fit.attempted_components==15);
    for (unsigned i=0;i<4;++i) CHECK(af_joint_target_fit.accepted[i]>0);
    CHECK(af_joint_target_fit.final_mse<af_joint_target_fit.initial_mse*.1f);
    CHECK(af_joint_target_fit.evaluations==options.evaluations && af_joint_target_fit.research_only==1);
    af_joint_target_report[2]=af_joint_target_fit.evaluations;
    af_joint_target_report[3]=(uint32_t)sizeof(work);
    af_joint_target_report[4]=af_joint_target_fit.attempted_components;
    af_joint_target_metrics[0]=af_joint_target_fit.initial_mse;
    af_joint_target_metrics[1]=af_joint_target_fit.final_mse;
    for (unsigned i=0;i<4;++i) af_joint_target_report[6]+=af_joint_target_fit.accepted[i];
    af_joint_target_report[7]=(uint32_t)sizeof(output);
    /* 失败/取消保留调用者已发布候选及结果，检查全部字节。 */
    memset(&output,0x5a,sizeof(output));memset(&af_joint_target_fit,0xa5,sizeof(af_joint_target_fit));
    CHECK(af_joint_fit(&model,0,&cube,training,8,&seed,&options,&work,&output,&af_joint_target_fit,cancelled,0)==AF_GRID_CANCELLED);
    for (unsigned i=0;i<sizeof(output);++i) CHECK(((uint8_t *)&output)[i]==0x5a);
    for (unsigned i=0;i<sizeof(af_joint_target_fit);++i) CHECK(((uint8_t *)&af_joint_target_fit)[i]==0xa5);
    model.components=8;
    CHECK(af_joint_fit(&model,0,&cube,training,8,&seed,&options,&work,&output,&af_joint_target_fit,0,0)==AF_INVALID);
    af_joint_target_report[5]=1;
    return 0;
}
