/* 源构建身份用于兼容检查，不是远端认证或运行映像测量。 */
#include "af_apply.h"
static const uint8_t builds[64]={
    0xd1,0x59,0x33,0xce,0xb5,0xff,0x9a,0xd0,0xb4,0xf7,0x89,0xcb,0xab,0xd6,0xff,0x0a,
    0x51,0x52,0x64,0x72,0xdd,0x35,0xc9,0x0d,0xb9,0x71,0x96,0xdd,0x22,0x78,0x20,0xe9,
    0x18,0xb2,0x65,0xc5,0x89,0xeb,0x42,0x01,0xd3,0xb3,0x68,0x08,0x57,0xd8,0x97,0xb6,
    0x93,0xd0,0x6c,0x6d,0xd4,0x91,0xd7,0x95,0xdb,0xb3,0xa6,0x16,0xd6,0x18,0x2e,0x97
};
static uint64_t get(const uint8_t *p,unsigned n) {
    /* 调用点固定读取2/4/8字节；避免Thumb紧凑构建依赖64位变量移位helper。 */
    uint32_t low=0,high=0;
    for (unsigned i=0;i<n;++i) {
        if (i<4) low|=(uint32_t)p[i]<<(8*i);
        else high|=(uint32_t)p[i]<<(8*(i-4));
    }
    return (uint64_t)low|((uint64_t)high<<32);
}
static void put(uint8_t *p,uint64_t v,unsigned n) {
    for (unsigned i=0;i<n;++i) p[i]=(uint8_t)(v>>(8*i));
}
static uint32_t crc(const uint8_t *p,size_t n) {
    uint32_t c=UINT32_MAX;
    for (size_t i=0;i<n;++i) { c^=p[i];for (unsigned j=0;j<8;++j) c=(c>>1)^(0xedb88320u&(0u-(c&1u))); }
    return ~c;
}
static int packet_valid(const AfApplyPacket *p) {
    if (!p || !p->session || !(p->required&AF_APPLY_ALL) ||
        (p->required&~AF_APPLY_PROTOCOL_ALLOWED) ||
        ((p->required&(AF_APPLY_CAP_USER20|AF_APPLY_CAP_SECTOR_MATRIX))&&!(p->required&AF_APPLY_CAP_FULL_RECIPE))) return 0;
    if (p->operation==AF_APPLY_HELLO) {
        const uint8_t *raw=(const uint8_t *)&p->preset;
        if (p->slot || p->version) return 0;
        for (size_t i=0;i<sizeof(p->preset);++i) if (raw[i]) return 0;
        return 1;
    }
    if (p->operation==AF_APPLY_NATIVE) {
        const uint8_t *raw=(const uint8_t *)&p->preset;
        if (!(p->required&AF_APPLY_CAP_SNAPSHOT_OVERLAY) || p->slot || !p->version) return 0;
        for (size_t i=0;i<sizeof(p->preset);++i) if (raw[i]) return 0;
        return 1;
    }
    return p->operation==AF_APPLY_PRESET && p->slot<=AF_USERS &&
        (p->slot>=1 || (p->required&AF_APPLY_CAP_FACTORY_RESTORE)) && p->version &&
        !p->preset.kind && af_validate(&p->preset)==AF_OK;
}
int af_apply_packet_encode(const AfApplyPacket *p,void *output,size_t capacity,size_t *written) {
    uint8_t raw[AF_APPLY_PACKET_BYTES]={0};
    if (!packet_valid(p) || !output || !written || capacity<sizeof(raw)) return AF_INVALID;
    raw[0]='A';raw[1]='7';raw[2]='P';raw[3]='1';put(raw+4,1,2);
    put(raw+6,p->operation,2);put(raw+8,sizeof(raw),4);put(raw+12,p->required,4);
    put(raw+16,p->session,8);put(raw+24,p->version,8);put(raw+32,p->slot,4);
    raw[36]=p->preset.base;raw[37]=p->preset.kind;
    for (unsigned i=0;i<8;++i) raw[38+i]=(uint8_t)p->preset.params[i];
    for (unsigned i=0;i<64;++i) raw[48+i]=builds[i];
    put(raw+112,1,4);put(raw+124,crc(raw,124),4);
    for (size_t i=0;i<sizeof(raw);++i) ((uint8_t *)output)[i]=raw[i];
    *written=sizeof(raw);return AF_OK;
}
int af_apply_packet_decode(const void *input,size_t bytes,AfApplyPacket *output) {
    const uint8_t *p=input;
    AfApplyPacket next={0};
    if (!p || !output || bytes!=AF_APPLY_PACKET_BYTES || p[0]!='A' || p[1]!='7' ||
        p[2]!='P' || p[3]!='1' || get(p+4,2)!=1 || get(p+8,4)!=bytes ||
        get(p+112,4)!=1 || get(p+124,4)!=crc(p,124) || p[46] || p[47]) return AF_INVALID;
    for (unsigned i=0;i<8;++i) if (p[116+i]) return AF_INVALID;
    for (unsigned i=0;i<64;++i) if (p[48+i]!=builds[i]) return AF_INVALID;
    next.operation=(uint32_t)get(p+6,2);next.required=(uint32_t)get(p+12,4);
    next.session=get(p+16,8);next.version=get(p+24,8);next.slot=(uint32_t)get(p+32,4);
    next.preset.base=p[36];next.preset.kind=p[37];
    for (unsigned i=0;i<8;++i) next.preset.params[i]=(int8_t)p[38+i];
    if (!packet_valid(&next)) return AF_INVALID;
    *output=next;return AF_OK;
}
