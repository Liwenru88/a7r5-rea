"""纯宿主验证：旧消息晚到隔离、原路径恢复、失败不发布；不执行固件。"""
from pathlib import Path
import ctypes as C
import subprocess
import pytest

ROOT=next(p for p in Path(__file__).resolve().parents
          if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
PROPOSAL=Path(__file__).resolve().parents[1]/'native'
SIZE=0xDBC
FIELDS=[0xA44,0xA46,0xA45,0xA47,0xA48,0xD2E,0xD2F,0xD30]

class Preset(C.Structure):
    _fields_=[('base',C.c_uint8),('kind',C.c_uint8),('params',C.c_int8*8),
              ('payload',C.c_uint8*32),('lut',C.c_uint8*32)]
class State(C.Structure):
    _fields_=[('mode',C.c_uint32),('slot',C.c_uint32),('preset',Preset),('version',C.c_uint64)]

def preset(base=18,values=(-3,4,-5,2,6,7,3,8)):
    p=Preset();p.base=base;p.params[:]=values;return p
def raw(p): return C.string_at(C.addressof(p),C.sizeof(p))
def buf(value): return (C.c_uint8*SIZE)(*([value]*SIZE))
def fields(b): return bytes(b[0xA40:0xA44])+bytes(b[i] for i in FIELDS)

@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    d=tmp_path_factory.mktemp('cp-override');target=d/'module.dylib'
    cmd=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
         '-I'+str(PROPOSAL),'-I'+str(NATIVE),str(PROPOSAL/'af_cp_override406.c'),
         str(NATIVE/'af_slots.c'),str(NATIVE/'af_cp406_state.c'),'-o',str(target)]
    r=subprocess.run(cmd,capture_output=True,text=True);assert r.returncode==0,r.stderr
    m=C.CDLL(str(target))
    m.af_cp_override406_publish_locked.argtypes=[C.POINTER(State),C.c_uint64,C.c_uint32,C.POINTER(Preset),C.c_void_p]
    m.af_cp_override406_release_locked.argtypes=[C.POINTER(State),C.c_uint64,C.c_void_p]
    m.af_cp_override406_snapshot_locked.argtypes=[C.POINTER(State),C.c_void_p,C.c_void_p,C.c_size_t]
    m.af_cp_override406_release.argtypes=[C.c_uint64]
    m.af_cp_override406_hook_matches.argtypes=[C.c_void_p,C.c_size_t,C.c_uint32]
    m.af_cp406_write_state.argtypes=[C.POINTER(Preset),C.c_void_p,C.c_size_t,C.c_void_p]
    return m

def test_late_native_messages_do_not_replace_user_copy(lib):
    state=State();p=preset();late=preset(17,(2,-3,4,1,-6,3,5,2));marker=C.c_uint8()
    native=buf(0xA5);dst=buf(0);before=bytes(native)
    assert lib.af_cp_override406_publish_locked(C.byref(state),1,7,C.byref(p),C.byref(marker))==0
    assert marker.value==1 and bytes(native)==before
    # 反例：原直接写输入的方法，晚到原九消息能够整体覆盖用户值。
    assert lib.af_cp406_write_state(C.byref(p),native,SIZE,C.byref(marker))==0
    wanted=fields(native)
    assert lib.af_cp406_write_state(C.byref(late),native,SIZE,C.byref(marker))==0
    assert fields(native)!=wanted
    for value in (late,preset(1,(9,-9,7,5,-8,1,2,0))):
        assert lib.af_cp406_write_state(C.byref(value),native,SIZE,C.byref(marker))==0
        native_before=bytes(native);C.memmove(dst,native,SIZE)
        assert lib.af_cp_override406_snapshot_locked(C.byref(state),native,dst,SIZE)==0
        assert fields(dst)==wanted and bytes(native)==native_before and state.mode==1
        changed={0xA40,0xA41,0xA42,0xA43,*FIELDS}
        assert all(dst[i]==native[i] for i in range(SIZE) if i not in changed)
    assert lib.af_cp_override406_release_locked(C.byref(state),2,C.byref(marker))==0
    C.memmove(dst,native,SIZE)
    assert lib.af_cp_override406_snapshot_locked(C.byref(state),native,dst,SIZE)==0
    assert state.mode==0 and state.slot==0 and bytes(dst)==bytes(native)

def test_factory_pending_waits_for_all_nine_native_values(lib):
    s=State();p=preset(17);native=buf(0x55);dst=buf(0);marker=C.c_uint8()
    assert lib.af_cp_override406_publish_locked(C.byref(s),1,0,C.byref(p),C.byref(marker))==0
    assert s.mode==2
    C.memmove(dst,native,SIZE)
    assert lib.af_cp_override406_snapshot_locked(C.byref(s),native,dst,SIZE)==0 and s.mode==2
    expected=fields(dst)
    assert lib.af_cp406_write_state(C.byref(p),native,SIZE,C.byref(marker))==0
    native[FIELDS[-1]]^=1;C.memmove(dst,native,SIZE)
    assert lib.af_cp_override406_snapshot_locked(C.byref(s),native,dst,SIZE)==0 and s.mode==2
    assert fields(dst)==expected
    native[FIELDS[-1]]^=1;C.memmove(dst,native,SIZE)
    assert lib.af_cp_override406_snapshot_locked(C.byref(s),native,dst,SIZE)==0
    assert s.mode==0 and s.slot==0 and bytes(dst)==bytes(native)

def test_invalid_alias_and_uninstalled_target_do_not_publish(lib):
    s=State();p=preset();marker=C.c_uint8(0x72);native=buf(0x5A);dst=buf(0xA6)
    for slot,kind,value in [(21,0,3),(7,1,3),(7,0,42)]:
        p.kind=kind;p.params[0]=value;before=(raw(s),marker.value,bytes(dst))
        assert lib.af_cp_override406_publish_locked(C.byref(s),1,slot,C.byref(p),C.byref(marker))==-1
        assert before==(raw(s),marker.value,bytes(dst))
    p=preset();assert lib.af_cp_override406_publish_locked(C.byref(s),1,7,C.byref(p),C.byref(marker))==0
    before=(raw(s),bytes(dst),bytes(native))
    for n,dest in [(SIZE-1,dst),(SIZE,native),(SIZE,C.byref(s))]:
        assert lib.af_cp_override406_snapshot_locked(C.byref(s),native,dest,n)==-1
        assert before==(raw(s),bytes(dst),bytes(native))
    assert lib.af_cp_override406_publish_locked(C.byref(s),2,7,C.byref(s.preset),C.byref(marker))==-1
    assert lib.af_cp_override406_release_locked(C.byref(s),2,C.byref(s))==-1
    assert raw(s)==before[0]
    assert lib.af_cp_override406_ready()==0 and lib.af_cp_override406_release(1)==-6

def test_hook_guard_rejects_old_partial_wrong_and_surrounding_code(lib):
    # 同CP18b265；完整原函数，不从当前被测C表构造预期。
    original=bytes.fromhex('f0b503af4df804bd0646242020f500edf8b94af61021304640f6bc52c0f257115cf528ee4bf2d070c0f25710c16869b94bf2e07cc0f2571cdcf80c2032b1624692e83a003ac00020ccf80c00242020f5bce9d2f160fe58b9d6f82002032807d1d6f868070338012802d80220c6f868075df804bbf0bd')
    old=(C.c_uint8*len(original)).from_buffer_copy(original);gate=0x92000001
    assert lib.af_cp_override406_hook_matches(old,len(original),gate)==0
    installed=bytearray(original);installed[36:44]=bytes.fromhex('dff800f0')+gate.to_bytes(4,'little')
    good=(C.c_uint8*len(installed)).from_buffer_copy(installed)
    assert lib.af_cp_override406_hook_matches(good,len(installed),gate)==1
    assert lib.af_cp_override406_hook_matches(good,len(installed)-1,gate)==0
    assert lib.af_cp_override406_hook_matches(good,len(installed),gate+2)==0
    assert lib.af_cp_override406_hook_matches(good,len(installed),gate&~1)==0
    for at in [0,35,44,117]:
        broken=bytearray(installed);broken[at]^=1
        data=(C.c_uint8*len(broken)).from_buffer_copy(broken)
        assert lib.af_cp_override406_hook_matches(data,len(broken),gate)==0

def test_carved_branch_requires_complete_original_surroundings(tmp_path):
    target=tmp_path/'branch.dylib'
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        '-DAF_CP_CARVE_BRANCH406=1','-I'+str(NATIVE),str(NATIVE/'af_cp_override406.c'),
        str(NATIVE/'af_slots.c'),'-o',str(target)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    api=C.CDLL(str(target));api.af_cp_override406_hook_matches.argtypes=[C.c_void_p,C.c_size_t,C.c_uint32]
    original=bytearray.fromhex('f0b503af4df804bd0646242020f500edf8b94af61021304640f6bc52c0f257115cf528ee4bf2d070c0f25710c16869b94bf2e07cc0f2571cdcf80c2032b1624692e83a003ac00020ccf80c00242020f5bce9d2f160fe58b9d6f82002032807d1d6f868070338012802d80220c6f868075df804bbf0bd')
    gate=0xbefa39
    delta=(gate&~1)-0x898570
    sign=(delta>>24)&1
    upper=0xf000|(sign<<10)|((delta>>12)&0x3ff)
    lower=0x9000|((~((delta>>23)^sign)&1)<<13)|((~((delta>>22)^sign)&1)<<11)|((delta>>1)&0x7ff)
    installed=original[:];installed[36:40]=upper.to_bytes(2,'little')+lower.to_bytes(2,'little')
    def check(raw,entry=gate):
        return api.af_cp_override406_hook_matches(C.create_string_buffer(bytes(raw)),len(raw),entry)
    assert check(installed)==1 and check(original)==0
    assert check(installed,gate+2)==0 and check(installed,gate&~1)==0
    assert check(installed,0x92000001)==0
    for position in (0,35,39,40,43,44,117):
        broken=installed[:];broken[position]^=1
        assert check(broken)==0
    absolute=original[:];absolute[36:44]=bytes.fromhex('dff800f0')+gate.to_bytes(4,'little')
    assert check(absolute)==0
