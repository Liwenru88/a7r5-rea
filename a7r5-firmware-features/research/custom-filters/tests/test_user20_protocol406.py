"""新20用户槽能力与旧FULL端隔离；不以相同4.06基础SHA替代协议能力。"""
from pathlib import Path
import subprocess

NATIVE = Path(__file__).resolve().parents[1] / 'native'


def test_old_full_handshake_cannot_accept_user20_and_dependent_capability_is_required(tmp_path):
    source = tmp_path / 'capability.c'
    source.write_text(r'''
#include "af_handshake.h"
#include <assert.h>
int main(void){
 AfHandshake client={0},old={0};uint8_t request[128],reply[128];size_t written=41;
 uint32_t legacy=AF_APPLY_PROTOCOL_REQUIRED&~AF_APPLY_CAP_USER20;
 assert(legacy&AF_APPLY_CAP_FULL_RECIPE);
 assert(!af_hs_server_init(&old,legacy));
 assert(!af_hs_begin(&client,71,AF_APPLY_PROTOCOL_REQUIRED,10,100,request));
 assert(af_hs_server(&old,request,128,0x80020002u,reply,128,&written)==1&&!written&&old.state==4&&!old.session);
 assert(af_hs_poll(&client,11)==AF_BUSY);
 /* FULL依赖不能靠单独声明USER20绕过。 */
 AfHandshake invalid={0};uint32_t bad=AF_APPLY_PROTOCOL_REQUIRED&~AF_APPLY_CAP_FULL_RECIPE;
 assert(af_hs_server_init(&invalid,bad)==AF_INVALID&&!invalid.state);
 assert(af_hs_begin(&invalid,72,bad,10,100,request)==AF_INVALID&&!invalid.state);
 /* 旧能力会话仍可保持自己原有的7..20范围，不能冒称20槽已握手。 */
 client=(AfHandshake){0};assert(!af_hs_begin(&client,73,legacy,10,100,request));
 assert(af_hs_server(&old,request,128,0x80020002u,reply,128,&written)==1&&written==128);
 assert(af_hs_client(&client,reply,128,0x90030001u,11)==1&&client.state==2&&client.required==legacy);
 return 0;
}
''')
    binary = source.with_suffix('')
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-DAF_RECIPE_BRIDGE406', '-DAF_FACTORY_RESTORE406', '-DAF_SNAPSHOT_OVERLAY406',
        '-I' + str(NATIVE), str(source), str(NATIVE / 'af_apply_wire.c'),
        str(NATIVE / 'af_handshake.c'), str(NATIVE / 'af_slots.c'), '-o', str(binary)],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
