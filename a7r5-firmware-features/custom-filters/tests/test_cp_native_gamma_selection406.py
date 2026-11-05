"""产品Gamma组件到原选表／构造的连续软件验证；无ISP或设备后端。"""
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from test_cp_capture_components406 import DRIVER, NATIVE

FEATURE = NATIVE.parent
ROOT = FEATURE.parents[1]
sys.path.insert(0, str(FEATURE))
from a7filters.cp_gamma406 import TABLE, record, setup
from a7filters.cp_machine import WORK, STACK

DRIVER_MAIN = r'''
static AfCatalog catalog;
static AfCpNativeBanks406 native_banks;
static AfCpOverride406 native_override;
static AfCpInput406 native_input;
static AfCpNativeLease406 native_lease;
static uint8_t live_prefix[0xe70],snapshot_prefix[0xe70],worker_prefix[0xe70];
static void memory_copy(void *d,const void *s,size_t n){memcpy(d,s,n);}
static void bind_user_recipe(uint64_t version,unsigned base,unsigned slot,int16_t tone){
 AfPreset preset={.base=(uint8_t)base,.kind=1,.params={0,0,0,0,0,0,3,0}};
 preset.payload_sha256[0]=(uint8_t)version;preset.lut_sha256[0]=(uint8_t)version;
 assert(!af_install(&catalog,slot,&preset,version!=7));
 assert(!af_read(&catalog,slot,0,&preset));
 AfJointAsset full={.base=base,.native_mode=1};full.model_sha256[0]=1;full.native_tone[0]=tone;
 for(unsigned i=0;i<129;++i)full.native_seed[i]=word(record+4*i);
 assert(!af_joint_gamma(full.native_seed,full.native_tone,full.recipe.gamma));
 full.recipe.matrix[0]=7;full.recipe.cc1[0]=13;full.recipe.grid[0]=3;
 uint8_t marker=0;
 assert(!af_cp_native_bank406_accept_locked(&native_banks,&native_override,version,slot,&preset,&full,&marker)&&marker==1);
 assert(!af_cp_override406_snapshot_copy_locked(&native_override,live_prefix,snapshot_prefix,
  AF_CP_INPUT406_SNAPSHOT_BYTES,&native_input,AF_CP_INPUT406_SNAPSHOT,memory_copy));
 put(snapshot_prefix+0xdc0,53);
 assert(!af_cp_copy406_observe(&native_input,worker_prefix,AF_CP_INPUT406_COPY_A,
  snapshot_prefix,AF_CP_INPUT406_SNAPSHOT,sizeof worker_prefix,53,1,memory_copy));
 AfCpInput406Token input;assert(!af_cp_input406_read(&native_input,AF_CP_INPUT406_COPY_A,&input));
 assert(input.version==version&&input.slot==slot&&input.actual.base==base&&input.actual.params[6]==3);
 if(native_lease.ticket)assert(!af_cp_native_bank406_release(&native_banks,&native_lease));
 assert(!af_cp_native_bank406_borrow_locked(&native_banks,&input,2,&native_lease));
 view.input=input;view.lease=native_lease;view.asset=native_lease.asset;view.prefix=worker_prefix;
 assert(view.asset->native_tone[0]==tone&&view.asset->recipe.matrix[0]==7&&
  view.asset->recipe.cc1[0]==13&&view.asset->recipe.grid[0]==3);
}
int main(int argc,char **argv){
 assert(argc==7);unsigned domain=(unsigned)atoi(argv[1]);
 unsigned route=(unsigned)atoi(argv[2]),column=(unsigned)atoi(argv[3]);
 uint32_t selected=(uint32_t)strtoul(argv[4],0,0);int accepted=atoi(argv[6]);
 setup();channel=domain==2;g[0]=(uint8_t)channel;
 FILE *file=fopen(argv[5],"rb");assert(file);
 assert(fread(record,1,sizeof record,file)==sizeof record);assert(!fclose(file));
 unsigned base=route==47?17:route==48?18:0,slot=domain?20:7;
 af_catalog_init(&catalog);bind_user_recipe(7,base,slot,128);publish();stamp();
 selected_record=selected;
 void *out=domain?output[channel]:main_output;
 AfCpCapture406Token scope={0};
 if(domain){assert(!af_cp_capture406_scope_begin(&capture,object+AF_CP_CAPTURE406_G,&scope));construct();
  put(f[channel]+0x30,route);f[channel][0x38]=(uint8_t)column;
 }else{put(main_params+0x30,route);main_params[0x38]=(uint8_t)column;}
 uint32_t result=domain?outer(faddr(channel),channel):
  af_cp_components406_gamma(&component,0,main_params,AF_CP_COMPONENTS406_FORMATTER,out);
 assert(result==(accepted?104u:103u));
 if(accepted){
  assert(fwrite(selected_candidate,1,sizeof selected_candidate,stdout)==sizeof selected_candidate);
  uint8_t first[516];memcpy(first,(uint8_t *)out+0x24c,sizeof first);
  /* 相同原厂参数、不同LUT版本仍重新构表。旧Capture按原已绑定快照处理。 */
  bind_user_recipe(9,base,slot,256);
  result=domain?outer(faddr(channel),channel):
   af_cp_components406_gamma(&component,0,main_params,AF_CP_COMPONENTS406_FORMATTER,out);
  assert(result==104u);
  assert((memcmp(first,(uint8_t *)out+0x24c,sizeof first)==0)==!!domain);
 }else assert(!memcmp((uint8_t *)out+0x24c,record,516));
 if(domain){assert(word((uint8_t *)out+0x450)==0x1234abcd);
  assert(!af_cp_capture406_scope_end(&capture,&scope));
  /* 失去本次原构造来源后不再沿用私有曲线。 */
  assert(outer(faddr(channel),channel)==103u);
 }else{
  assert(!af_cp_native_bank406_clear_active_locked(&native_banks));view.asset=0;
  assert(af_cp_components406_gamma(&component,0,main_params,AF_CP_COMPONENTS406_FORMATTER,out)==103u);
 }
 assert(!memcmp((uint8_t *)out+0x24c,record,516)&&!component.gamma_busy);
 assert(!af_cp_capture406_release(&capture,object));
 assert(!af_cp_native_bank406_release(&native_banks,&native_lease));return 0;
}
'''


def driver_source():
    text = DRIVER.split('int main(int argc,char **argv)')[0]
    patches = (
        ('#include <assert.h>', '#include <assert.h>\n#include <stdio.h>\n#include "af_cp_copy406.h"'),
        ('static uint32_t thread_id=22;',
         'static uint32_t thread_id=22,selected_record;\nstatic uint8_t selected_candidate[576];'),
        ('put(out,0xdcca0c);return AF_OK;',
         'put(out,selected_record?selected_record:0xdcca0c);return AF_OK;'),
        ('if(address==0xdcca0c&&n==sizeof record)',
         'if((address==0xdcca0c||address==selected_record)&&n==sizeof record)'),
        ('memcpy((uint8_t *)out+0x24c,adjusted,516);return 104;',
         'memcpy(selected_candidate,adjusted,576);memcpy((uint8_t *)out+0x24c,adjusted,516);return 104;'),
    )
    for old, new in patches:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text + DRIVER_MAIN


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('native-gamma-selection406')
    source, target = directory / 'driver.c', directory / 'driver'
    source.write_text(driver_source())
    names = ('af_cp_components406.c', 'af_cp_capture406.c', 'af_cp_capture_fields406.c',
             'af_joint.c', 'af_color406.c', 'af_slots.c', 'af_cp_native_bank406.c',
             'af_cp_input406.c', 'af_cp_copy406.c', 'af_cp_override406.c', 'af_cp406_state.c')
    command = ['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-function', '-DAF_CP_CAPTURE406=1', '-DAF_CP_CAPTURE_INPUT406=1', '-I'+str(NATIVE),
               str(source), *[str(NATIVE/name) for name in names], '-o', str(target)]
    run = subprocess.run(command, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return target


@pytest.fixture(scope='module')
def cp():
    source = ROOT / '.local/fixed-custom-filters/integration52-source406/components/cpapp-b.bin'
    if not source.is_file():
        pytest.skip('未准备锁定CP，不能伪造原选表／构造证据')
    return source.read_bytes()


@pytest.mark.parametrize('domain', (0, 1, 2), ids=('main', 'capture0', 'capture1'))
@pytest.mark.parametrize('wire,column', ((0, 6), (19, 0), (19, 6), (20, 0), (20, 6)))
def test_recipe_candidate_enters_original_selected_constructor(binary, cp, tmp_path, domain, wire, column):
    machine, route = setup(cp, wire, column)
    pointer = machine.word(TABLE + route * 28 + column * 4)
    original = record(cp, machine, pointer)
    path = tmp_path / 'original-record.bin'
    path.write_bytes(original)
    run = subprocess.run([str(binary), str(domain), str(route), str(column), hex(pointer),
                          str(path), '1'], capture_output=True, timeout=15)
    assert run.returncode == 0, run.stderr.decode()
    candidate = run.stdout
    assert len(candidate) == 576
    assert candidate[0x204:0x220] == original[0x204:0x220]
    assert candidate[0x224:] == original[0x224:]
    assert candidate[:516] != original[:516]
    assert struct.unpack_from('<I', candidate, 0x220)[0] == struct.unpack_from('<I', candidate, 512)[0]
    # 仅在隔离RAM中的原选表项指向产品组件实际生成的候选；CP输入文件不变。
    machine.put(WORK + 0x8000, candidate)
    machine.word(TABLE + route * 28 + column * 4, WORK + 0x8000)
    output = WORK + 0x4000
    machine.put(output - 16, b'\xa5' * (0x800 + 32))
    result = machine.run(0x41363c, arguments=(int(domain != 0), WORK + 0x2000, output), limit=100000)
    assert result['status'] == 'RETURNED'
    assert machine.read(output + 0x24c, 516) == candidate[:516]
    assert machine.read(output - 16, 16) == machine.read(output + 0x800, 16) == b'\xa5' * 16
    for item in machine.writes:
        at = int(item['address'], 16)
        assert any(lo <= at < at + item['bytes'] <= hi for lo, hi in (
            (output, output + 0x800), (STACK, STACK + 0x10000)))


@pytest.mark.parametrize('domain', (0, 1, 2))
@pytest.mark.parametrize('route,column,pointer', (
    (47, 0, 0x1195084), (47, 6, 0x1195080), (48, 0, 0xbefdc0),
    (48, 6, 0xbefb80), (0, 6, 0x1a39dbc), (47, 0, 0x1a39000), (48, 0, 0xbef9c8)))
def test_wrong_inherited_record_keeps_original_result(binary, tmp_path, domain, route, column, pointer):
    raw = bytearray(576)
    struct.pack_into('<129I', raw, 0, *[i * 1000 for i in range(129)])
    struct.pack_into('<I', raw, 0x220, 128000)
    path = tmp_path / 'record.bin'
    path.write_bytes(raw)
    run = subprocess.run([str(binary), str(domain), str(route), str(column), hex(pointer),
                          str(path), '0'], capture_output=True, timeout=15)
    assert run.returncode == 0, run.stderr.decode()
    assert run.stdout == b''
