/* 固定修改版4.06的原构造后增量；不改变原银行分组发布或相机准入。 */
#ifndef AF_CP_COMPONENTS406_H
#define AF_CP_COMPONENTS406_H
#include "af_cp_jobs406.h"
#define AF_CP_COMPONENTS406_FORMATTER 0x1f6a08cu
#define AF_CP_COMPONENTS406_GAMMA_TABLE 0x1a396d8u
#define AF_CP_COMPONENTS406_RECORD_BYTES 576u
#define AF_CP_COMPONENTS406_RO_BEGIN 0xbf0000u
#define AF_CP_COMPONENTS406_RO_END 0x107f000u
#define AF_CP_COMPONENTS406_SHOT 0x1f0a830u
#define AF_CP_COMPONENTS406_SHOT_BASELINE 0x1f10a50u
#define AF_CP_COMPONENTS406_SHOT_BYTES 0x12d8u
#define AF_CP_COMPONENTS406_SHOT_COPY_LR 0x313c75u
#define AF_CP_COMPONENTS406_GAMMA_PACKED0 0x1f6c024u
#define AF_CP_COMPONENTS406_GAMMA_PACKED1 0x1f6caa4u
#define AF_CP_COMPONENTS406_GAMMA_PACKED_BYTES 0x466u
#define AF_CP_COMPONENTS406_SOURCE 0x1f6a088u
#define AF_CP_COMPONENTS406_SHADOW 0x1f6a43cu
#define AF_CP_COMPONENTS406_SOURCE_BYTES 84u
#define AF_CP_COMPONENTS406_SHADOW_LR 0xaa697du

/* 原formatter元数据的按值伴随身份，不含asset指针，不授予图像帧或第二域资格。 */
typedef struct {
    uint64_t version;
    uint32_t input_source,input_epoch,snapshot_epoch,slot,ticket,source_epoch;
    int16_t tone[3];
    uint16_t reserved;
} AfCpGamma406Tone;

typedef struct {
    void *context;
    int (*view)(void *,uint32_t,AfCpJobs406View *);
    int (*current)(void *,const AfCpJobs406View *);
    int (*read)(void *,uint32_t,void *,size_t);
    uint32_t (*matrix)(void *,void *,uint32_t,void *,uint32_t);
    uint32_t (*cc1)(void *,void *,uint32_t,void *);
    uint32_t (*gamma)(void *,uint32_t,const void *,void *);
    uint32_t (*gamma_record)(void *,uint32_t,const void *,void *,const void *);
    void *(*map)(void *,uint32_t,size_t);
    uint32_t (*grid_query)(void *,void *,void *);
    void (*grid_pack)(void *,void *,void *);
    uint32_t grid_cleanup;
    int (*address)(void *,const void *,size_t,uint32_t *);
    /* 原厂回退也须核真实任务；不能把view缺失当作可跨线程写packed的资格。 */
    int (*worker)(void *,uint32_t);
    uint32_t (*gamma_source)(void *,const void *);
    uint32_t (*gamma_reset)(void *,const void *);
    void (*copy)(void *,void *,const void *,size_t);
} AfCpComponents406Ports;
/* Gamma工作区只供已核同步任务；网格active以CAS保护跨主/Capture的LR和暂借raw。 */
typedef struct {
    AfCpComponents406Ports ports;
    uint32_t gamma_busy,gamma_private_mask;
    struct {
        uint32_t guard,fault,epoch,building,source_ready,shadow_ready,shadow_busy,identity_ready;
        AfCpGamma406Tone source,shadow;
        uint8_t image[AF_CP_COMPONENTS406_SOURCE_BYTES];
        uint8_t shadow_image[AF_CP_COMPONENTS406_SOURCE_BYTES];
    } gamma_handoff;
    _Alignas(4) uint8_t original[576],adjusted[576];
    uint32_t gamma_before[129],gamma_after[129],gamma_work[129];
    struct {uint32_t packed,private_packed;} grid_banks[4];
    struct {
        uint32_t active,original_lr,raw,bank,private_run,query_result,native_selector;
        uint8_t type,format;
        uint8_t *state,*context;
    } grid;
} AfCpComponents406;
size_t af_cp_components406_bytes(void);
/* 仅boot零对象配置一次；端口必须全部提供，不能默认成功。 */
int af_cp_components406_init(AfCpComponents406 *,const AfCpComponents406Ports *);
/* 实际worker已RUNNING、调用原worker之前的资格复核。成功仅表示此视图可继续，
 * 不是构造器/原分组发布/照片完成凭证。正常id3原路线本来逐job重建端点；
 * 不为旁路、初始化或其他运行域伪造dirty字段。 */
int af_cp_components406_prepare(AfCpComponents406 *,uint32_t identity);
/* 仅在313C70的原12D8 copy已经完成后调用，原copy仍由调用者执行且只执行一次。
 * 只失效工作shot+920这个比较缓存；原85912E回写actual并保留后置模式清B。
 * 输出标记仅跟踪可能残留的私有Gamma，不等于原formatter/照片已消费LUT。 */
int af_cp_components406_shot_after(AfCpComponents406 *,void *actual,
    uint32_t destination,uint32_t source,size_t,uint32_t return_lr);
/* 按asset基底匹配原232FE0的真实profile；ST49另核operation+34模式。
 * matrix仍仅处理原71E41E的27项输出，单色53的原9项矩阵另行委派；
 * CC1保留原24项输出，包括BW/SE的53。错配/未知/来源丢失均保留原结果。 */
uint32_t af_cp_components406_matrix(AfCpComponents406 *,void *,uint32_t,void *,uint32_t);
uint32_t af_cp_components406_cc1(AfCpComponents406 *,void *,uint32_t,void *);
typedef uint32_t (*AfCpComponents406Matrix9)(void *,const void *);
/* 仅71D6EC单色9项copy调用站；原copy一次，三端点相等才应用唯一增量。 */
uint32_t af_cp_components406_matrix9(AfCpComponents406 *,void *,const void *,void *,uint32_t,
                                    AfCpComponents406Matrix9);
/* address必须是实际formatter原地址，host映射与address分开。 */
uint32_t af_cp_components406_gamma(AfCpComponents406 *,uint32_t,const void *,uint32_t,void *);
/* 原构造/初始化只调用一次；私有标记失败不阻断原厂调用。 */
uint32_t af_cp_components406_gamma_source(AfCpComponents406 *,const void *);
uint32_t af_cp_components406_gamma_reset(AfCpComponents406 *,const void *);
/* AA6978原copy前后有界核对，绝不在此读取全局当前配方。 */
int af_cp_components406_gamma_copy(AfCpComponents406 *,void *,const void *,size_t,
    uint32_t destination,uint32_t source,uint32_t return_lr);
int af_cp_components406_gamma_shadow(AfCpComponents406 *,AfCpGamma406Tone *);
/* 同代shadow身份及84B实际像；前后复核原copy写者，不返回内部指针。 */
int af_cp_components406_gamma_snapshot(AfCpComponents406 *,AfCpGamma406Tone *,uint8_t image[84]);
int af_cp_components406_shadow_target(AfCpGamma406Tone *,uint8_t image[84]);
/* 仅从原BEF550稳定寄存器/活动帧调用。返回0委派原selector；进入query后
 * 返回230F23或230F63，绝不重复已经执行的query/packer。saved_lr为原SP+0x24。
 * 非零返回必须最终进入cleanup；query失败仍走原230F62失败continuation。
 * 主id3只走stage0；Capture须真实scope/root来源、native+0C==11，
 * 沿原mode6/11且最终stage1；其他stage仍原委派。
 * stock/fault只清已追踪的同stage私有packed，不凭结构授LUT。 */
uint32_t af_cp_components406_grid_enter(AfCpComponents406 *,void *,void *,uint32_t *saved_lr);
uint32_t af_cp_components406_grid_leave(AfCpComponents406 *);

/* 固定ARM绑定。未编入目标配置时不可用，不接触固定地址。 */
int af_cp_components406_bind_target(void);
int af_cp_components406_prepare_target(uint32_t identity);
int af_cp_components406_shot_after_target(void *,const void *,size_t,uint32_t return_lr);
uint32_t af_cp_components406_matrix_target(void *,uint32_t,void *,uint32_t);
uint32_t af_cp_components406_cc1_target(void *,uint32_t,void *);
uint32_t af_cp_components406_matrix9_target(uint32_t,uint32_t,uint32_t,uint32_t);
uint32_t af_cp_components406_gamma_target(uint32_t,const void *,void *);
uint32_t af_cp_components406_gamma_source_target(const void *);
uint32_t af_cp_components406_gamma_reset_target(const void *);
void af_cp_components406_gamma_copy_target(void *,const void *,size_t,uint32_t);
/* 内层建立与旧BEF8E0相同的616B活动帧，尾入原BEF9AE。 */
uint32_t af_cp_components406_gamma_inner(uint32_t,const void *,void *,const void *);
uint32_t af_cp_components406_grid_enter_target(void *,void *,uint32_t *);
uint32_t af_cp_components406_grid_leave_target(void);
void af_cp_components406_grid_gate(void);
void af_cp_components406_grid_cleanup(void);
#endif
