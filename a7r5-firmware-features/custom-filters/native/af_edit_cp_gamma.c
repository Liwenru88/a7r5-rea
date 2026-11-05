#include "af_edit_cp_gamma.h"
#include "af_sha256.h"
_Static_assert(sizeof(AfEditCpGamma)==AF_EDIT_CP_GAMMA_OUTPUT_BYTES,"Gamma output layout");

static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m &&
           (x+n<=y || y+m<=x);
}
static int equal(const uint8_t *a,const uint8_t *b) {
    unsigned difference=0;
    for (unsigned i=0;i<32;++i) difference|=a[i]^b[i];
    return !difference;
}
int af_edit_cp_gamma(const void *record,size_t bytes,const uint32_t *curve,size_t points,
                      AfEditCpGamma *output,AfGridProgress progress,void *context) {
    static const uint8_t source_sha[32]={
        0xf4,0xe9,0xf3,0x1b,0xce,0x38,0xb4,0xc7,0x05,0x72,0x1a,0x50,0x1c,0x75,0x97,0x70,
        0x58,0x52,0xe6,0x71,0xbc,0x39,0xba,0xf6,0x0b,0x02,0xda,0xc8,0xb8,0x8f,0x95,0xac};
    static const uint8_t axis_sha[32]={
        0x67,0x64,0x4a,0x74,0xc4,0xc7,0xc6,0x30,0x95,0xde,0x90,0x06,0x46,0xf7,0xf8,0x7e,
        0x49,0xbc,0x71,0x85,0xbb,0x40,0xa4,0xb8,0x80,0xf7,0xca,0xf0,0xec,0x6a,0x17,0x70};
    uint32_t axis[129];uint8_t digest[32],encoded[516];AfEditCpGamma candidate;
    if (bytes!=576 || points!=129 ||
        !apart(record,576,output,sizeof(*output)) ||
        !apart(curve,516,output,sizeof(*output)) ||
        (uintptr_t)curve%_Alignof(uint32_t) ||
        (uintptr_t)output%_Alignof(AfEditCpGamma)) return AF_INVALID;
    if (progress && progress(context,0,128)) return AF_GRID_CANCELLED;
    if (af_sha256(record,576,digest)!=0 || !equal(digest,source_sha) ||
        af_gamma406_axis(record,axis)!=AF_OK) return AF_INVALID;
    for (unsigned i=0;i<129;++i)
        for (unsigned j=0;j<4;++j) encoded[4*i+j]=(uint8_t)(axis[i]>>(8*j));
    if (af_sha256(encoded,sizeof(encoded),digest)!=0 || !equal(digest,axis_sha) ||
        axis[127]!=61440 || axis[128]!=65535 || curve[0] || !curve[128]) return AF_INVALID;
    for (unsigned i=0;i<129;++i)
        if (curve[i]>0x3ffffu || (i && curve[i]<curve[i-1])) return AF_INVALID;
    for (unsigned i=0;i<129;++i) if (curve[i]>0x1ffffu) return AF_JOINT_SKIP;
    for (unsigned i=0;i<128;++i) {
        unsigned source=i==127?128:i;
        candidate.axis[i]=32u*axis[source];candidate.gamma_y[i]=2u*curve[source];
    }
    /* 整数乘法使用64位；显式重建被删除的自由度，不能静默忽略。 */
    uint32_t width=axis[128]-axis[126],offset=axis[127]-axis[126];
    uint32_t edit_y=candidate.gamma_y[126]+(uint32_t)(
        ((uint64_t)(candidate.gamma_y[127]-candidate.gamma_y[126])*offset)/width);
    if ((edit_y+1u)/2u!=curve[127]) return AF_JOINT_SKIP;
    if (progress && progress(context,128,128)) return AF_GRID_CANCELLED;
    for (unsigned i=0;i<128;++i) {
        output->axis[i]=candidate.axis[i];output->gamma_y[i]=candidate.gamma_y[i];
    }
    return AF_OK;
}
