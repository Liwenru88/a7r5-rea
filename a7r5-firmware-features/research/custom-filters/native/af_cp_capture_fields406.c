#include "af_cp_capture_fields406.h"
static const uint8_t offsets[47]={0,4,5,6,7,8,9,10,11,12,13,14,16,17,18,19,20,21,22,
    24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,48,49,50,51,52,53,54,55,56,57};
static int apart(const void *a,size_t n,const void *b,size_t m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
static uint32_t u32(const uint8_t *p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
int af_cp_capture_fields406_shadow(const uint8_t *s,uint8_t *out){
    if(!apart(s,84,out,47))return AF_INVALID;
    for(unsigned i=0;i<47;++i){
        unsigned d=offsets[i],from=d>=48&&d<56?d-4:d==57?68:d;
        out[i]=(uint8_t)((d>=8&&d<=11)||d==20?s[from]!=0:s[from]);
    }
    return AF_OK;
}
int af_cp_capture_fields406_normalize(const uint8_t *d,uint8_t *out){
    if(!apart(d,0x3a,out,47))return AF_INVALID;
    for(unsigned i=0;i<47;++i)out[i]=d[offsets[i]];
    return AF_OK;
}
int af_cp_capture_fields406_matches(const uint8_t *s,const uint8_t *d){
    uint8_t expected[47],actual[47];unsigned different=0,diagnostic=0;
    if(af_cp_capture_fields406_shadow(s,expected)!=AF_OK||
       af_cp_capture_fields406_normalize(d,actual)!=AF_OK)return AF_INVALID;
    for(unsigned i=0;i<47;++i){
        unsigned offset=offsets[i],fallback=offset==0?s[0]:offset==48?1u:offset==52?3u:0u;
        different|=expected[i]^actual[i];diagnostic|=expected[i]^fallback;
    }
    return different||!diagnostic?AF_EMPTY:AF_OK;
}
typedef struct {uint8_t value[0x4e],written[0x4e];} Fields;
static void byte(Fields *p,unsigned offset,unsigned value){p->value[offset]=(uint8_t)value;p->written[offset]=1;}
static void word(Fields *p,unsigned offset,uint32_t value){
    for(unsigned j=0;j<4;++j)byte(p,offset+j,value>>(j*8));
}
static int read32(AfCpCaptureRead read,void *context,uint32_t address,uint32_t *out){
    uint8_t raw[4];int status=read(context,address,raw,4);if(status)return status;
    *out=u32(raw);return AF_OK;
}
static int table(AfCpCaptureRead read,void *context,uint32_t address,
                 uint32_t index,unsigned endpoint,uint32_t *out){
    /* 每个原表使用独立的保守索引域，不接受负值的无符号伪装或跨表读取。 */
    unsigned limit=address==0xdcc514u?63u:address==0x107eefcu?18u:
        address==0xdcc714u?2u:address==0xdcc72cu?17u:0u;
    if(index>limit||endpoint>1)return AF_EMPTY;
    return read32(read,context,address+8u*index+4u*endpoint,out);
}
static int routes(Fields *p,AfCpCaptureRead read,void *context,uint32_t base,uint32_t index,
                   uint32_t other,unsigned endpoint){
    uint32_t a,b,c;int status=table(read,context,base,index,endpoint,&a);
    if(!status)status=table(read,context,base,other,endpoint,&b);
    if(!status)status=table(read,context,base,other,0,&c);
    if(status)return status;
    word(p,0x30,a);word(p,0x40,b);word(p,0x34,c);return AF_OK;
}
static void same_route(Fields *p,uint32_t route){word(p,0x30,route);word(p,0x34,route);word(p,0x40,route);}
int af_cp_capture_fields406_formatter(const uint8_t *d,const uint8_t *e,const uint8_t *f,
    AfCpCaptureRead read,void *context){
    if(!d||!e||!f||!read)return AF_INVALID;
    Fields p;uint8_t snapshot[0x4e],debug;uint32_t mode,profile=u32(d+4),marker=u32(d+0x10);
    unsigned endpoint=d[8];int status;
    for(unsigned i=0;i<0x4e;++i){((volatile uint8_t *)p.written)[i]=0;snapshot[i]=((const volatile uint8_t *)f)[i];}
    if(endpoint>1||d[9]>1||d[10]>1||d[11]>1||d[0x14]>1||
       (marker>=249&&marker<=254)||d[0x15]>=14)return AF_EMPTY;
    status=read32(read,context,0xdcc4e0u,&mode);if(status)return status;
    status=read(context,0x18d1c25u,&debug,1);if(status)return status;
    if(mode==2||debug==2)return AF_EMPTY;
    word(&p,0,u32(d+4));
    for(unsigned i=0;i<7;++i)byte(&p,4+i,d[8+i]);
    word(&p,0xc,marker);
    for(unsigned i=0;i<3;++i)byte(&p,0x10+i,d[0x14+i]);
    for(unsigned i=0;i<4;++i)word(&p,0x14+4*i,u32(d+0x18+4*i));
    byte(&p,0x24,d[0x28]);byte(&p,0x25,d[0x29]);
    word(&p,0x28,u32(d+0x30));word(&p,0x2c,u32(d+0x34));
    byte(&p,0x3e,d[0x28]);byte(&p,0x3f,d[0x29]);byte(&p,0x39,endpoint);
    byte(&p,0x46,d[0xb]);word(&p,0x48,u32(d+0x18));
    uint32_t base=0xdcc514u,index=profile;
    if(marker&&marker!=255){
        int select=profile<3||(profile>=18&&profile<=43&&((1u<<(profile-18))&0x02008001u));
        if(select||d[0x14]){base=0x107eefcu;index=marker;}
    }
    status=routes(&p,read,context,base,index,u32(d+0x30),endpoint);if(status)return status;
    if(endpoint&&u32(d+0x20)){
        status=routes(&p,read,context,0xdcc714u,u32(d+0x20),u32(d+0x20),1);if(status)return status;
    }
    if(u32(d+0x24)){
        if(u32(d+0x24)!=1)return AF_EMPTY;
        uint32_t first,second;
        status=read32(read,context,0xdcc7c4u+4u*endpoint,&first);if(status)return status;
        status=read32(read,context,0xdcc7c4u,&second);if(status)return status;
        word(&p,0x30,first);word(&p,0x40,first);word(&p,0x34,second);
    }
    if(!d[0xb]){
        uint32_t value;status=table(read,context,0x107eefcu,0,endpoint,&value);if(status)return status;
        word(&p,0x30,value);
    }
    if(d[0x16]){
        uint32_t index=u32(d+0x18);if(!index)return AF_EMPTY;
        status=routes(&p,read,context,0xdcc72cu,index,index,endpoint);if(status)return status;
    }
    if(d[0xa])same_route(&p,45);
    if(u32(d+0x2c)==2||(endpoint&&u32(d+0x34)<=2))same_route(&p,31);
    if(u32(p.value+0x30)>=51||u32(p.value+0x34)>=51||u32(p.value+0x40)>=51)return AF_EMPTY;
    uint32_t route=u32(p.value+0x30);
    byte(&p,0x38,route==31||route==28?d[0x2a]:6);
    byte(&p,0x3c,d[0x15]);byte(&p,0x3d,d[0x15]);
    unsigned first=(uint8_t)(d[0xc]-d[0xd]+18),second=(uint8_t)(d[0xc]+d[0xe]+18);
    if(first>36)first=18;if(second>36)second=18;
    if(d[0x16]||d[0x15]||!d[0xb])first=second=18;
    byte(&p,0x3a,first);byte(&p,0x3b,second);byte(&p,0x44,first!=18);
    if(!d[0xb])byte(&p,0x3d,0);
    byte(&p,0x45,p.value[0x3d]!=0);
    if(e[2]){
        uint32_t value;status=table(read,context,0xdcc514u,u32(e+4),0,&value);if(status)return status;
        word(&p,0x30,value);
    }
    if(e[3])byte(&p,0x38,e[8]);
    if(e[1]){byte(&p,0x39,0);word(&p,0x30,u32(p.value+0x34));}
    if(!e[0]){
        if(!p.value[0x12]&&!p.value[6]){
            uint32_t value;status=table(read,context,0x107eefcu,0,0,&value);if(status)return status;
            word(&p,0x30,value);
        }
        byte(&p,0x3a,18);byte(&p,0x3b,18);byte(&p,0x3d,0);
    }
    if(p.value[0x39]>=2||u32(p.value+0x30)>=51||p.value[0x38]>=7||
       p.value[0x3a]>36||p.value[0x3b]>36)return AF_EMPTY;
    for(unsigned i=0;i<0x4e;++i){
        if(((const volatile uint8_t *)f)[i]!=snapshot[i])return AF_STALE;
        if(p.written[i]&&snapshot[i]!=p.value[i])return AF_EMPTY;
    }
    return AF_OK;
}
