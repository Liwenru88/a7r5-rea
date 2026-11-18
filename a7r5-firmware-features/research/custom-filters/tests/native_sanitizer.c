/* 对外部文本和有界状态操作执行地址/未定义行为检查，不链接设备代码。 */
#include "../native/af_cube.h"
#include "../native/af_slots.h"
#include "../native/af_record.h"
#include "../native/af_ui.h"
#include "../native/af_document.h"
#include "../native/af_cp406.h"
#include "../native/af_cp406_state.h"
#include "../native/af_apply.h"
#include "../native/af_handshake.h"
#include "../native/af_runtime.h"
#include "../native/af_grid.h"
#include "../native/af_joint.h"
#include "../native/af_gamma406.h"
#include "../native/af_import.h"
#include "../native/af_color406.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint32_t seed = 0x7a7f506u;
static uint64_t runtime_now;
static int runtime_clock(uint64_t *v) { *v=runtime_now;return 0; }
static int runtime_nonce(uint64_t *v) { *v=43;return 0; }
static int runtime_send(const void *p,size_t n) { return !p || n!=128; }
static int runtime_receive(uint32_t queue,void **p,int wait) {
    assert(queue==0x80020002u && wait>=1 && wait<=50);
    *p=0;runtime_now+=(unsigned)wait;return -1022;
}
static const AfRuntimePorts runtime_ports={runtime_nonce,runtime_clock,runtime_send,runtime_receive};
extern uint32_t af_pipeline_check(void);
extern uint32_t af_apply_check(void);
extern uint32_t af_grid_target_check(void);
extern uint32_t af_joint_target_check(void);
extern uint32_t af_import_target_check(void);
extern uint32_t af_color406_target_check(void);
extern const AfGridModel af_grid_test_model;
extern uint8_t af_apply_wire_result[AF_APPLY_PACKET_BYTES];
static uint32_t wire_crc(const uint8_t *p,size_t n) {
    uint32_t c=UINT32_MAX;
    for (size_t i=0;i<n;++i) {
        c^=p[i];
        for (unsigned j=0;j<8;++j) c=(c>>1)^(0xedb88320u&(0u-(c&1u)));
    }
    return ~c;
}
static uint32_t random_word(void) {
    seed ^= seed << 13;
    seed ^= seed >> 17;
    seed ^= seed << 5;
    return seed;
}

int main(void) {
    AfCatalog catalog;
    AfPreset preset = {0};
    AfSave pending[20] = {0};
    const char header[] = "LUT_3D_SIZE 2\n";
    unsigned iteration, i;
    uint8_t encoded[512];
    size_t encoded_bytes=0;
    AfDocument document={0};
    static uint8_t cp_source[AF_CP406_PREFIX_BYTES],cp_target[AF_CP406_PREFIX_BYTES];
    document.present=1;document.name="probe";document.name_bytes=5;
    document.initial.params[6]=3;document.saved=document.initial;
    assert(af_document_encode(&document,0,encoded,sizeof(encoded),&encoded_bytes)==0);
    af_catalog_init(&catalog);
    assert(af_apply_check()==0);
    assert(af_grid_target_check()==0);
    assert(af_import_target_check()==0);
    assert(af_color406_target_check()==0);
    preset.params[6] = 3;
    for (i = 1; i <= 20; ++i) assert(af_install(&catalog, i, &preset, 0) == AF_OK);
    for (iteration = 0; iteration < 20000; ++iteration) {
        char text[1024];
        float storage[24], rgb[3], output[3];
        AfCube cube = {0};
        AfCubeLimits limits = {33, sizeof(text)};
        size_t length = random_word() % sizeof(text);
        uint32_t slot = random_word() % 24;
        int status;
        {
            uint16_t raw[24],cal[3],metadata[8];int16_t adjust[8],out[27],delta[27],changed[27];
            for (unsigned k=0;k<24;++k) raw[k]=(uint16_t)random_word();
            for (unsigned k=0;k<3;++k) cal[k]=(uint16_t)random_word();
            for (unsigned k=0;k<8;++k) {adjust[k]=(int16_t)((int)(random_word()%65536)-32768);metadata[k]=(uint16_t)random_word();}
            assert(af_color406_matrix(raw,cal,out)==AF_OK);
            for (unsigned k=0;k<3;++k) for (unsigned row=0;row<3;++row)
                assert(((unsigned)((int32_t)out[k*9+row*3]+out[k*9+row*3+1]+out[k*9+row*3+2])&65535u)==cal[row]);
            assert(af_color406_primary(raw,adjust,out)==AF_OK);
            for (unsigned k=0;k<8;++k) {
                assert(((int32_t)out[8+k]-out[k]-raw[8+k])%65536==0);
                assert(((int32_t)out[16+k]-out[k]-raw[16+k])%65536==0);
            }
            assert(af_color406_secondary(raw,adjust,metadata,out)==AF_OK);
            for (unsigned k=0;k<8;++k) assert((uint16_t)out[k+8]==metadata[k]);
            for (unsigned k=0;k<27;++k) {out[k]=(int16_t)((int)(random_word()%65536)-32768);delta[k]=(int16_t)((int)(random_word()%65536)-32768);changed[k]=12345;}
            status=af_color406_add(out,delta,(iteration&1)?26:27,changed);
            assert(status==((iteration&1)?AF_INVALID:AF_OK));
            for (unsigned k=0;k<27;++k)
                if (status) assert(changed[k]==12345);
                else assert((uint16_t)changed[k]==(uint16_t)((int32_t)out[k]+delta[k]));
            {
                uint16_t weights[4];
                weights[0]=(uint16_t)(random_word()%257);weights[1]=(uint16_t)(random_word()%257);
                weights[2]=(uint16_t)(random_word()%(257-weights[1]));weights[3]=(uint16_t)(random_word()%257);
                if (iteration&1) weights[1]=weights[2]=256;
                for (unsigned k=0;k<27;++k) changed[k]=12345;
                status=af_color406_blend(out,weights,changed);
                assert(status==((iteration&1)?AF_INVALID:AF_OK));
                for (unsigned k=status?0:8;k<27;++k) assert(changed[k]==12345);
                for (unsigned k=0;k<27;++k) changed[k]=12345;
                status=af_color406_matrix_blend(out,weights,changed);
                assert(status==((iteration&1)?AF_INVALID:AF_OK));
                for (unsigned k=status?0:9;k<27;++k) assert(changed[k]==12345);
            }
            {
                uint8_t selected[8];
                for (unsigned k=0;k<8;++k) selected[k]=(uint8_t)random_word();
                assert(af_color406_adjust(selected,changed)==AF_OK);
                for (unsigned k=0;k<8;++k)
                    assert(changed[k]==(k<4 && selected[k]>=128?(int)selected[k]-256:selected[k]));
            }
        }
        {
            AfJointAsset original={0},decoded;uint8_t raw[AF_JOINT_ASSET_BYTES];size_t written=777;
            original.base=(iteration&1)?18:0;original.model_sha256[0]=1;
            for (unsigned k=0;k<129;++k) original.recipe.gamma[k]=k*1023;
            for (unsigned k=0;k<AF_GRID_BYTES;++k) original.recipe.grid[k]=(int8_t)((int)(random_word()%128)-64);
            assert(af_joint_asset_encode(&original,raw,sizeof(raw),&written)==AF_OK && written==sizeof(raw));
            assert(af_joint_asset_decode(raw,sizeof(raw),&decoded)==AF_OK);
            raw[random_word()%sizeof(raw)]^=1;memset(&decoded,0xa5,sizeof(decoded));
            assert(af_joint_asset_decode(raw,sizeof(raw),&decoded)!=AF_OK);
            for (unsigned k=0;k<sizeof(decoded);++k) assert(((uint8_t *)&decoded)[k]==0xa5);
        }
        {
            static const uint8_t exponent[12]={0,0,1,2,3,4,5,4,3,4,4,3};
            uint8_t record[576]={0},output_record[576];uint32_t axis[129],curve[129];
            AfGamma406Span bracket={77,77,77,77};
            for (unsigned k=0;k<129;++k) {
                uint32_t y=k*1023u;
                for (unsigned b=0;b<4;++b) record[k*4+b]=(uint8_t)(y>>(b*8));
                curve[k]=(k*k*180001u)/16384u;axis[k]=0xa5a5a5a5u;
            }
            memcpy(record+0x204,exponent,12);memset(output_record,0xa5,sizeof(output_record));
            if (iteration&1) record[0x204+random_word()%12]=16;
            status=af_gamma406_axis(record,axis);
            assert(status==((iteration&1)?AF_INVALID:AF_OK));
            if (status==AF_INVALID) for (unsigned k=0;k<129;++k) assert(axis[k]==0xa5a5a5a5u);
            else {
                uint32_t code=random_word()%70000;
                status=af_gamma406_locate(axis,code,&bracket);
                assert(status==(code>65535?AF_INVALID:AF_OK));
                if (status==AF_OK) assert(bracket.left<bracket.right && bracket.offset<=bracket.width);
                else assert(bracket.left==77 && bracket.right==77 && bracket.offset==77 && bracket.width==77);
            }
            if (iteration&2) curve[127]=0x40000u;
            status=af_gamma406_replace(record,curve,output_record);
            assert(status==((iteration&3)?AF_INVALID:AF_OK));
            if (status==AF_INVALID) for (unsigned k=0;k<576;++k) assert(output_record[k]==0xa5);
        }
        {
            uint32_t curve[129],changed[129];int16_t tone[3],matrix[18],expanded[27];
            for (unsigned k=0;k<129;++k) {curve[k]=k*2047u;changed[k]=0xa5a5a5a5u;}
            for (unsigned k=0;k<3;++k) tone[k]=(int16_t)((int)(random_word()%2201)-1100);
            if (iteration&1) curve[random_word()%129]=0x40000u;
            status=af_joint_gamma(curve,tone,changed);
            assert(status==AF_OK || status==AF_INVALID);
            if (status==AF_INVALID) for (unsigned k=0;k<129;++k) assert(changed[k]==0xa5a5a5a5u);
            else for (unsigned k=1;k<129;++k) assert(changed[k]>=changed[k-1] && changed[k]<=0x3ffffu);
            for (unsigned k=0;k<18;++k) matrix[k]=(int16_t)((int)(random_word()%2201)-1100);
            for (unsigned k=0;k<27;++k) expanded[k]=12345;
            status=af_joint_expand_matrix(matrix,expanded);
            assert(status==AF_OK || status==AF_INVALID);
            if (status==AF_INVALID) for (unsigned k=0;k<27;++k) assert(expanded[k]==12345);
            else for (unsigned k=0;k<27;k+=3) assert(expanded[k]+expanded[k+1]+expanded[k+2]==0);
        }
        {
            int8_t grid[AF_GRID_BYTES];uint16_t order[AF_GRID_NODES];uint32_t packed[AF_GRID_NODES];
            float input[3],output_rgb[3]={42,42,42};
            for (unsigned k=0;k<AF_GRID_BYTES;++k) grid[k]=(int8_t)((int)(random_word()%128)-64);
            if (iteration&1) grid[random_word()%AF_GRID_BYTES]=(iteration&4)?64:-65;
            for (unsigned k=0;k<3;++k) input[k]=(float)(random_word()%1501)/1000-.25f;
            status=af_grid_predict(&af_grid_test_model,grid,input,output_rgb);
            assert(status==AF_OK || status==AF_INVALID);
            if (status==AF_INVALID) for (unsigned k=0;k<3;++k) assert(output_rgb[k]==42);
            for (unsigned k=0;k<AF_GRID_NODES;++k) {order[k]=(uint16_t)(404-k);packed[k]=0xa5a5a5a5u;}
            if (iteration&2) order[100]=order[101];
            status=af_grid_pack(grid,order,random_word()%10,packed);
            assert(status==AF_OK || status==AF_INVALID);
            if (status==AF_INVALID) for (unsigned k=0;k<AF_GRID_NODES;++k) assert(packed[k]==0xa5a5a5a5u);
        }
        {
            AfRuntime runtime={0};void *message=(void *)(uintptr_t)1;
            runtime_now=iteration;
            assert(af_rt_next(&runtime,&runtime_ports,0x80020002u,&message)==0 && !message);
            assert(runtime.hello.state==1 && runtime.attempted==1 && !runtime.fault);
            if (iteration&2) {
                assert(af_rt_poll(&runtime,0)==AF_INVALID && runtime.fault==AF_RT_CLOCK);
            } else if (iteration&1) {
                runtime_now=(uint64_t)iteration+1000;
                assert(af_rt_poll(&runtime,&runtime_ports)==AF_STALE && runtime.hello.state==3);
            } else {
                runtime_now=0;
                assert(af_rt_poll(&runtime,&runtime_ports)==AF_INVALID && runtime.fault==AF_RT_CLOCK);
            }
        }
        for (i = 0; i < length; ++i) text[i] = (char)random_word();
        if (length >= sizeof(header) && (iteration & 1)) memcpy(text, header, sizeof(header)-1);
        status = af_cube_parse(text, length, &cube, storage, random_word()%25, limits);
        if (status == AF_CUBE_OK) {
            for (i = 0; i < 3; ++i) rgb[i] = (float)(random_word()%1024)/1024;
            assert(af_cube_eval(&cube, rgb, output) == AF_CUBE_OK);
        } else assert(cube.dimension == 0);
        status = af_edit(&catalog, slot, random_word()%12, (int)(random_word()%801)-400);
        assert(status == AF_OK || status == AF_INVALID);
        {
            AfPreset probe=preset;
            size_t capacity=(iteration&1)?sizeof(cp_source):random_word()%sizeof(cp_source);
            probe.base=(uint8_t)(random_word()%21);
            probe.params[random_word()%8]=(int8_t)random_word();
            status=af_cp406_overlay(&probe,cp_source,cp_target,capacity);
            assert(status==AF_OK || status==AF_INVALID);
            if (status==AF_OK) assert(af_cp406_matches(&probe,cp_target,capacity)==AF_OK);
        }
        {
            uint8_t wire[AF_APPLY_PACKET_BYTES],before[sizeof(AfApplyPacket)];
            uint8_t state[AF_CP406_STATE_BYTES],old_state[AF_CP406_STATE_BYTES],marker=9;
            AfApplyPacket decoded;
            AfPreset probe=preset;
            uint32_t crc;
            memcpy(wire,af_apply_wire_result,sizeof(wire));
            for (i=0;i<1+(iteration%4);++i) wire[random_word()%124]^=(uint8_t)random_word();
            crc=wire_crc(wire,124);
            for (i=0;i<4;++i) wire[124+i]=(uint8_t)(crc>>(8*i));
            memset(&decoded,0xa5,sizeof(decoded));memcpy(before,&decoded,sizeof(decoded));
            status=af_apply_packet_decode(wire,(iteration&1)?sizeof(wire):random_word()%129,&decoded);
            if (status==AF_INVALID) assert(!memcmp(before,&decoded,sizeof(decoded)));
            else assert(status==AF_OK && af_validate(&decoded.preset)==AF_OK);
            memset(state,0x5a,sizeof(state));memcpy(old_state,state,sizeof(state));
            probe.base=(uint8_t)(random_word()%21);
            probe.params[random_word()%8]=(int8_t)random_word();
            status=af_cp406_write_state(&probe,state,random_word()%(sizeof(state)+1),&marker);
            assert(status==AF_OK || status==AF_INVALID);
            if (status==AF_INVALID) assert(marker==9 && !memcmp(state,old_state,sizeof(state)));
        }
        {
            AfHandshake client={0},server={0};
            uint8_t wire[128],reply[128];size_t reply_bytes=0;
            uint32_t crc;
            assert(af_hs_begin(&client,(uint64_t)iteration+1,AF_APPLY_ALL,100,50,wire)==0);
            assert(af_hs_server_init(&server,AF_APPLY_ALL)==0);
            wire[random_word()%128]^=(uint8_t)random_word();
            if (iteration&1) {
                crc=wire_crc(wire,124);
                for (i=0;i<4;++i) wire[124+i]=(uint8_t)(crc>>(8*i));
            }
            memset(reply,0xa5,sizeof(reply));
            (void)af_hs_server(&server,wire,(iteration&1)?128:random_word()%129,
                               0x80020002u,reply,sizeof(reply),&reply_bytes);
            if (reply_bytes) {
                assert(reply_bytes==128);
                assert(af_hs_client(&client,reply,reply_bytes,0x90030001u,149)==1);
                assert(client.state==1 || client.state==2);
            } else for (i=0;i<sizeof(reply);++i) assert(reply[i]==0xa5);
            (void)af_hs_poll(&client,150);
            assert(client.state==2 || client.state==3);
        }
        {
            AfUiRoute route = {0};
            int value = 99;
            status = af_ui_item(random_word()%36, &route);
            assert(status == AF_OK || status == AF_INVALID);
            if (status == AF_OK) {
                (void)af_ui_read(&catalog, route.menu, random_word()%10, &value);
                (void)af_ui_step(&catalog, route.menu, random_word()%10, random_word()%3, &value);
                (void)af_ui_assign(&catalog,route.menu,random_word()%10,
                                   (int)(random_word()%801)-400,&value);
                {
                    uint8_t snapshot[160], enabled[8];
                    for (i = 0; i < 8; ++i) enabled[i] = (uint8_t)(random_word()%3);
                    memset(snapshot,0xa5,sizeof(snapshot));
                    (void)af_ui_snapshot(&catalog,route.menu,enabled,snapshot);
                }
            }
        }
        if (slot >= 1 && slot <= 20) {
            switch (random_word()%4) {
                case 0: (void)af_begin_save(&catalog, slot, &pending[slot-1]); break;
                case 1: (void)af_finish_save(&catalog, &pending[slot-1], random_word()&1); break;
                case 2: (void)af_restore(&catalog, slot, random_word()&1); break;
                default: (void)af_install(&catalog, slot, &preset, 1); break;
            }
        }
        {
            uint8_t corrupted[512],roundtrip[512];
            AfDocument decoded={0};
            size_t roundtrip_bytes=0;
            memcpy(corrupted,encoded,encoded_bytes);
            corrupted[random_word()%encoded_bytes]^=(uint8_t)(1u<<(random_word()%8));
            status=af_document_decode(corrupted,encoded_bytes,0,&decoded);
            if (status==AF_DOCUMENT_OK) {
                assert(af_document_encode(&decoded,0,roundtrip,sizeof(roundtrip),&roundtrip_bytes)==0);
                assert(roundtrip_bytes==encoded_bytes && !memcmp(roundtrip,corrupted,encoded_bytes));
            }
            (void)af_document_decode(text,length,0,&decoded);
        }
        {
            uint8_t payload[64], record[96];
            AfRecordView view = {0};
            AfRecordChoice selected = {0};
            size_t written = 77, payload_bytes = 1 + random_word()%64;
            uint32_t record_slot = 1 + random_word()%20;
            for (i = 0; i < sizeof(payload); ++i) payload[i] = (uint8_t)random_word();
            assert(af_record_encode(record_slot, (uint64_t)iteration + 1,
                                    payload, payload_bytes, sizeof(payload),
                                    record, sizeof(record), &written) == AF_RECORD_OK);
            assert(af_record_decode(record, written, record_slot, 64, &view) == AF_RECORD_OK);
            assert(view.bytes == payload_bytes && !memcmp(view.payload, payload, payload_bytes));
            /* 随机字节翻转与任意损坏副本均不得越界。 */
            record[random_word()%written] ^= 1;
            assert(af_record_decode(record, written, record_slot, 64, &view) != AF_RECORD_OK);
            (void)af_record_decode(text, length, record_slot, 64, &view);
            (void)af_record_choose(record, written, text, length, record_slot, 64, &selected);
        }
    }
    assert(af_pipeline_check()==0);
    assert(af_joint_target_check()==0);
    puts("PASS: 20000 native input/state/record/UI/document/CP-prefix/whole-packet/HELLO/runtime/grid/joint/Gamma-domain/complete-asset/color-endpoint probes + native import/rename/export/recovery contracts; ASan+UBSan");
    return 0;
}
