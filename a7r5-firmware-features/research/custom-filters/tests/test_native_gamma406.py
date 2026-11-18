"""非均匀采样、区间和原曲线替换契约；硬件插值另行验证。"""
import ctypes as c
from pathlib import Path
import struct
import subprocess
import sys

import pytest

HOME=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOME))


class Span(c.Structure):
    _fields_=[('left',c.c_uint32),('right',c.c_uint32),('offset',c.c_uint32),('width',c.c_uint32)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    target=tmp_path_factory.mktemp('gamma406')/'native.so'
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        str(HOME/'native/af_gamma406.c'),'-o',str(target)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    result=c.CDLL(str(target))
    result.af_gamma406_axis.argtypes=[c.c_void_p,c.c_void_p]
    result.af_gamma406_locate.argtypes=[c.c_void_p,c.c_uint32,c.c_void_p]
    result.af_gamma406_replace.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p]
    return result


def source():
    raw=bytearray([0x6a]*576)
    struct.pack_into('<129I',raw,0,*[i*1023 for i in range(129)])
    raw[0x204:0x210]=bytes((0,0,1,2,3,4,5,4,3,4,4,3))
    struct.pack_into('<I',raw,0x220,128*1023)
    return raw


def test_native_axis_is_piecewise_not_uniform_and_locates_boundary_codes(api):
    raw=c.create_string_buffer(bytes(source()));axis=(c.c_uint32*129)()
    expected=list(range(0,2049,32))+list(range(2176,4097,128))+list(range(4608,8193,512))+list(range(8704,16385,512))+list(range(17408,32769,1024))+list(range(36864,61441,4096))+[65535]
    assert len(expected)==129
    assert api.af_gamma406_axis(raw,axis)==0 and list(axis)==expected
    for value in (0,1,31,32,2048,2049,61440,65534,65535):
        out=Span();assert api.af_gamma406_locate(axis,value,c.byref(out))==0
        left=max(i for i,x in enumerate(expected[:-1]) if x<=value)
        assert (out.left,out.right,out.offset,out.width)==(left,left+1,value-expected[left],expected[left+1]-expected[left])
    out=Span(77,77,77,77);before=bytes(out)
    assert api.af_gamma406_locate(axis,65536,c.byref(out))==-1 and bytes(out)==before


def test_direct_curve_replace_preserves_source_axis_and_all_ancillary_fields(api):
    raw=source();source_buffer=c.create_string_buffer(bytes(raw));curve=(c.c_uint32*129)(*[(i*i*200001)//16384 for i in range(129)])
    output=c.create_string_buffer(b'\xa5'*576,576)
    assert api.af_gamma406_replace(source_buffer,curve,output)==0
    expected=bytearray(raw);struct.pack_into('<129I',expected,0,*curve);struct.pack_into('<I',expected,0x220,curve[-1])
    assert output.raw==expected and source_buffer.raw[:-1]==raw
    before=output.raw;curve[90]=262144
    assert api.af_gamma406_replace(source_buffer,curve,output)==-1 and output.raw==before
    assert api.af_gamma406_replace(source_buffer,curve,source_buffer)==-1


@pytest.mark.parametrize('kind',('zero_step','wrong_count','nonmonotone'))
def test_bad_source_metadata_never_publishes_a_partial_axis(api,kind):
    raw=source()
    if kind=='zero_step':raw[0x204]=16
    elif kind=='wrong_count':raw[0x204]=1
    else:struct.pack_into('<I',raw,40,0)
    result=(c.c_uint32*129)(*([0xa5a5a5a5]*129));before=bytes(result)
    assert api.af_gamma406_axis(c.create_string_buffer(bytes(raw)),result)==-1
    assert bytes(result)==before


def test_gamma_source_checked_before_accessing_executor():
    from a7filters import cp_gamma406
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):
        cp_gamma406.collect(b'changed CP',object())


def test_optional_gamma_symbols_must_be_in_declared_range_before_cpu(monkeypatch):
    from a7filters.native_joint import JointMachine
    import elftools.elf.elffile
    import unicorn
    # 仅隔离ELF元数据门槛，不能作为任何实际ELF/CP执行证据。
    class Symbol(dict):
        def __init__(self,name,value):
            super().__init__(st_value=value,st_shndx=1);self.name=name
    names=('af_joint_gamma_record','af_joint_expand_matrix','af_joint_target_check',
           'af_joint_target_report','af_joint_target_metrics','af_gamma406_axis',
           'af_gamma406_locate','af_gamma406_replace')
    class Table:
        def iter_symbols(self):
            return [Symbol(name,0x90000000 if name=='af_gamma406_locate' else 0x9080000+i*4) for i,name in enumerate(names)]
    class Elf(dict):
        little_endian=True
        def __init__(self):super().__init__(e_machine='EM_AARCH64',e_type='ET_EXEC')
        def iter_sections(self):return []
        def get_section_by_name(self,name):return Table()
    monkeypatch.setattr(elftools.elf.elffile,'ELFFile',lambda *args:Elf())
    def forbidden(*args):pytest.fail('Gamma扩展地址越界时创建了CPU')
    monkeypatch.setattr(unicorn,'Uc',forbidden)
    with pytest.raises(ValueError,match='限定入口'):JointMachine(b'metadata fixture')
