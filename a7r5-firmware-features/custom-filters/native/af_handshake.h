/* 仅确认私有入口兼容性；不确认银行已应用，实际时钟/启动会话仍须接入。 */
#ifndef AF_HANDSHAKE_H
#define AF_HANDSHAKE_H
#include "af_apply.h"
typedef struct {
    uint64_t session,deadline;
    uint32_t required,state;
} AfHandshake;
/* state：0未配置，1等待，2兼容确认，3已过期，4服务端未绑定，5服务端已绑定。
 * 单一拥有者串行调用。会话由调用者保证跨重建唯一，超时使用单调时钟同一单位。 */
int af_hs_begin(AfHandshake *,uint64_t,uint32_t,uint64_t now,uint64_t timeout,void *packet128);
int af_hs_server_init(AfHandshake *,uint32_t required);
/* 即使没有回复也必须由事件循环轮询；实际时钟/轮询尚未绑定时不能启用产品功能。 */
int af_hs_poll(AfHandshake *,uint64_t now);
/* 返回0委派原通路、1已处理；坏私有包也消费但不回复。输出范围独立，bytes总会初始化0。 */
int af_hs_server(AfHandshake *,const void *,size_t,uint32_t source,void *,size_t,size_t *bytes);
int af_hs_client(AfHandshake *,const void *,size_t,uint32_t source,uint64_t now);
#endif
