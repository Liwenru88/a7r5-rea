/* 管理动作到真实文件事务；目录fd由明确的运行环境提供，不探测机身路径。 */
#ifndef AF_REPOSITORY_H
#define AF_REPOSITORY_H
#include "af_posix.h"
#include "af_labels_store.h"
#include "af_ap_manage.h"
#include "af_import.h"
#include "af_media.h"
#define AF_REPOSITORY_NAMESPACE "A7LOOKS1"
#define AF_REPOSITORY_RESERVE (1024u*1024u)
#define AF_REPOSITORY_PARTIAL 2
typedef struct {
    AfPosix posix;
    AfStoreIo io;
    AfStore stores[AF_USERS];
    AfStoreBuffers buffers;
    AfCatalog *catalog;
    AfLabels *labels;
    uint32_t schema,ready_mask,error_mask;
    int status[AF_USERS];
    int owner_fd,opened;
} AfRepository;
typedef struct {
    int directory;
    const AfMediaList *listing;
    void *source;size_t source_capacity;
    const AfImportRequest *parameters;
    float *cube_storage;size_t cube_capacity;
    AfImportWork *work;
    AfImportCandidate *candidate;
    /* 非NULL使用原生只读提供者；此时directory必须为-1，context不得提前释放。 */
    const AfMediaProvider *provider;
} AfRepositoryImport;
static inline int af_repository_import_read(const AfRepositoryImport *i,const AfMediaList *list,
    uint32_t index,AfMediaSource *out,AfGridProgress progress,void *context){
    if(i->provider){
        if(i->directory!=-1||!af_media_provider_valid(i->provider))return AF_INVALID;
        return i->provider->read(i->provider->context,list,index,i->source,i->source_capacity,out,progress,context);
    }
    return af_media_read(i->directory,list,index,i->source,i->source_capacity,out,progress,context);
}
size_t af_repository_bytes(void);
/* 新namespace必须本次mkdir创建；既有目录须有完全匹配的基线/版本标记。
 * 不创建/覆盖未知目录或文件，不清理遗留.new；独占锁保持至close。
 * repo首次调用前须清零，catalog须为空，buffers由调用者拥有；坏槽隔离，返回PARTIAL且有效槽仍可用。
 * 相机路径/真实介质未获准入时，调用方不得在机身调用；本接口本身不查设备。 */
int af_repository_open(AfRepository *,int parent_directory,int create,uint32_t schema,
                       size_t max_payload,const AfStoreBuffers *,AfCatalog *,AfLabels *);
/* 显式区分仓库标记与文档允许的schema；不改STORE.ID或既有AFR记录。
 * marker_schema只核验/创建命名空间标记；document_schema交给各槽AFD1解码。
 * 可在原marker=0仓库中读取纯参数与声明的LUT格式；不支持文档仍逐槽隔离。
 * 原open仍将同一schema同时传给两者，保持原有拒绝与磁盘格式语义。 */
int af_repository_open_documents(AfRepository *,int parent_directory,int create,
                       uint32_t marker_schema,uint32_t document_schema,size_t max_payload,
                       const AfStoreBuffers *,AfCatalog *,AfLabels *);
int af_repository_close(AfRepository *);
/* 显式恢复会丢弃该槽未保存工作；不作为失败后的自动重试。 */
int af_repository_recover(AfRepository *,uint32_t slot);
/* 同一UI拥有者串行pump一个已排队管理请求，无后台线程/跨线程承诺。
 * SAVE/COPY/CREATE/CLEAR/RENAME复用persist；同步IMPORT只处理显式模型CUBE，
 * 配方文件必须走af_repository_import_start/poll，不误当CUBE或默认拟合回退。
 * 发布前commit_begin核对快照/取消；保存和成像回执分开。 */
int af_repository_execute(AfRepository *,AfApManage *,const AfRepositoryImport *);
/* 已保存完整文档导出；library为显式普通目录fd，不能等于机内仓库目录。
 * scratch须与仓库/manager/catalog/labels及三存储缓冲独立，容量至少完整AFD1。
 * 固定Cxx_G<16位十六进制保存代号>.a7filter，O_EXCL保证绝不覆盖既有名称。
 * 完整写入、文件同步关闭、独立回读、目录同步后才成功；目录可先看到不完整文件。
 * 创建后任一失败保留本次文件并返回UNCERTAIN，不自动删除/重试，不改变body记录。
 * 读者须校验完整长度/字段；AFD1纯参数格式没有全文件CRC。 */
int af_repository_export(AfRepository *,AfApManage *,int library,void *scratch,size_t capacity);
#endif
