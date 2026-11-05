/* 单一通信任务拥有；仅协商兼容性，不发布参数银行或帧回执。 */
#ifndef AF_RUNTIME_H
#define AF_RUNTIME_H
#include "af_handshake.h"
typedef struct {
    int (*nonce)(uint64_t *);
    int (*clock_ms)(uint64_t *);
    int (*send)(const void *,size_t);
    int (*receive)(uint32_t,void **,int);
} AfRuntimePorts;
typedef struct {
    AfHandshake hello;
    uint64_t last_now;
    uint32_t attempted,fault;
} AfRuntime;
enum { AF_RT_NONCE=1,AF_RT_CLOCK=2,AF_RT_SEND=3,AF_RT_RECEIVE=4,AF_RT_CONFIG=5,AF_RT_RECIPE=6 };
int af_rt_start(AfRuntime *,const AfRuntimePorts *);
int af_rt_poll(AfRuntime *,const AfRuntimePorts *);
/* 返回1才有消息；空接收必须跳回循环，不能继续原指针解引用。 */
int af_rt_next(AfRuntime *,const AfRuntimePorts *,uint32_t,void **);
/* limit为0..50毫秒或-1沿用原等待。显式有界轮询可推进完整配方回执截止；
 * 空队列仍归原循环，未创建线程、重发或伪造消息。 */
int af_rt_next_bounded(AfRuntime *,const AfRuntimePorts *,uint32_t,void **,int limit);
int af_rt_reply(AfRuntime *,const AfRuntimePorts *,const void *,uint32_t,size_t);
#endif
