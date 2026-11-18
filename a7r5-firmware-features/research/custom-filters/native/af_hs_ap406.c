/* 仅供匿名AP接入研究；时钟未配置时不接管私有消息。 */
#include "af_handshake.h"
#ifdef AF_RUNTIME406
#include "af_runtime.h"
extern AfRuntime af_ap_runtime;
extern int af_ap_runtime_reply(const void *,uint32_t,size_t);
#endif
typedef uint64_t (*AfClock)(void);
AfHandshake af_ap_handshake;
static AfClock clock_source;
int af_ap_hs_begin(uint64_t session,uint32_t required,uint64_t timeout,AfClock clock,void *out) {
    int result;
    if (!clock) return AF_INVALID;
    result=af_hs_begin(&af_ap_handshake,session,required,clock(),timeout,out);
    if (result==AF_OK) clock_source=clock;
    return result;
}
int af_ap_hs_receive(const void *p,uint32_t source,size_t bytes) {
    const uint8_t *tag=p;
#ifdef AF_RUNTIME406
    if (af_ap_runtime.attempted) return af_ap_runtime_reply(p,source,bytes);
#endif
    if (!clock_source || !p || source!=0x90030001u || bytes!=128 ||
        tag[0]!='A' || tag[1]!='7' || tag[2]!='P' || tag[3]!='1') return 0;
    return af_hs_client(&af_ap_handshake,p,bytes,source,clock_source());
}
int af_ap_hs_poll(void) {
    return clock_source?af_hs_poll(&af_ap_handshake,clock_source()):AF_EMPTY;
}
