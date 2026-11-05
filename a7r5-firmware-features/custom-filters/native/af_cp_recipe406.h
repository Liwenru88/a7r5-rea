/* 真实CP消息拥有者的完整配方桥；不安装gate，不授予任何像素消费者资格。 */
#ifndef AF_CP_RECIPE406_H
#define AF_CP_RECIPE406_H
#include "af_handshake.h"
#include "af_recipe_transport.h"

typedef void *(*AfCpRecipe406Allocate)(void *,size_t);
typedef void (*AfCpRecipe406Free)(void *,void *);
typedef int (*AfCpRecipe406Send)(void *,const void *,size_t,uint32_t);
/* 单一原消息任务同步调用一次。AF_OK仅表示消费者已接受软件prepared对象，
 * 该消费者必须保留lease，并在最后引用结束后调用release；不代表取景/JPG完成。
 * AF_BUSY表示等待显式finish，不自动重调；AF_IO表示提交结果未知，固定拥有权并关闭
 * 后续私有输入，不发送假拒绝ACK。其他负值须保证未应用且不再借用对象。 */
typedef int (*AfCpRecipe406Consumer)(void *,const AfRecipeOwned *,const AfRecipeLease *);
typedef struct {
    AfHandshake *handshake;
    uint64_t *input_version;
    uint32_t *input_slot,*input_fault;
    AfCpRecipe406Allocate allocate;
    AfCpRecipe406Free release;
    AfCpRecipe406Send send;
    AfCpRecipe406Consumer consume;
    void *context;
} AfCpRecipe406Config;

size_t af_cp_recipe406_owner_bytes(void);
/* 对象在握手配置之前由实际堆分配器显式建立；没有默认分配器或成功消费者。
 * 这些外部指针与context须驻留，拥有者地址固定；所有API由同一消息任务串行调用。 */
int af_cp_recipe406_bind(const AfCpRecipe406Config *);
/* 仅未配置握手且未开始接收时允许撤销；已绑定会话不可重置、换会话或猜测排空。 */
int af_cp_recipe406_unbind(void);
int af_cp_recipe406_ready(const AfHandshake *);
/* 与kind0/NATIVE共用版本屏障；成功BEGIN即消耗版本，失败也不得重放。 */
uint64_t af_cp_recipe406_seen_version(void);
/* 分片接收或消费者待决时，原参数入口须返回BUSY，不能并行替换输入。 */
int af_cp_recipe406_busy(void);
#ifdef AF_CP_NATIVE406
/* 仅完整校验的显式NATIVE使用：同会话USER20、更高输入/已见版本、无fault且
 * 无已take/pending对象时取消未提交接收；保留seen_version与旧active。
 * 无incoming返回EMPTY；未知提交返回BUSY/IO，绝不猜测归还租约或回滚。 */
int af_cp_recipe406_cancel_partial(uint64_t session,uint64_t next_version);
#endif
/* 返回1表示明确的A7R1私有消息已消费，0表示交回原厂分流。
 * 仅接受0x80020002来源；完整128B、同会话HELLO和FULL_RECIPE协商缺一不可。
 * 全部校验完成才调用消费者；回执只表示软件prepared决定。 */
int af_cp_recipe406_receive(const void *,uint32_t,size_t);
int af_cp_recipe406_pending(AfRecipeLease *,const AfRecipeOwned **);
/* 不能对未知提交自动重试。AF_IO固定待决并置fault，不产生回滚或拒绝ACK。
 * 发送ACK失败返回IO，但已确定的prepared决定不回滚，也不自动重发。 */
int af_cp_recipe406_finish(int decision);
int af_cp_recipe406_release(const AfRecipeLease *);
int af_cp_recipe406_last_result(void);
int af_cp_recipe406_last_send(void);
#endif
