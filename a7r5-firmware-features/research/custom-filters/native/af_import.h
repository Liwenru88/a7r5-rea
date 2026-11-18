/* CUBE到自包含候选的原生事务；不自带机身颜色模型或文件/设备接口。 */
#ifndef AF_IMPORT_H
#define AF_IMPORT_H
#include "af_joint_asset.h"
#include "af_joint_report.h"
#include "af_document.h"
#ifdef AF_JOINT_BASIS406
#include "af_joint_basis.h"
#endif
#define AF_IMPORT_SOURCE_MAX (4u*1024u*1024u)
#define AF_PREPARED_FILE_MAX (AF_DOCUMENT_HEADER+AF_DOCUMENT_NAME_MAX+AF_JOINT_ASSET_MAX_BYTES)
/* 电脑配方或现有导出文件：不拟合，不改变报告；work/asset独立驻留。
 * 只允许有效纯参数或当前CP能消费的converter2/AJR2；拒绝墓碑与旧AJR1。
 * 成功文档借用raw；摘要仅证明完整性，不认证提供者或模型精度。 */
int af_import_prepared(const void *raw,size_t bytes,AfJointAssetDecodeWork *,AfJointAsset *,AfDocument *);
typedef struct {
    AfPreset initial;
    AfFitReport report;
    AfJointFit fit;
    AfGridReport validation;
    uint32_t name_bytes;
    char name[64];
    uint8_t image[AF_JOINT_ASSET_BYTES];
} AfImportCandidate;
typedef struct {
    AfJointWork fit;
    AfJointRecipe recipe;
    AfJointReportWork report;
    AfImportCandidate candidate;
} AfImportWork;
typedef struct {
    const char *source;size_t source_bytes;
    const char *name;size_t name_bytes;
    const AfJointModel *model;
    AfPreset initial;
    const AfJointRecipe *seed;
    const AfGridSample *training;size_t training_count;
    const AfGridSample *validation;size_t validation_count;
    AfJointOptions options;
} AfImportRequest;
/* 可让出给原UI事件轮询的转换工作状态；首次使用清零，非存储/消息ABI。
 * source、样本、work、storage和model.context由唯一拥有者保持到结束。
 * 模型/seed/请求参数与名称在start复制，源内容摘要在完成前再次核对。 */
typedef struct {
    AfImportRequest request;
    AfJointModel model;
    AfJointRecipe seed;
    AfCube cube;
#ifdef AF_JOINT_BASIS406
    AfJointBasisState search;
#else
    AfJointState search;
#endif
    AfImportWork *work;
    AfImportCandidate *output;
    AfGridProgress progress;
    void *context;
    uint32_t phase,validated,total;
    uint8_t source_sha256[32];
    char name[64];
} AfImportState;
size_t af_import_state_bytes(void);
/* MORE表示工作尚未完成，step预算1..64，完成前不发布候选。
 * 不创建线程，不访问文件；取消在批次及模型调用间检查。 */
int af_import_start(AfImportState *,const AfImportRequest *,float *,size_t,
                    AfImportWork *,AfImportCandidate *,AfGridProgress,void *);
int af_import_step(AfImportState *,uint32_t budget);
/* 唯一拥有者在任务期间固定全部输入及模型context；模型须明确绑定initial的基底、
 * 八项参考参数和seed。声明本身不是标定证据；不得以合成模型作为默认回退。
 * 模型只允许声明本次一个基底；验证色不得与训练色重合，必须含灰阶/肤色标签。
 * storage为24～107811个float的独立暂存区；work为独立有界工作区。
 * 任意取消/错误不发布候选。进度总量=evaluations+validation_count+2，
 * 最后回调仍可取消；进度不是实测耗时百分比。不改变目录/显示/存储。
 */
int af_import_cube(const AfImportRequest *,float *storage,size_t capacity_floats,
                    AfImportWork *,AfImportCandidate *,AfGridProgress,void *);
/* 成功只返回借用候选name/image的文档视图，候选须保持不可变。
 * 当前schema仅供研究保存；返回成功不等于实际机身模型、菜单或CP可用。 */
int af_import_document(const AfImportCandidate *,AfDocument *);
/* 对已完整恢复的文档再核对联合载荷、模型/基底和摘要。
 * 只解码研究配方；不确认真实CP版本绑定或授予成像应用许可。 */
int af_import_asset(const AfDocument *,AfJointAsset *);
#endif
