/* 固定4.06独立request快照到Capture颜色构造的按值伴随；不拥有图像。 */
#ifndef AF_CP_CAPTURE_COLOR406_H
#define AF_CP_CAPTURE_COLOR406_H
#include "af_cp_input406.h"
#include "af_cp_runtime_asset406.h"
#define AF_CP_CAPTURE_COLOR406_COUNT 490u
#define AF_CP_CAPTURE_COLOR406_REQUEST 0x163f3f0u
#define AF_CP_CAPTURE_COLOR406_R_OFFSET 0x20u

typedef struct AfCpCaptureColor406 AfCpCaptureColor406;
typedef struct {
    void *context;
    /* 返回实际第4输入token及163F3C8请求ID；无资格不能默认成功。 */
    int (*request)(void *,AfCpInput406Token *,uint32_t *request_id);
    int (*thread)(void *,uint32_t *);
    /* 仅核实际R已复制的字段子集；未复制的八值不得补造。
     * 身份来自原request/R-copy事件，此处只作额外数值一致检查。 */
    int (*r_matches)(void *,uint32_t r,const AfPreset *expected);
} AfCpCaptureColor406Ports;
typedef struct {
    uint32_t a,mark,index,thread,serial,bank,generation;
} AfCpCaptureColor406Scope;
typedef struct {
    AfCpCaptureColor406Scope token;
    AfCpInput406Token input;
    uint32_t request_id,request_serial;
} AfCpCaptureColor406Write;
typedef struct {
    AfCpCaptureColor406Scope token;
    uint64_t version;
    uint32_t slot;
    const AfCpRuntimeAsset406 *asset;
    const AfPreset *preset;
} AfCpCaptureColor406View;

/* state自身、490个8B关联及两个完整运行副本全部位于同一有界heap段。
 * 配合原54880B Capture工作区时必须以真实sizeof核总量<65536。首次清零，
 * 同一CP启动期间不搬移；端口读取与原调用均不持私有guard。 */
size_t af_cp_capture_color406_bytes(void);
int af_cp_capture_color406_init(AfCpCaptureColor406 *,size_t,const AfCpCaptureColor406Ports *);
int af_cp_capture_color406_ready(const AfCpCaptureColor406 *);
int af_cp_capture_color406_a_birth(AfCpCaptureColor406 *,uint32_t a);
int af_cp_capture_color406_a_release(AfCpCaptureColor406 *,uint32_t a);
/* 原R覆盖/序列化恢复仅撤来源，保留alive A供之后真实request copy重绑。 */
int af_cp_capture_color406_a_invalidate(AfCpCaptureColor406 *,uint32_t a);
/* 原ADF128 copy前先撤销request引用；原copy/投影成功且解锁前由0x24拥有者
 * 传稳定token/asset。两个cache仍被旧A引用时返回BUSY，不覆盖、不重试。 */
int af_cp_capture_color406_request_invalidate(AfCpCaptureColor406 *);
int af_cp_capture_color406_request_publish(AfCpCaptureColor406 *,const AfCpInput406Token *,
    uint32_t request_id,const AfCpRuntimeAsset406 *);
/* 原ADD846/4596F4前后各调用一次；先撤销A旧资格，end核同request epoch、
 * ID、任务及实际R已复制字段才提交。未知/失败不沿用旧A资格。 */
int af_cp_capture_color406_r_begin(AfCpCaptureColor406 *,uint32_t a,AfCpCaptureColor406Write *);
int af_cp_capture_color406_r_end(AfCpCaptureColor406 *,const AfCpCaptureColor406Write *);
/* 每次原Capture颜色构造都登记scope，含EMPTY返回的非零serial也须end。
 * view内指针仅借到scope_end；原矩阵/CC1/packer同步读完即归还scope引用。 */
int af_cp_capture_color406_scope_begin(AfCpCaptureColor406 *,uint32_t r,AfCpCaptureColor406Scope *);
/* 原厂scope可观察真实R/线程，但不授asset；fault/过期不写输出。 */
int af_cp_capture_color406_scope_observe(AfCpCaptureColor406 *,uint32_t r,AfCpCaptureColor406Scope *);
int af_cp_capture_color406_view(AfCpCaptureColor406 *,AfCpCaptureColor406View *);
int af_cp_capture_color406_current(AfCpCaptureColor406 *,const AfCpCaptureColor406View *);
int af_cp_capture_color406_scope_end(AfCpCaptureColor406 *,const AfCpCaptureColor406Scope *);
/* 原池/生命周期重置撤销全部A和request；在途R写者或scope时粘性关闭。 */
int af_cp_capture_color406_pool_reset(AfCpCaptureColor406 *);
#endif
