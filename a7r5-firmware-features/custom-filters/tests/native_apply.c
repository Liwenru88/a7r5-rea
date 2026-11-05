/* 整包/银行/帧引用的业务结果联验；回执由测试驱动，绝不伪称相机确认。 */
#include "../native/af_apply.h"
#include "../native/af_cp406_state.h"

#define CHECK(x) do { ++af_apply_report[1];if (!(x)) return __LINE__; } while (0)
#define VERSION (UINT64_C(1)<<40)
static AfApply context;
uint32_t af_apply_report[8];
uint8_t af_apply_wire_result[AF_APPLY_PACKET_BYTES];

static int reserve(AfApplyToken *token) {
    for (uint32_t i=0;i<AF_APPLY_CONSUMERS;++i) {
        AfOutputBank bank={0x91000000u+token->bank*0x100000u+i*0x1000u,0x400u};
        int result=af_apply_reserve(&context,token,i,&bank);
        if (result!=AF_OK) return result;
    }
    return AF_OK;
}
static int fill(AfApplyToken *token,int failure) {
    int result=reserve(token);
    if (result!=AF_OK) return result;
    result=af_apply_start(&context,token);
    if (result!=AF_OK) return result;
    for (uint32_t i=0;i<AF_APPLY_CONSUMERS;++i) {
        AfOutputBank bank={0x91000000u+token->bank*0x100000u+i*0x1000u,0x400u};
        result=af_apply_bank(&context,token,i,&bank,(int)i!=failure);
        if (result!=AF_OK) return result;
    }
    return AF_OK;
}

uint32_t af_apply_check(void) {
    AfApplyPacket packet={0},decoded={0},hello={0},peer={0};
    AfApplyToken first,failed,second,third,fourth;
    AfApplyLease old,mid,last;
    AfApplyLease leases[AF_APPLY_LEASES];
    const AfApplyGroup *view;
    uint8_t corrupt[AF_APPLY_PACKET_BYTES],state[AF_CP406_STATE_BYTES+16],marker=0;
    uint8_t old_state[AF_CP406_STATE_BYTES+16];
    AfOutputBank bank={0x91000000u,0x400u};
    AfPreset preset={0};
    size_t written=0;
    packet.operation=AF_APPLY_PRESET;packet.session=42;packet.version=VERSION+1;
    packet.required=AF_APPLY_ALL;packet.slot=20;packet.preset.base=17;
    packet.preset.params[0]=-9;packet.preset.params[1]=9;packet.preset.params[2]=-8;
    packet.preset.params[3]=7;packet.preset.params[4]=-6;packet.preset.params[5]=5;
    packet.preset.params[6]=4;packet.preset.params[7]=3;
    CHECK(af_apply_packet_encode(&packet,af_apply_wire_result,sizeof(af_apply_wire_result),&written)==0);
    CHECK(written==AF_APPLY_PACKET_BYTES);
    CHECK(af_apply_packet_decode(af_apply_wire_result,written,&decoded)==0);
    CHECK(decoded.version==VERSION+1 && decoded.preset.params[0]==-9 && decoded.preset.base==17);
    CHECK(af_apply_init(&context,42,AF_APPLY_ALL)==0);
    CHECK(af_apply_stage(&context,&decoded,&first)==AF_BUSY);
    hello.operation=AF_APPLY_HELLO;hello.session=41;hello.required=AF_APPLY_ALL;
    CHECK(af_apply_negotiate(&context,&hello)==AF_STALE);
    hello.session=42;hello.required=1;
    CHECK(af_apply_negotiate(&context,&hello)==AF_INVALID);
    hello.required=AF_APPLY_ALL;
    hello.preset.base=17;
    CHECK(af_apply_negotiate(&context,&hello)==AF_INVALID);
    hello.preset.base=0;
    CHECK(af_apply_packet_encode(&hello,corrupt,sizeof(corrupt),&written)==0);
    CHECK(af_apply_packet_decode(corrupt,written,&peer)==0);
    CHECK(af_apply_negotiate(&context,&peer)==0);
    CHECK(af_apply_negotiate(&context,&hello)==0);
    CHECK(af_apply_stage(&context,&decoded,&first)==0);
    CHECK(af_apply_publish(&context,&first)==AF_BUSY);
    CHECK(af_apply_frame(&context,3,&old)==AF_EMPTY);
    CHECK(af_apply_bank(&context,&first,0,&bank,1)==AF_BUSY);
    CHECK(af_apply_start(&context,&first)==AF_BUSY);
    CHECK(reserve(&first)==0);
    CHECK(af_apply_reserve(&context,&first,0,&bank)==AF_STALE);
    CHECK(af_apply_bank(&context,&first,0,&bank,1)==AF_BUSY);
    CHECK(af_apply_start(&context,&first)==0);
    for (uint32_t i=0;i<AF_APPLY_CONSUMERS-1;++i) {
        bank.address=0x91000000u+first.bank*0x100000u+i*0x1000u;
        CHECK(af_apply_bank(&context,&first,i,&bank,1)==0);
    }
    CHECK(af_apply_publish(&context,&first)==AF_BUSY);
    bank.address=0x91000000u+first.bank*0x100000u+12*0x1000u;
    CHECK(af_apply_bank(&context,&first,12,&bank,1)==0);
    CHECK(af_apply_publish(&context,&first)==0);
    CHECK(af_apply_frame(&context,3,&old)==0);
    CHECK(af_apply_view(&context,&old,&view)==0 && view->version==VERSION+1 && view->preset.params[0]==-9);
    decoded.version=VERSION+2;decoded.preset.params[0]=2;
    CHECK(af_apply_stage(&context,&decoded,&failed)==0);
    CHECK(reserve(&failed)==0);
    CHECK(af_apply_start(&context,&failed)==0);
    CHECK(af_apply_bank(&context,&failed,0,0,0)==0);
    CHECK(af_apply_abort(&context,&failed)==AF_BUSY);
    for (uint32_t i=1;i<AF_APPLY_CONSUMERS;++i) {
        bank.address=0x91000000u+failed.bank*0x100000u+i*0x1000u;
        CHECK(af_apply_bank(&context,&failed,i,&bank,1)==0);
    }
    CHECK(af_apply_publish(&context,&failed)==AF_IO);
    CHECK(af_apply_abort(&context,&failed)==0);
    CHECK(af_apply_view(&context,&old,&view)==0 && view->preset.params[0]==-9);
    CHECK(af_apply_stage(&context,&decoded,&failed)==AF_STALE);
    decoded.version=VERSION+3;
    CHECK(af_apply_stage(&context,&decoded,&second)==0);
    bank.address=0x91000000u+first.bank*0x100000u;
    CHECK(af_apply_reserve(&context,&second,0,&bank)==AF_BUSY);
    CHECK(af_apply_bank(&context,&first,0,&bank,1)==AF_STALE);
    CHECK(fill(&second,-1)==0);
    CHECK(af_apply_bank(&context,&second,0,&bank,1)==AF_STALE);
    CHECK(af_apply_publish(&context,&second)==0);
    CHECK(af_apply_frame(&context,1,&mid)==0);
    decoded.version=VERSION+4;
    CHECK(af_apply_stage(&context,&decoded,&third)==0);
    CHECK(fill(&third,-1)==0 && af_apply_publish(&context,&third)==0);
    CHECK(af_apply_frame(&context,1,&last)==0);
    decoded.version=VERSION+5;
    CHECK(af_apply_stage(&context,&decoded,&fourth)==AF_BUSY);
    CHECK(af_apply_retire(&context,&old,1)==0);
    CHECK(af_apply_retire(&context,&old,1)==AF_STALE);
    CHECK(af_apply_retire(&context,&old,2)==0);
    CHECK(af_apply_stage(&context,&decoded,&fourth)==AF_BUSY);
    CHECK(af_apply_owner_end(&context,&old)==0);
    CHECK(af_apply_owner_end(&context,&old)==AF_STALE);
    CHECK(af_apply_stage(&context,&decoded,&fourth)==0 && fourth.bank==first.bank);
    CHECK(fill(&fourth,-1)==0 && af_apply_publish(&context,&fourth)==0);
    CHECK(af_apply_view(&context,&old,&view)==AF_STALE);
    CHECK(af_apply_init(&context,43,AF_APPLY_ALL)==AF_BUSY);
    CHECK(af_apply_owner_end(&context,&mid)==0 && af_apply_retire(&context,&mid,1)==0);
    CHECK(af_apply_retire(&context,&last,1)==0 && af_apply_owner_end(&context,&last)==0);
    for (uint32_t slot=1;slot<=20;++slot) {
        decoded.version=VERSION+5+slot;decoded.slot=slot;
        CHECK(af_apply_stage(&context,&decoded,&first)==0);
        CHECK(fill(&first,-1)==0 && af_apply_publish(&context,&first)==0);
        CHECK(af_apply_frame(&context,7,&old)==0);
        CHECK(af_apply_view(&context,&old,&view)==0 && view->slot==slot);
        CHECK(af_apply_owner_end(&context,&old)==0 && af_apply_retire(&context,&old,7)==0);
    }
    CHECK(af_apply_init(&context,43,AF_APPLY_ALL)==0);
    CHECK(af_apply_retire(&context,&old,1)==AF_STALE);
    hello.session=43;
    CHECK(af_apply_negotiate(&context,&hello)==0);
    decoded.session=43;decoded.version=VERSION+99;
    CHECK(af_apply_stage(&context,&decoded,&first)==0 && fill(&first,-1)==0);
    CHECK(af_apply_publish(&context,&first)==0);
    decoded.version=VERSION+100;
    CHECK(af_apply_stage(&context,&decoded,&failed)==0);
    bank.address=0x91000000u+failed.bank*0x100000u;
    CHECK(af_apply_reserve(&context,&failed,0,&bank)==0);
    CHECK(af_apply_reserve(&context,&failed,1,&bank)==AF_BUSY);
    CHECK(af_apply_start(&context,&failed)==AF_BUSY);
    CHECK(af_apply_abort(&context,&failed)==0);
    CHECK(af_apply_bank(&context,&failed,0,0,0)==AF_STALE);
    CHECK(af_apply_stage(&context,&decoded,&failed)==AF_STALE);
    for (unsigned i=0;i<AF_APPLY_LEASES;++i) CHECK(af_apply_frame(&context,1,&leases[i])==0);
    CHECK(af_apply_frame(&context,1,&old)==AF_BUSY);
    for (unsigned i=0;i<AF_APPLY_LEASES;++i) {
        CHECK(af_apply_owner_end(&context,&leases[i])==0);
        CHECK(af_apply_retire(&context,&leases[i],1)==0);
    }
    context.next_lease=UINT64_MAX;
    CHECK(af_apply_frame(&context,1,&old)==AF_EXHAUSTED);
    context.last_version=UINT64_MAX;decoded.version=UINT64_MAX;
    CHECK(af_apply_stage(&context,&decoded,&failed)==AF_EXHAUSTED);
    for (size_t byte=0;byte<sizeof(corrupt);++byte) {
        for (size_t j=0;j<sizeof(corrupt);++j) corrupt[j]=af_apply_wire_result[j];
        corrupt[byte]^=1;
        CHECK(af_apply_packet_decode(corrupt,sizeof(corrupt),&decoded)==AF_INVALID);
    }
    preset=packet.preset;
    for (size_t j=0;j<sizeof(state);++j) state[j]=old_state[j]=(uint8_t)(j*17u+3u);
    CHECK(af_cp406_write_state(&preset,state+8,AF_CP406_STATE_BYTES,&marker)==0);
    CHECK(marker==1 && state[8+0xa40]==19 && state[8+0xd2e]==5 && state[8+0xd2f]==4);
    for (size_t j=0;j<8;++j) CHECK(state[j]==old_state[j] && state[sizeof(state)-1-j]==old_state[sizeof(state)-1-j]);
    preset.params[6]=0;marker=9;
    for (size_t j=0;j<sizeof(state);++j) old_state[j]=state[j];
    CHECK(af_cp406_write_state(&preset,state+8,AF_CP406_STATE_BYTES,&marker)==AF_INVALID);
    CHECK(marker==9);
    for (size_t j=0;j<sizeof(state);++j) CHECK(state[j]==old_state[j]);
    af_apply_report[0]=0x41374131u;af_apply_report[2]=20;
    af_apply_report[3]=13;af_apply_report[4]=3;af_apply_report[5]=128;
    return 0;
}
