"""原默认UTF8策略的只读guard和有界中文文件路由；宿主替身不等于原FS执行。"""
from pathlib import Path
import ctypes as c
import json,struct,subprocess
import pytest
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if(p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native';LOCAL=HERE.parent/'native'
@pytest.fixture(scope='module')
def built(tmp_path_factory):
 out=tmp_path_factory.mktemp('fsys406-utf8');common=['clang','-std=c11','-O2','-fno-builtin','-Wall','-Wextra','-Werror',f'-I{LOCAL}',f'-I{NATIVE}',str(LOCAL/'af_fsys406.c'),str(NATIVE/'af_sha256.c')]
 for tail in ([str(HERE/'fsys406_utf8_contract.c'),'-o',str(out/'contract')],['-shared','-fPIC','-o',str(out/'guard.so')]):
  r=subprocess.run(common+tail,capture_output=True,text=True);assert r.returncode==0,r.stderr
 lib=c.CDLL(str(out/'guard.so'));lib.af_fsys406_utf8_policy.argtypes=[c.c_size_t,c.c_size_t]
 return out/'contract',lib
@pytest.mark.parametrize('name',['中文-暖调.CUBE','清晰-🎨.cube','é-e\u0301.cube','中'*40+'aa.cube'])
def test_unicode_names_roundtrip_byte_exact_after_policy(built,name):
 r=subprocess.run([str(built[0]),'0',name.encode().hex()],capture_output=True,text=True);assert r.returncode==0,r.stderr
@pytest.mark.parametrize('name',[b'\xc0\xaf.cube',b'\xe0\x80\x80.cube',b'\xed\xa0\x80.cube',b'\xf4\x90\x80\x80.cube',b'\xe4\xb8.cube',b'\x80.cube',b'\xc2\x85.cube',b'\x1f.cube','\u2028.cube'.encode(),('中'*41+'.cube').encode(),b'../x.cube',b'A:x.cube',b'x?.cube',b'x*.cube',b'x\\y.cube'])
def test_bad_utf8_controls_path_wildcards_and_128_bytes_rejected(built,name):
 r=subprocess.run([str(built[0]),'1',name.hex()],capture_output=True,text=True);assert r.returncode==0,r.stderr
@pytest.mark.parametrize('case',[2,3,4,5,6])
def test_policy_before_after_failures_and_write_alias_never_publish(built,case):
 r=subprocess.run([str(built[0]),str(case)],capture_output=True,text=True);assert r.returncode==0,r.stderr

def test_runtime_guard_checks_exact_source_windows_and_current_converters(built):
 f=json.loads((HERE/'fixtures/fsys406-encoding.json').read_text());span=f['virtual_span'];raw=c.create_string_buffer(span+4095);base=(c.addressof(raw)+4095)&~4095
 def put(off,data):c.memmove(base+off,data,len(data))
 for e in f['helper_reads']['code']:put(e['offset'],bytes.fromhex(e['hex']))
 g=f['helper_reads']['got'];m=f['helper_reads']['module'];put(g['offset'],struct.pack('<Q',base+g['expected_relative_pointer']));put(m['offset'],struct.pack('<I',1))
 for i,off in enumerate(m['converter_offsets']):put(m['offset']+m['converters_offset']+8*i,struct.pack('<Q',base+off))
 guard=built[1].af_fsys406_utf8_policy;assert guard(base,span)==0
 mutations=[(g['offset'],8),(m['offset'],4)]+[(m['offset']+m['converters_offset']+8*i,8)for i in range(6)]+[(e['offset'],1)for e in f['helper_reads']['code']]
 for off,n in mutations:
  before=c.string_at(base+off,n);put(off,bytes([before[0]^1])+before[1:]);assert guard(base,span)==-5;put(off,before);assert guard(base,span)==0
 assert guard(base,span-1)==-1 and guard(base+1,span)==-1
