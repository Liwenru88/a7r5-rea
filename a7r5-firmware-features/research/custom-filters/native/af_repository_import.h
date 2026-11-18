/* IMPORT双入口的单拥有者分批胶合；复用媒体、可选转换与既有持久化。 */
#ifndef AF_REPOSITORY_IMPORT_H
#define AF_REPOSITORY_IMPORT_H
#include "af_repository.h"
enum AfRepositoryImportPhase {
    AF_REPOSITORY_IMPORT_IDLE=0, AF_REPOSITORY_IMPORT_MEDIA=1,
    AF_REPOSITORY_IMPORT_FITTING=2, AF_REPOSITORY_IMPORT_COMMIT=3,
    AF_REPOSITORY_IMPORT_FINISHED=4
};
typedef struct {
    AfRepository *repository;
    AfApManage *manager;
    AfApManageJob job;
    AfRepositoryImport input;
    AfMediaProvider provider;
    AfMediaList listing;
    AfMediaSource expected;
    AfImportRequest parameters;
    AfJointModel model;
    AfJointRecipe seed;
    AfGridSample training[AF_JOINT_SAMPLES],validation[AF_GRID_SAMPLES];
    AfImportState conversion;
    uint8_t candidate_sha256[32];
    AfJointAssetDecodeWork prepared_work;
    AfJointAsset prepared_asset;
    uint32_t phase,fitting,kind;
    int last_result;
} AfRepositoryImportTask;
size_t af_repository_import_task_bytes(void);
/* 首次使用须清零；活动时init返回BUSY。该状态较大，调用者应驻留分配而非原UI栈。
 * 活动状态含自指针，不能搬移、复制、重新绑定目录或提前释放任何工作区。 */
int af_repository_import_init(AfRepositoryImportTask *);
int af_repository_import_busy(const AfRepositoryImportTask *);
/* take一个排队IMPORT后保持RUNNING。复制同代列表及选中文件bytes/SHA；
 * CUBE另复制模型声明、seed、全部样本，配方不要求parameters/拟合工作区。
 * 固定选项及首次选中文件的bytes/SHA；expected不得缺省。source/name/initial改由
 * 本任务的文件副本和管理请求提供，不使用parameters中的路径或外部名称。
 * directory为服务显式借用fd，必须维持到任务结束；model.context仍由可信拥有者固定。
 * task、source、cube、work、candidate与仓库/管理器/输入均须独立。
 * C01..06须有明确overwrite确认，只写独立overlay，不修改原生六槽数据。 */
int af_repository_import_start(AfRepositoryImportTask *,AfRepository *,AfApManage *,
                               const AfRepositoryImport *,const AfMediaSource *expected);
/* 预算1..64；MORE让出原UI事件轮询。首轮沿用有界双读媒体和CUBE解析，不分割文件I/O；
 * 后续每轮最多budget个拟合候选或验证色，无线程；配方完整校验后跳过拟合。
 * 两入口完成候选后均另一次poll才进入提交。
 * 取消、首选SHA变化、源内存变化、槽快照陈旧或模型错误均不提交；
 * 持久化成功及labels回读后才finish，发布后不确定沿用既有恢复契约。 */
int af_repository_import_poll(AfRepositoryImportTask *,uint32_t budget);
#endif
