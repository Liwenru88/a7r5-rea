#include "af_handshake.h"
static int owned(const void *input,size_t n) {
    const uint8_t *p=input;
    return p && n==128 && p[0]=='A' && p[1]=='7' && p[2]=='P' && p[3]=='1';
}
int af_hs_begin(AfHandshake *s,uint64_t session,uint32_t required,uint64_t now,uint64_t timeout,void *out) {
    AfApplyPacket p={0};size_t written;
    if (!s || !session || !timeout || now>UINT64_MAX-timeout || !out) return AF_INVALID;
    if (s->state==1 || s->state==2) return AF_BUSY;
    if (s->state && session==s->session) return AF_STALE;
    p.operation=AF_APPLY_HELLO;p.session=session;p.required=required;
    if (af_apply_packet_encode(&p,out,128,&written)!=AF_OK) return AF_INVALID;
    s->session=session;s->deadline=now+timeout;s->required=required;s->state=1;
    return AF_OK;
}
int af_hs_server_init(AfHandshake *s,uint32_t required) {
    if (!s || !(required&AF_APPLY_ALL) || (required&~AF_APPLY_PROTOCOL_ALLOWED) ||
        ((required&(AF_APPLY_CAP_USER20|AF_APPLY_CAP_SECTOR_MATRIX))&&!(required&AF_APPLY_CAP_FULL_RECIPE))) return AF_INVALID;
    /* 显式重建入口；实际集成须先证明所有连接/银行/帧均已退役。 */
    s->session=s->deadline=0;s->required=required;s->state=4;return AF_OK;
}
int af_hs_poll(AfHandshake *s,uint64_t now) {
    if (!s) return AF_INVALID;
    if (s->state==1 && now>=s->deadline) s->state=3;
    if (s->state==2) return AF_OK;
    return s->state==1?AF_BUSY:(s->state==3?AF_STALE:AF_EMPTY);
}
int af_hs_server(AfHandshake *s,const void *input,size_t n,uint32_t source,void *out,size_t capacity,size_t *bytes) {
    AfApplyPacket p;
    if (bytes) *bytes=0;
    if (!s || (s->state!=4 && s->state!=5) || source!=0x80020002u || !owned(input,n)) return 0;
    if (!out || !bytes || capacity<128 || af_apply_packet_decode(input,n,&p)!=AF_OK ||
        p.operation!=AF_APPLY_HELLO || p.required!=s->required || (s->session && s->session!=p.session)) return 1;
    for (size_t i=0;i<128;++i) ((uint8_t *)out)[i]=((const uint8_t *)input)[i];
    s->session=p.session;s->state=5;*bytes=128;return 1;
}
int af_hs_client(AfHandshake *s,const void *input,size_t n,uint32_t source,uint64_t now) {
    AfApplyPacket p;
    if (!s || !s->state || source!=0x90030001u || !owned(input,n)) return 0;
    if (s->state!=1) return 1;
    if (af_hs_poll(s,now)!=AF_BUSY) return 1;
    if (af_apply_packet_decode(input,n,&p)==AF_OK && p.operation==AF_APPLY_HELLO &&
        p.session==s->session && p.required==s->required) s->state=2;
    return 1;
}
