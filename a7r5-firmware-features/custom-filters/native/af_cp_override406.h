/* 同包4.06原快照的纯参数副本覆盖；不代表照片已经生效。 */
#ifndef AF_CP_OVERRIDE406_H
#define AF_CP_OVERRIDE406_H
#include "af_cp406_state.h"
#if defined(AF_CP_CAPTURE_COPIES406) && !defined(AF_CP_CAPTURE_INPUT406)
#error "copy capture requires the paired input observer"
#endif

enum AfCpOverride406Mode {
    AF_CP_OVERRIDE_NATIVE=0,
    AF_CP_OVERRIDE_USER=1,
    AF_CP_OVERRIDE_FACTORY_PENDING=2
};
typedef struct {
    uint32_t mode,slot;
    AfPreset preset;
    uint64_t version;
} AfCpOverride406;

/* 以下叶函数由同一原0x24互斥串行调用；state须零初始化且由单一模块拥有。
 * 发布只改私有对象和原update marker，绝不改原157aa10。
 * version与配方同锁提交，仅接受非零递增值；原厂退出也消费同一版本序列。
 * 所有输入/输出内存须独立；无效或陈旧输入不发布。仅接受纯参数。 */
int af_cp_override406_publish_locked(AfCpOverride406 *,uint64_t,uint32_t,const AfPreset *,uint8_t *);
int af_cp_override406_release_locked(AfCpOverride406 *,uint64_t,uint8_t *);
/* 必须在原memcpy(dst,157aa10,0xdbc)之后、原锁释放之前调用。
 * 仅覆盖dst九字段；factory pending在原九字段同值时退出，不证明消息队列排空。 */
int af_cp_override406_snapshot_locked(AfCpOverride406 *,const void *native_state,
                                      void *destination,size_t);
/* 校验完整118B函数；旧绝对gate/new carve分支各有明确唯一替换窗口。 */
int af_cp_override406_hook_matches(const void *,size_t,uint32_t thumb_gate);

/* 研究目标绑定；宿主构建永远不访问固定地址并保持不可就绪。
 * ready只有精确已安装gate且原try-lock/release均成功时才为1。
 * prepare/release失败不是原厂/照片应用成功；unlock失败后必须冻结会话。 */
int af_cp_override406_ready(void);
int af_cp_override406_prepare(uint64_t,uint32_t,const AfPreset *);
int af_cp_override406_release(uint64_t);
/* 只读粘性故障位；不重读/否定已经独立借用的旧prefix。 */
int af_cp_override406_faulted(void);
void af_cp_override406_snapshot_target(void *,size_t);
void af_cp_override406_snapshot_gate(void);
#ifdef AF_CP_CAPTURE_INPUT406
struct AfCpInput406;
struct AfCpInput406Token;
typedef void (*AfCpSnapshotCopy406)(void *,const void *,size_t);
/* 原0x24锁下的实际复制胶合。无效追踪不阻断原copy；失败关闭该次来源资格。
 * logical_destination只供已证原地址，宿主可显式分离逻辑键与实际可读缓冲。
 * copy必须提供原memcpy ABI；状态、源、目的及追踪对象互相独立。
 * state=NULL是明确的故障回退：仍执行原copy、撤销该目的资格，返回AF_IO。 */
int af_cp_override406_snapshot_copy_locked(AfCpOverride406 *,const void *,void *,size_t,
    struct AfCpInput406 *,uint32_t logical_destination,AfCpSnapshotCopy406);
struct AfCpInput406 *af_cp_override406_input_state(void);
/* 成像侧只能经此资格读取；故障前后检查，失败不写输出。
 * raw sidecar只证明原复制历史，不能绕过本入口用于私有成像。 */
int af_cp_override406_read_input(uint32_t,struct AfCpInput406Token *);
void af_cp_override406_snapshot_copy_target(void *,const void *,size_t);
void af_cp_override406_snapshot_copy_gate(void);
#ifdef AF_CP_CAPTURE406
void af_cp_override406_request_copy_target(void *,const void *,size_t);
#endif
#endif
#endif
