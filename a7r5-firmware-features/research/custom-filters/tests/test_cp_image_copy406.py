"""三个真实E70包装器的复制端口行为与Thumb入口静态ABI。"""
from pathlib import Path
import subprocess

NATIVE = Path(__file__).resolve().parents[1] / 'native'


def test_image_copy_preserves_original_and_tracks_only_matching_source(tmp_path):
    source = tmp_path/'image-copy.c'
    source.write_text(r'''
#include "af_cp_copy406.h"
#include <assert.h>
#include <string.h>
static AfCpInput406 input;
static unsigned calls,refresh;
static uint8_t raw[AF_CP_INPUT406_COPY_BYTES],out[sizeof raw];
static uint32_t logical_destination=AF_CP_INPUT406_COPY_A;
static int during=AF_BUSY;
static AfPreset selected={.base=17,.params={-3,4,-5,2,6,7,3,8}};
static void snapshot(uint64_t version){
 AfCpInput406Write t;uint8_t marker=0;
 assert(!af_cp_input406_snapshot_begin(&input,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&t));
 assert(!af_cp406_write_state(&selected,raw,AF_CP_INPUT406_SNAPSHOT_BYTES,&marker));
 assert(!af_cp_input406_snapshot_end(&input,&t,version,7,AF_CP_OVERRIDE_USER,&selected,raw,AF_CP_INPUT406_SNAPSHOT_BYTES));
}
static void original(void *dst,const void *src,size_t n){
 AfCpInput406Token token;
 assert(af_cp_input406_read(&input,logical_destination,&token)==during);
 ++calls;memcpy(dst,src,n);
 if(refresh)snapshot(refresh);
}
static int copy(unsigned allow,unsigned vd){
 return af_cp_copy406_observe(&input,out,logical_destination,raw,AF_CP_INPUT406_SNAPSHOT,
  sizeof raw,vd,allow,original);
}
int main(void){
 memset(raw,0x5a,sizeof raw);snapshot(11);
 raw[AF_CP_INPUT406_VD_OFFSET]=0x31;raw[AF_CP_INPUT406_VD_OFFSET+1]=0x42;
 raw[AF_CP_INPUT406_VD_OFFSET+2]=raw[AF_CP_INPUT406_VD_OFFSET+3]=0;
 assert(!copy(1,0x4231)&&calls==1&&!memcmp(out,raw,sizeof out));
 AfCpInput406Token t;
 assert(!af_cp_input406_read(&input,logical_destination,&t)&&t.version==11&&t.native_vd==0x4231);
 assert(t.flags==(AF_CP_INPUT406_USER_VERSION|AF_CP_INPUT406_VD_VALID));
 /* 同九字段的新版本在copy期间刷新，原copy保留，旧资格拒绝。 */
 refresh=12;assert(copy(1,0x4231)==AF_STALE&&calls==2);refresh=0;
 assert(af_cp_input406_read(&input,logical_destination,&t)==AF_EMPTY);
 assert(!copy(1,0x4231)&&calls==3);
 assert(af_cp_input406_read(&input,logical_destination,&t)==AF_OK&&t.version==12);
 /* 故障/未知入口不再授予资格，原厂完整字节始终只复制一次。 */
 during=AF_EMPTY;
 assert(copy(0,0x4231)==AF_INVALID&&calls==4&&!memcmp(out,raw,sizeof out));
 assert(af_cp_input406_read(&input,logical_destination,&t)==AF_EMPTY);
 during=AF_BUSY;
 logical_destination=AF_CP_INPUT406_COPY_B;
 assert(copy(1,0x4232)==AF_STALE&&calls==5&&!memcmp(out,raw,sizeof out));
 assert(af_cp_input406_read(&input,logical_destination,&t)==AF_EMPTY);
 assert(!copy(1,0x4231)&&calls==6);
 assert(!af_cp_input406_read(&input,logical_destination,&t)&&t.version==12);
 /* 地址别名不会在验证前损坏观察器或复制内存。 */
 assert(af_cp_copy406_observe(&input,raw,logical_destination,raw,AF_CP_INPUT406_SNAPSHOT,
  sizeof raw,0x4231,1,original)==AF_INVALID&&calls==6);
 return 0;
}
''')
    binary=tmp_path/'image-copy'
    built=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),
        str(source),*[str(NATIVE/n) for n in ('af_cp_copy406.c','af_cp_input406.c','af_cp406_state.c','af_slots.c')],
        '-o',str(binary)],capture_output=True,text=True)
    assert built.returncode==0,built.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
