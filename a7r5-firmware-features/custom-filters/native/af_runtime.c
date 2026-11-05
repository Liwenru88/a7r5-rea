#include "af_runtime.h"
static int fail(AfRuntime *s,uint32_t fault) {
    if (!s->fault) s->fault=fault;
    s->hello.state=3;
    return AF_INVALID;
}
int af_rt_poll(AfRuntime *s,const AfRuntimePorts *p) {
    uint64_t now;
    if (!s || !s->attempted) return AF_INVALID;
    if (s->fault) return AF_INVALID;
    if (!p || !p->clock_ms) return fail(s,AF_RT_CLOCK);
    if (p->clock_ms(&now) || now<s->last_now) return fail(s,AF_RT_CLOCK);
    s->last_now=now;
    return af_hs_poll(&s->hello,now);
}
int af_rt_start(AfRuntime *s,const AfRuntimePorts *p) {
    uint64_t session=0,now=0;
    uint8_t packet[128];
    if (!s || !p) return AF_INVALID;
    if (s->attempted) return AF_BUSY;
    s->attempted=1;
    if (!p->nonce || !p->clock_ms || !p->send || !p->receive) return fail(s,AF_RT_CONFIG);
    if (p->nonce(&session) || !session) return fail(s,AF_RT_NONCE);
    if (p->clock_ms(&now)) return fail(s,AF_RT_CLOCK);
    s->last_now=now;
    if (af_hs_begin(&s->hello,session,AF_APPLY_PROTOCOL_REQUIRED,now,1000,packet)!=AF_OK)
        return fail(s,AF_RT_CLOCK);
    if (p->send(packet,sizeof(packet))) return fail(s,AF_RT_SEND);
    return AF_OK;
}
int af_rt_next_bounded(AfRuntime *s,const AfRuntimePorts *p,uint32_t queue,void **out,int limit) {
    int wait=limit,result;
    if (!s || !p || !p->receive || !out || queue!=0x80020002u || limit< -1 || limit>50) return 0;
    if (!s->attempted) (void)af_rt_start(s,p);
    if (!s->fault) (void)af_rt_poll(s,p);
    if (!s->fault && s->hello.state==1) {
        uint64_t left=s->hello.deadline-s->last_now;
        int handshake_wait=(int)(left<50?left:50);
        if(wait<0 || handshake_wait<wait)wait=handshake_wait;
    }
    *out=0;
    result=p->receive(queue,out,wait);
    if (!s->fault) (void)af_rt_poll(s,p);
    /* 非空输出仍归原消息路径拥有，不因协议故障自行释放或丢弃。 */
    if (*out) {
        if (result) (void)fail(s,AF_RT_RECEIVE);
        return 1;
    }
    /* -1022是原OSAL空队列/超时结果；其他错误终止私有握手，不自动重试。 */
    if (result!=-1022 || wait<0) (void)fail(s,AF_RT_RECEIVE);
    return 0;
}
int af_rt_next(AfRuntime *s,const AfRuntimePorts *p,uint32_t queue,void **out) {
    return af_rt_next_bounded(s,p,queue,out,-1);
}
int af_rt_reply(AfRuntime *s,const AfRuntimePorts *p,const void *raw,uint32_t source,size_t n) {
    const uint8_t *b=raw;
    if (!s || !s->attempted || !b || source!=0x90030001u || n!=128 ||
        b[0]!='A' || b[1]!='7' || b[2]!='P' || b[3]!='1') return 0;
    if (!s->fault) (void)af_rt_poll(s,p);
    if (!s->fault) (void)af_hs_client(&s->hello,raw,n,source,s->last_now);
    return 1;
}
