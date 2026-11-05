"""原厂工作数组整组读取：非零值、当前修改、原数组不写及拒绝不发布。"""
import ctypes as c
from pathlib import Path
import subprocess

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
PROPOSAL=Path(__file__).resolve().parents[1]/'native'


class Preset(c.Structure):
    _fields_=[('base',c.c_uint8),('kind',c.c_uint8),('params',c.c_int8*8),('payload',c.c_uint8*32),('lut',c.c_uint8*32)]


def test_factory_working_snapshot_no_cache_and_fail_without_publication(tmp_path):
    target=tmp_path/'factory.so'
    r=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-I'+str(PROPOSAL),'-I'+str(NATIVE),str(PROPOSAL/'af_factory406.c'),str(NATIVE/'af_slots.c'),'-o',str(target)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    api=c.CDLL(str(target));api.af_factory406_snapshot.argtypes=[c.c_uint32,c.c_void_p,c.c_void_p,c.c_void_p]
    api.af_ap_factory406_snapshot.argtypes=[c.c_size_t,c.c_uint32,c.c_void_p]
    bases=(c.c_uint32*18)(*list(range(10)),0,1,2,3,4,5,10,11)
    arrays=[(c.c_int32*18)(*[((i+p)%19-9) if p in (0,1,2,4) else 1+i%5 if p==6 else (i+p)%10 for i in range(18)]) for p in range(8)]
    pointers=(c.c_void_p*8)(*[c.addressof(x) for x in arrays])
    untouched=[bytes(x) for x in [bases,*arrays,pointers]]
    out=c.create_string_buffer(b'\xa5'*(c.sizeof(Preset)+16));at=c.addressof(out)+8
    for selector in [*range(10),17,18]:
        assert api.af_factory406_snapshot(selector,bases,pointers,at)==0
        p=Preset.from_buffer_copy(out.raw[8:8+c.sizeof(Preset)])
        index=selector if selector<10 else selector-1
        assert p.base==selector and p.kind==0 and list(p.params)==[a[index] for a in arrays]
        assert bytes(p.payload)==bytes(32) and bytes(p.lut)==bytes(32)
        assert out.raw[:8]==b'\xa5'*8 and out.raw[8+c.sizeof(Preset):8+c.sizeof(Preset)+8]==b'\xa5'*8
    assert [bytes(x) for x in [bases,*arrays,pointers]]==untouched
    arrays[0][16]=-7
    assert api.af_factory406_snapshot(17,bases,pointers,at)==0
    assert Preset.from_buffer_copy(out.raw[8:8+c.sizeof(Preset)]).params[0]==-7
    before=out.raw
    for selector in [10,15,16,19,0xffffffff]:
        assert api.af_factory406_snapshot(selector,bases,pointers,at)==-1 and out.raw==before
    bases[16]=0
    assert api.af_factory406_snapshot(17,bases,pointers,at)==-5 and out.raw==before
    bases[16]=10;arrays[6][16]=0
    assert api.af_factory406_snapshot(17,bases,pointers,at)==-1 and out.raw==before
    arrays[6][16]=2
    for alias in [bases,pointers,arrays[0]]:
        saved=bytes(alias)
        assert api.af_factory406_snapshot(17,bases,pointers,alias)==-1 and bytes(alias)==saved
    assert api.af_ap_factory406_snapshot(0,17,at)==-1 and out.raw==before
