/* 原三个C4 owner与值复制队列的固定任务接入；不改变原分组发布。 */
#ifndef AF_CP_JOBS406_H
#define AF_CP_JOBS406_H
#include "af_cp_native_bank406.h"
#define AF_CP_JOBS406_COUNT 3u
#define AF_CP_JOBS406_SOURCES 2u
#define AF_CP_JOBS406_C4_BYTES 0xc4u
#define AF_CP_JOBS406_ALIAS_OFFSET 0xe18u
#define AF_CP_JOBS406_STACK_BYTES 0xc0u
enum AfCpJob406State {AF_CP_JOB406_FREE=0,AF_CP_JOB406_BUILDING=1,AF_CP_JOB406_CAPTURED=2,
    AF_CP_JOB406_QUEUING=3,AF_CP_JOB406_QUEUED=4,AF_CP_JOB406_RUNNING=5,AF_CP_JOB406_PINNED=6};
typedef struct {
    uint32_t ticket,identity,source_index,task,queue,c4_address,original_source,prefix_address;
    const uint8_t *prefix;
    const AfCpRuntimeAsset406 *asset;
    AfCpInput406Token input;
    AfCpNativeLease406 lease;
} AfCpJobs406View;
typedef struct {
    void *context;
    AfCpNativeBanks406 *banks;
    void *(*map)(void *,uint32_t,size_t);
    int (*read_input)(void *,uint32_t,AfCpInput406Token *);
    int (*borrow_locked)(void *,AfCpNativeBanks406 *,const AfCpInput406Token *,uint32_t,AfCpNativeLease406 *);
    int (*release)(void *,AfCpNativeBanks406 *,const AfCpNativeLease406 *);
    /* 只读sticky资格位；不得取锁、查询任务或重读可变原源。 */
    int (*allowed)(void *);
    void (*copy)(void *,void *,const void *,size_t);
    int (*task)(void *,uint32_t *,uint32_t *);
    void (*invoke)(void *,uint32_t,uint32_t);
    void (*complete)(void *,uint32_t);
    uint32_t worker_address[AF_CP_JOBS406_COUNT],completion_address,after_native_lr;
    uint32_t prefix_address[AF_CP_JOBS406_COUNT][AF_CP_JOBS406_SOURCES];
} AfCpJobs406Config;
typedef struct {
    uint32_t state,next_ticket,ticket,message_address,completion_seen,executed;
    AfCpJobs406View view;
} AfCpJob406;
typedef struct AfCpJobs406 {
    uint32_t magic,fault;
    AfCpJobs406Config config;
    AfCpJob406 jobs[AF_CP_JOBS406_COUNT];
    _Alignas(4) uint8_t prefixes[AF_CP_JOBS406_COUNT][AF_CP_JOBS406_SOURCES][AF_CP_INPUT406_COPY_BYTES];
} AfCpJobs406;
/* stack是原5C353C当前SP开始的明确可读映射，address为其32位原地址。
 * 调用者须保存完整C0字节活动帧；不得以r1/n猜测或向前探测未知源。 */
typedef struct {void *stack;size_t bytes;uint32_t address;} AfCpJobs406QueueFrame;
size_t af_cp_jobs406_bytes(void);
/* 仅boot零对象配置一次；无活动期reset、默认成功bank或自动释放未知借用。 */
int af_cp_jobs406_init(AfCpJobs406 *,const AfCpJobs406Config *);
/* 调用者持原0x24锁。只在已证原三个C4 memcpy调用上使用；任何资格失败仍copy一次。
 * 仅mother192B070→A、secondary165D820→B。clone只重定位C4前三word，第三为E18。 */
int af_cp_jobs406_c4_copy_locked(AfCpJobs406 *,void *,uint32_t,const void *,uint32_t,size_t,uint32_t);
/* 原三ARM memcpy的首段/末段；绝不调用锁或GetTaskID，所有原copy仍委派一次。 */
int af_cp_jobs406_queue_copy(AfCpJobs406 *,void *,const void *,size_t,uint32_t,const AfCpJobs406QueueFrame *);
/* 已识别worker的资格/任务/状态失败仍invoke原work一次；未知借用固定且不计成功。
 * generic接口无法信任未初始化config；真实target对已知wrapper另有固定原入口回退。 */
int af_cp_jobs406_run(AfCpJobs406 *,uint32_t identity);
/* 正常wrapped完成只记录到达；work返回后才release。reject先结束本代再原callback。 */
int af_cp_jobs406_complete(AfCpJobs406 *,uint32_t identity,uint32_t return_lr);
/* 唯一真实worker线程内的独立快照；前后组件复核同ticket，不用global activeView。
 * 指针只借到同次worker返回；current不是允许调用者跨worker保存指针的独立租约。 */
int af_cp_jobs406_current_view(AfCpJobs406 *,uint32_t identity,AfCpJobs406View *);
int af_cp_jobs406_current(AfCpJobs406 *,const AfCpJobs406View *);

/* 实际ARM绑定只接受真实banks；宿主不访问固定地址且target保持不可用。 */
int af_cp_jobs406_bind_target(AfCpNativeBanks406 *);
AfCpJobs406 *af_cp_jobs406_target_state(void);
int af_cp_jobs406_current_target(uint32_t identity,AfCpJobs406View *);
int af_cp_jobs406_current_matches_target(const AfCpJobs406View *);
void af_cp_jobs406_c4_target(void *,const void *,size_t,uint32_t);
void af_cp_jobs406_queue_target(void *,const void *,size_t,uint32_t,const void *);
void af_cp_jobs406_worker_target(uint32_t);
void af_cp_jobs406_completion_target(uint32_t,uint32_t);
void af_cp_jobs406_worker2(void);
void af_cp_jobs406_worker3(void);
void af_cp_jobs406_worker6(void);
void af_cp_jobs406_completion(void);
void af_cp_jobs406_invoke_native(uint32_t);
void af_cp_jobs406_after_native(void);
#endif
