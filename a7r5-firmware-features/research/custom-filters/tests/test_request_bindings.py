"""宿主只验证原导入准备/失败不发布；不调用原AP函数。"""
from pathlib import Path
import ctypes as c
import mmap
import subprocess

HERE=Path(__file__).resolve().parents[1]
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
class Binding(c.Structure):
    _fields_=[('version',c.c_uint32),('bytes',c.c_uint32),('base',c.c_size_t),('span',c.c_size_t),('init',c.c_size_t),('sha',c.c_ubyte*32)]
class Check(c.Structure):_fields_=[('offset',c.c_uint32),('words',c.c_uint32*4)]

def test_actual_binding_table_prepare_and_failed_preimage_does_not_publish(tmp_path):
    stub=tmp_path/'exits.c';stub.write_text('#include <stdint.h>\n'+''.join('const uint32_t '+n+'[1]={0xd42080c0u};\n' for n in ['af_ap_hs_original_return','af_ap_hs_owned_return','af_ap_receive_return','af_ap_receive_loop'])+'extern uintptr_t af_ap_requests_targets[11];\nuintptr_t af_test_target(unsigned i){return af_ap_requests_targets[i];}\n')
    so=tmp_path/'bindings.so'
    r=subprocess.run(['clang','-shared','-fPIC','-O2','-std=c11','-Wall','-Wextra','-Werror',
        '-I'+str(HERE/'native'),'-I'+str(ROOT/'a7r5-firmware-features/custom-filters/native'),
        str(HERE/'native/af_ap_requests_binding.c'),str(stub),'-o',str(so)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    api=c.CDLL(str(so));api.af_ap_requests_resolve.argtypes=[c.c_void_p,c.c_void_p]
    api.af_ap_requests_bind.argtypes=[c.c_void_p]
    api.af_test_target.argtypes=[c.c_uint];api.af_test_target.restype=c.c_size_t
    checks=(Check*16).in_dll(api,'af_ap_requests_checks')
    with mmap.mmap(-1,0x8e84000) as memory:
        base=c.addressof(c.c_char.from_buffer(memory))
        for check in checks:
            memory[check.offset:check.offset+16]=bytes(check.words)
        b=Binding(1,c.sizeof(Binding),base,0x8e84000,base+0x17feac0)
        b.sha[:]=bytes.fromhex('d15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9')
        out=(c.c_size_t*11)(*([0xaaaa]*11))
        assert api.af_ap_requests_resolve(c.byref(b),out)==0
        assert list(out)==[base+check.offset for check in checks[:11]]
        before=bytes(out);memory[checks[3].offset+4]^=1
        assert api.af_ap_requests_resolve(c.byref(b),out)==-5 and bytes(out)==before
        memory[checks[3].offset+4]^=1
        for field,value in [('base',0),('span',1),('init',base+4),('version',2)]:
            previous=getattr(b,field);setattr(b,field,value)
            assert api.af_ap_requests_resolve(c.byref(b),out)==-1 and bytes(out)==before
            setattr(b,field,previous)
        b.sha[0]^=1;assert api.af_ap_requests_resolve(c.byref(b),out)==-1 and bytes(out)==before
        b.sha[0]^=1
        assert api.af_ap_requests_resolve(c.byref(b),c.byref(b))==-1
        assert api.af_ap_requests_resolve(c.byref(b),base+checks[0].offset)==-1
        assert api.af_ap_requests_bind(None)==-1
        assert [api.af_test_target(i) for i in range(11)]==[0]*11
