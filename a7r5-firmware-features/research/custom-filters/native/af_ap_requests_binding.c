#include "af_ap_requests_binding.h"
/* 固定AP d15933...：原PLT完整16B、四个返回窗口及初始化入口。 */
const AfApRequestsCheck af_ap_requests_checks[16]={
 {0x16dabe0u,{0xd0021590u,0xf9462611u,0x91312210u,0xd61f0220u}},
 {0x16dac90u,{0xd0021590u,0xf9465211u,0x91328210u,0xd61f0220u}},
 {0x16d9740u,{0xf0021590u,0xf940fe11u,0x9107e210u,0xd61f0220u}},
 {0x16d9840u,{0xf0021590u,0xf9413e11u,0x9109e210u,0xd61f0220u}},
 {0x16dba00u,{0xd0021590u,0xf941ae11u,0x910d6210u,0xd61f0220u}},
 {0x16db580u,{0xd0021590u,0xf9408e11u,0x91046210u,0xd61f0220u}},
 {0x16dc740u,{0xb0021590u,0xf944fe11u,0x9127e210u,0xd61f0220u}},
 {0x16d99c0u,{0xf0021590u,0xf9419e11u,0x910ce210u,0xd61f0220u}},
 {0x16dafc0u,{0xd0021590u,0xf9471e11u,0x9138e210u,0xd61f0220u}},
 {0x16dae10u,{0xd0021590u,0xf946b211u,0x91358210u,0xd61f0220u}},
 {0x16daf60u,{0xd0021590u,0xf9470611u,0x91382210u,0xd61f0220u}},
 {0x3554d94u,{0x79013fbfu,0x7100441fu,0x54000a01u,0xb9400661u}},
 {0x3554ec8u,{0xf94053a1u,0x52800040u,0x72b00040u,0x97861ee3u}},
 {0x3554d24u,{0xaa1703e1u,0x52800040u,0x12800002u,0x72b00040u}},
 {0x3554d3cu,{0xf94053b3u,0xaa1303e0u,0x97861c03u,0x2a0003f4u}},
 {0x17feac0u,{0xa9ba7bfdu,0xf00209a3u,0xb000f922u,0xd2800401u}}
};
const uint32_t af_ap_requests_exit_offsets[4]={0x3554d94u,0x3554ec8u,0x3554d3cu,0x3554d24u};
__attribute__((visibility("hidden"))) uintptr_t af_ap_requests_targets[AF_AP_REQUESTS_IMPORTS];
extern const uint32_t af_ap_hs_original_return[],af_ap_hs_owned_return[];
extern const uint32_t af_ap_receive_return[],af_ap_receive_loop[];
static uint32_t bound;
static int separate(uintptr_t a,size_t n,uintptr_t b,size_t m){
 return a<=UINTPTR_MAX-n && b<=UINTPTR_MAX-m && (a+n<=b || b+m<=a);
}
int af_ap_requests_resolve(const AfApRequestsBinding *b,uintptr_t out[AF_AP_REQUESTS_IMPORTS]){
 static const uint8_t sha[32]={0xd1,0x59,0x33,0xce,0xb5,0xff,0x9a,0xd0,0xb4,0xf7,0x89,0xcb,0xab,0xd6,0xff,0x0a,0x51,0x52,0x64,0x72,0xdd,0x35,0xc9,0x0d,0xb9,0x71,0x96,0xdd,0x22,0x78,0x20,0xe9};
 uintptr_t next[AF_AP_REQUESTS_IMPORTS];
 if(!b || !out || (uintptr_t)b%_Alignof(AfApRequestsBinding) || (uintptr_t)out%_Alignof(uintptr_t) ||
    b->version!=1 || b->bytes!=sizeof(*b) || !b->base || (b->base&4095u) ||
    b->mapped_bytes!=AF_AP_REQUESTS_SPAN || b->base>UINTPTR_MAX-AF_AP_REQUESTS_SPAN ||
    b->application_init!=b->base+0x17feac0u ||
    !separate((uintptr_t)b,sizeof(*b),(uintptr_t)out,sizeof(next)) ||
    !separate(b->base,b->mapped_bytes,(uintptr_t)b,sizeof(*b)) ||
    !separate(b->base,b->mapped_bytes,(uintptr_t)out,sizeof(next)))return AF_INVALID;
 for(unsigned i=0;i<32;++i)if(b->ap_sha256[i]!=sha[i])return AF_INVALID;
 for(unsigned i=0;i<16;++i)for(unsigned j=0;j<4;++j)
  if(*(const uint32_t *)(b->base+af_ap_requests_checks[i].offset+4u*j)!=af_ap_requests_checks[i].words[j])return AF_STALE;
 for(unsigned i=0;i<AF_AP_REQUESTS_IMPORTS;++i)next[i]=b->base+af_ap_requests_checks[i].offset;
 for(unsigned i=0;i<AF_AP_REQUESTS_IMPORTS;++i)out[i]=next[i];
 return AF_OK;
}
int af_ap_requests_bind(const AfApRequestsBinding *b){
 const uint32_t *const exits[4]={af_ap_hs_original_return,af_ap_hs_owned_return,af_ap_receive_return,af_ap_receive_loop};
 uintptr_t next[AF_AP_REQUESTS_IMPORTS];int result;
 if(bound)return AF_BUSY;
 result=af_ap_requests_resolve(b,next);if(result)return result;
 for(unsigned i=0;i<4;++i){
  uintptr_t from=(uintptr_t)exits[i],to=b->base+af_ap_requests_exit_offsets[i];
  uint64_t distance=from>to?from-to:to-from;
  if((from&3u) || (to&3u) || distance>(1u<<27) || (to>=from && distance==(1u<<27)))return AF_INVALID;
  int64_t delta=to>=from?(int64_t)distance:-(int64_t)distance;
  uint32_t expected=0x14000000u|((uint32_t)(delta/4)&0x3ffffffu);
  if(*exits[i]!=expected)return AF_STALE;
 }
 for(unsigned i=0;i<AF_AP_REQUESTS_IMPORTS;++i)af_ap_requests_targets[i]=next[i];
 bound=1;return AF_OK;
}
