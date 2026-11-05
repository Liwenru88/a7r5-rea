"""FNV槽压缩的完整静态CFG与独立宿主数学对照，不执行ARM。"""
from pathlib import Path
import ctypes
import importlib.util
import random
import subprocess
import pytest

HERE=Path(__file__).resolve().parents[1]/'experiments/packaging406/cp_carve406'


def module():
    spec=importlib.util.spec_from_file_location('checker_static_layout',HERE/'capture_layout.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


@pytest.fixture(scope='module')
def checker(tmp_path_factory):
    api=module();original=api.source()[0xbef5c0-api.BASE:0xbef620-api.BASE]
    output=tmp_path_factory.mktemp('checker-static')
    header=['#define AF_CAPTURE_PHASE_ENTRY 0xbef818']
    header += ['#define AF_CAPTURE_'+name+'_TARGET 0x2aef001' for name in api.TARGETS]
    (output/'native_capture_constants.h').write_text('\n'.join(header)+'\n')
    obj=output/'aux.o'
    run=subprocess.run(['clang','--target=armv7a-none-eabi','-mthumb','-march=armv7-a',
        '-I'+str(output),'-c',str(HERE/'bootstrap/capture_aux.S'),'-o',str(obj)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    from elftools.elf.elffile import ELFFile
    with obj.open('rb')as stream:
        candidate=ELFFile(stream).get_section_by_name('.text.capture_checker').data()
    return api,original,candidate,output


def test_complete_original_and_rewritten_checker_have_equal_cfg(checker):
    api,original,candidate,_=checker
    result=api.validate_checker(original,candidate)
    assert result['checker_bytes']==80 and result['literal_bytes']==20
    assert result['normalized_operations']==27
    assert result['gate_address']==0xbef610 and result['record_address']==0xbef618


@pytest.mark.parametrize('offset',[0,20,36,44,48,60,68,76],
                         ids=['stack','address-flags','byte-step','count-step','condition','prefix','version','fnv-prime'])
def test_checker_mutation_cannot_pass_equivalence(checker,offset):
    api,original,candidate,_=checker
    changed=bytearray(candidate);changed[offset]^=1
    with pytest.raises(ValueError):
        api.validate_checker(original,bytes(changed))


def test_host_unsigned_fnv_math_matches_original_integer_spec(checker):
    _,_,_,output=checker
    # 只编译宿主C数学参照，既不翻译也不执行ARM指令。
    src=output/'fnv.c';lib=output/'fnv.so'
    src.write_text('''#include <stdint.h>
uint32_t fnv(const uint8_t *p) {
 uint32_t v=UINT32_C(2166136261);
 for(unsigned i=0;i<1215;++i)v=(v^p[i])*UINT32_C(16777619);
 return v;
}
''')
    run=subprocess.run(['cc','-shared','-fPIC',str(src),'-o',str(lib)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    native=ctypes.CDLL(str(lib));native.fnv.argtypes=[ctypes.POINTER(ctypes.c_ubyte)];native.fnv.restype=ctypes.c_uint32
    rng=random.Random(0x406)
    samples=[bytes([n])*1215 for n in range(256)] + [rng.randbytes(1215) for _ in range(32)]
    for data in samples:
        expected=2166136261
        for byte in data:expected=((expected^byte)*16777619)&0xffffffff
        buf=(ctypes.c_ubyte*1215).from_buffer_copy(data)
        assert native.fnv(buf)==expected
