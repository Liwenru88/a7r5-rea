"""版本必须在CP私有拥有者内单调提交；消息诊断变量不能代替它。"""
from pathlib import Path
import subprocess

NATIVE=Path(__file__).resolve().parents[1]/'native'


def test_owner_rejects_stale_even_without_message_diagnostic(tmp_path):
    header=(NATIVE/'af_cp_override406.h').read_text()
    versioned='uint64_t version' in header
    # 旧API适配仅用于复现版本没有传到拥有者；产品不提供此兼容后端。
    call=('af_cp_override406_publish_locked(s,v,slot,p,m)' if versioned else
          '(void)v,af_cp_override406_publish_locked(s,slot,p,m)')
    release=('af_cp_override406_release_locked(s,v,m)' if versioned else
             '(void)v,af_cp_override406_release_locked(s,m)')
    state_version='state.version' if versioned else '0'
    source=r'''
#include "af_cp_override406.h"
#include <assert.h>
#include <string.h>
static int publish(AfCpOverride406 *s,uint64_t v,uint32_t slot,const AfPreset *p,uint8_t *m){return CALL;}
static int release(AfCpOverride406 *s,uint64_t v,uint8_t *m){return RELEASE;}
int main(void){
 AfCpOverride406 state={0};AfPreset a={.base=18,.params={-3,4,-5,2,6,7,3,8}};
 AfPreset b=a;b.params[0]=2;uint8_t marker=0;
 const uint64_t v=UINT64_C(0x100000009);
 assert(publish(&state,v,7,&a,&marker)==AF_OK);
 AfCpOverride406 before=state;marker=0;
 assert(publish(&state,v,7,&b,&marker)==AF_STALE);
 assert(publish(&state,v-1,7,&b,&marker)==AF_STALE);
 assert(release(&state,v,&marker)==AF_STALE);
 assert(!marker&&!memcmp(&state,&before,sizeof(state)));
 assert(release(&state,v+1,&marker)==AF_OK&&state.mode==AF_CP_OVERRIDE_NATIVE);
 before=state;marker=0;
 assert(publish(&state,v,7,&b,&marker)==AF_STALE);
 assert(!marker&&!memcmp(&state,&before,sizeof(state)));
 assert(publish(&state,v+2,7,&b,&marker)==AF_OK);
 assert(VERSION==v+2&&state.preset.params[0]==2);
 AfCpOverride406 edge={0};marker=0;
 assert(publish(&edge,0,7,&a,&marker)==AF_INVALID&&!marker);
 assert(publish(&edge,UINT64_MAX,7,&a,&marker)==AF_OK);
 before=edge;marker=0;
 assert(release(&edge,0,&marker)==AF_INVALID);
 assert(release(&edge,UINT64_MAX,&marker)==AF_STALE);
 assert(!marker&&!memcmp(&edge,&before,sizeof(edge)));
 return 0;
}
'''.replace('CALL',call).replace('RELEASE',release).replace('VERSION',state_version)
    p=tmp_path/'atomic.c';p.write_text(source);binary=tmp_path/'atomic'
    command=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(p),
             *[str(NATIVE/n) for n in ('af_cp_override406.c','af_slots.c','af_cp406_state.c')],'-o',str(binary)]
    build=subprocess.run(command,capture_output=True,text=True)
    assert build.returncode==0,build.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
