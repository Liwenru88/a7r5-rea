"""实际snapshot-copy胶合的主机顺序／失败证据；原memcpy为显式端口。"""
from pathlib import Path
import subprocess

NATIVE=Path(__file__).resolve().parents[1]/'native'


def test_real_copy_busy_override_publish_and_original_fallback(tmp_path):
    source=tmp_path/'copy.c'
    source.write_text(r'''
#include "af_cp_override406.h"
#include "af_cp_input406.h"
#include <assert.h>
#include <string.h>
static AfCpInput406 input;
static AfCpOverride406 state;
static unsigned calls;
static int expected_read=AF_BUSY;
static uint8_t native[AF_CP406_STATE_BYTES],destination[AF_CP406_STATE_BYTES];
static void original_copy(void *out,const void *in,size_t bytes){
 AfCpInput406Token token;
 int result=af_cp_input406_read(&input,AF_CP_INPUT406_SNAPSHOT,&token);
 assert(result==expected_read);
 ++calls;memcpy(out,in,bytes);
 assert(!memcmp(out,native,bytes));
 /* 还在原copy期间，绝不能读到已发布的私有版本。 */
 assert(af_cp_input406_read(&input,AF_CP_INPUT406_SNAPSHOT,&token)==result);
}
static int capture(void){
 return af_cp_override406_snapshot_copy_locked(&state,native,destination,sizeof native,
  &input,AF_CP_INPUT406_SNAPSHOT,original_copy);
}
int main(void){
 uint8_t marker=0;AfCpInput406Token a,b;
 AfPreset raw={.base=0};raw.params[6]=3;
 assert(!af_cp406_write_state(&raw,native,sizeof native,&marker));
 assert(!capture()&&calls==1&&!memcmp(native,destination,sizeof native));
 assert(!af_cp_input406_read(&input,AF_CP_INPUT406_SNAPSHOT,&a)&&!a.version&&!a.flags);
 AfPreset selected={.base=18,.params={-3,4,-5,2,6,7,3,8}};
 assert(!af_cp_override406_publish_locked(&state,11,7,&selected,&marker));
 assert(!capture()&&calls==2&&destination[0xa40]==20&&destination[0xa44]==(uint8_t)-3);
 assert(!af_cp_input406_read(&input,AF_CP_INPUT406_SNAPSHOT,&a)&&a.version==11&&a.slot==7);
 assert(a.flags==AF_CP_INPUT406_USER_VERSION&&!memcmp(&a.actual,&selected,sizeof selected));
 assert(!af_cp_override406_publish_locked(&state,12,7,&selected,&marker));
 assert(!capture()&&calls==3);
 assert(!af_cp_input406_read(&input,AF_CP_INPUT406_SNAPSHOT,&b)&&b.version==12&&b.epoch!=a.epoch);
 assert(!memcmp(&a.actual,&b.actual,sizeof selected));
 /* 私有故障后的原厂copy同样先撤销旧USER tag，不得留下同九值旧LUT资格。 */
 assert(af_cp_override406_snapshot_copy_locked(0,native,destination,sizeof native,
  &input,AF_CP_INPUT406_SNAPSHOT,original_copy)==AF_IO&&calls==4);
 assert(!memcmp(native,destination,sizeof native));
 assert(af_cp_input406_read(&input,AF_CP_INPUT406_SNAPSHOT,&b)==AF_EMPTY);
 assert(!capture()&&calls==5);
 AfCpInput406Write pending;
 assert(!af_cp_input406_snapshot_begin(&input,AF_CP_INPUT406_SNAPSHOT,sizeof native,&pending));
 /* 违反唯一写者约束的重入会关闭整个目的资格，不允许旧票据稍后错误发布。 */
 expected_read=AF_EMPTY;
 assert(capture()==AF_BUSY&&calls==6&&destination[0xa40]==20);
 assert(af_cp_input406_read(&input,AF_CP_INPUT406_SNAPSHOT,&b)==AF_EMPTY);
 assert(af_cp_input406_snapshot_end(&input,&pending,12,7,AF_CP_OVERRIDE_USER,&selected,destination,sizeof destination)==AF_STALE);
 expected_read=AF_BUSY;assert(!capture()&&calls==7);
 /* 追踪耗尽也必须原样完成原copy和已授权的九字段覆盖，不发布来源成功。 */
 input.records[0].sequence=UINT32_MAX;
 expected_read=AF_EXHAUSTED;
 assert(capture()==AF_EXHAUSTED&&calls==8&&destination[0xa40]==20);
 assert(af_cp_input406_read(&input,AF_CP_INPUT406_SNAPSHOT,&b)==AF_EXHAUSTED);
 return 0;
}
''')
    binary=tmp_path/'copy'
    command=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-DAF_CP_CAPTURE_INPUT406=1',
             '-DAF_CP_CARVE_BRANCH406=1','-I'+str(NATIVE),str(source),
             *[str(NATIVE/name) for name in ('af_cp_input406.c','af_cp_override406.c','af_cp406_state.c','af_slots.c')],
             '-o',str(binary)]
    built=subprocess.run(command,capture_output=True,text=True)
    assert built.returncode==0,built.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
