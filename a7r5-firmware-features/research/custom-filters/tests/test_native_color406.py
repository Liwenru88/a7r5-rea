"""原厂半字构造重建；完整原CP消费另由同包审计执行。"""
import ctypes as c
from pathlib import Path
import random
import struct
import subprocess
import sys
import pytest

HOME=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOME))


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    path=tmp_path_factory.mktemp('color406')/'native.so'
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        str(HOME/'native/af_color406.c'),str(HOME/'tests/native_color406_target.c'),'-o',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    a=c.CDLL(str(path))
    for name,count in [('af_color406_matrix',3),('af_color406_primary',3),('af_color406_secondary',4)]:
        getattr(a,name).argtypes=[c.c_void_p]*count
    a.af_color406_add.argtypes=[c.c_void_p,c.c_void_p,c.c_uint32,c.c_void_p]
    a.af_color406_blend.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p]
    a.af_color406_adjust.argtypes=[c.c_void_p,c.c_void_p]
    a.af_color406_matrix_blend.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p]
    return a


def short(v):return (v+32768)%65536-32768


def test_matrix_three_endpoints_keep_independent_diagonals_and_native_halfword_order(api):
    rng=random.Random(2301)
    for _ in range(40):
        values=[rng.randrange(65536) for _ in range(18)];diagonal=[rng.randrange(65536) for _ in range(3)]
        source=(c.c_uint16*18)(*values);cal=(c.c_uint16*3)(*diagonal);out=(c.c_int16*27)();expected=[]
        for start in range(0,18,6):
            a,b,cc,d,e,f=values[start:start+6]
            expected.extend(map(short,(diagonal[0]+a+b,-a,-b,-cc,diagonal[1]+cc+d,-d,-e,-f,diagonal[2]+e+f)))
        before=bytes(source),bytes(cal)
        assert api.af_color406_matrix(source,cal,out)==0 and list(out)==expected
        assert (bytes(source),bytes(cal))==before


def test_cc1_global_adjust_then_endpoint_differences_and_secondary_metadata(api):
    raw=[32760,65535,1,0,100,400,65000,32000]+[32760,-32768,32767,-1,0,222,333,444]*2
    values=(c.c_uint16*24)(*[(v&65535) for v in raw]);adjust=(c.c_int16*8)(-125,110,-87,99,201,211,239,251)
    metadata=(c.c_uint16*8)(*[65535-i*101 for i in range(8)])
    output=(c.c_int16*24)();secondary=(c.c_int16*16)()
    assert api.af_color406_primary(values,adjust,output)==0
    assert list(output)==[short(raw[i%8]+adjust[i%8]+(raw[i] if i>=8 else 0)) for i in range(24)]
    assert api.af_color406_secondary(values,adjust,metadata,secondary)==0
    assert list(secondary)==list(output[:8])+[short(v) for v in metadata]


@pytest.mark.parametrize('count',[8,24,27])
def test_signed_delta_is_after_native_expansion_and_wraps_low_halfword(api,count):
    source=(c.c_int16*count)(*[32760 if i%2 else -32760 for i in range(count)])
    delta=(c.c_int16*count)(*[1000 if i%2 else -1000 for i in range(count)]);out=(c.c_int16*count)()
    assert api.af_color406_add(source,delta,count,out)==0
    assert list(out)==[short(a+b) for a,b in zip(source,delta)]
    before=bytes(out)
    assert api.af_color406_add(source,delta,7,out)==-1 and bytes(out)==before
    assert api.af_color406_add(source,delta,count,source)==-1


def test_bad_aliases_do_not_partially_publish(api):
    raw=(c.c_uint16*64)(*[0x6a6a]*64);before=bytes(raw)
    assert api.af_color406_matrix(raw,c.byref(raw,80),raw)==-1 and bytes(raw)==before
    assert api.af_color406_primary(raw,c.byref(raw,32),raw)==-1 and bytes(raw)==before
    assert api.af_color406_secondary(raw,c.byref(raw,32),c.byref(raw,64),raw)==-1 and bytes(raw)==before


def test_same_target_contract_executes_on_host(api):
    assert api.af_color406_target_check()==0
    report=(c.c_uint32*4).in_dll(api,'af_color406_target_report')
    assert report[0]==0x43323331 and report[1]>100 and report[2:]==[27,24]


def test_two_stage_cc1_blend_keeps_intermediate_wrap_and_signed_half_rounding(api):
    rng=random.Random(2302)
    for _ in range(100):
        endpoints=[rng.randrange(-32768,32768) for _ in range(24)]
        weights=[rng.randrange(257),rng.randrange(257),0,rng.randrange(257)];weights[2]=rng.randrange(257-weights[1])
        e=(c.c_int16*24)(*endpoints);w=(c.c_uint16*4)(*weights);out=(c.c_int16*8)();expected=[]
        for i in range(8):
            a,b,cc=endpoints[i],endpoints[i+8],endpoints[i+16]
            first=short(a+((b-a)*weights[0]//256))
            second=short(a+(((b-a)*weights[1]+(cc-a)*weights[2])//256))
            value=first*(256-weights[3])+second*weights[3]
            expected.append(short((abs(value)+128)//256*(1 if value>=0 else -1)))
        assert api.af_color406_blend(e,w,out)==0 and list(out)==expected
        before=bytes(out);w[1]=w[2]=256
        assert api.af_color406_blend(e,w,out)==-1 and bytes(out)==before
    e=(c.c_int16*24)(*([-1]*8+[0]*8+[0]*8));w=(c.c_uint16*4)(256,0,0,128);out=(c.c_int16*8)()
    assert api.af_color406_blend(e,w,out)==0 and list(out)==[-1]*8


def test_wrong_cp_is_rejected_before_creating_native_machine(monkeypatch):
    from a7filters import cp_color406
    def forbidden(*args,**kwargs):pytest.fail('未核对CP就创建了执行器')
    monkeypatch.setattr(cp_color406,'CpMachine',forbidden)
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):cp_color406.collect(b'changed CP',object())


def test_dynamic_cc1_calibration_keeps_signed_first_four_unsigned_last_four(api):
    raw=(c.c_uint8*8)(128,255,0,127,128,255,0,127);out=(c.c_int16*8)(*[12345]*8)
    before=bytes(raw)
    assert api.af_color406_adjust(raw,out)==0
    assert list(out)==[-128,-1,0,127,128,255,0,127] and bytes(raw)==before
    assert api.af_color406_adjust(raw,raw)==-1 and bytes(raw)==before
    assert api.af_color406_adjust(None,out)==-1 and list(out)==[-128,-1,0,127,128,255,0,127]


def test_matrix_consumer_rounds_delta_before_adding_base(api):
    # 主路径-1→0的半步：先舍入差分应为0，直接舍入加权和会得到-1。
    endpoints=(c.c_int16*27)(*([-1]*9+[0]*9+[32767]*9))
    weights=(c.c_uint16*4)(128,0,0,0);out=(c.c_int16*9)()
    assert api.af_color406_matrix_blend(endpoints,weights,out)==0 and list(out)==[0]*9
    weights[3]=128
    assert api.af_color406_matrix_blend(endpoints,weights,out)==0 and list(out)==[-1]*9


def test_matrix_consumer_matches_independent_rational_reference_and_rejects_partial_output(api):
    from fractions import Fraction
    rng=random.Random(2401)
    def rounded(value):return (1 if value>=0 else -1)*int(abs(value)+Fraction(1,2))
    for _ in range(100):
        values=[rng.randrange(-32768,32768) for _ in range(27)]
        w=[rng.randrange(257),rng.randrange(257),0,rng.randrange(257)];w[2]=rng.randrange(257-w[1])
        endpoints=(c.c_int16*27)(*values);weights=(c.c_uint16*4)(*w);out=(c.c_int16*9)();want=[]
        for i in range(9):
            a,b,cc=values[i],values[i+9],values[i+18]
            x=a+rounded(Fraction((b-a)*w[0],256))
            y=a+rounded(Fraction((b-a)*w[1]+(cc-a)*w[2],256))
            want.append(rounded(Fraction(x*(256-w[3])+y*w[3],256)))
        assert api.af_color406_matrix_blend(endpoints,weights,out)==0 and list(out)==want
        before=bytes(out);weights[1]=weights[2]=256
        assert api.af_color406_matrix_blend(endpoints,weights,out)==-1 and bytes(out)==before
    assert api.af_color406_matrix_blend(endpoints,weights,endpoints)==-1


def test_matrix_full_audit_rejects_wrong_cp_before_allocating_cpu(monkeypatch):
    from a7filters import cp_color_consumption406
    def forbidden(*args,**kwargs):pytest.fail('CP不匹配时创建了CPU')
    monkeypatch.setattr(cp_color_consumption406,'setup',forbidden)
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):cp_color_consumption406.collect(b'changed CP',object())


@pytest.mark.parametrize('bad',['missing','range','consume_missing','consume_range'])
def test_color_extension_metadata_is_checked_before_cpu_creation(monkeypatch,bad):
    from a7filters.native_joint import JointMachine
    import elftools.elf.elffile
    import unicorn
    names=('af_joint_gamma_record','af_joint_expand_matrix','af_joint_target_check','af_joint_target_report',
           'af_joint_target_metrics','af_color406_matrix','af_color406_primary','af_color406_secondary',
           'af_color406_add','af_color406_target_check','af_color406_target_report','af_color406_blend')
    if bad.startswith('consume_'):names+=('af_color406_adjust','af_color406_matrix_blend')
    class Symbol(dict):
        def __init__(self,name,i):
            outside=bad=='range' and i==5 or bad=='consume_range' and i==len(names)-1
            super().__init__(st_value=0x90000000 if outside else 0x9080000+i*4,st_shndx=1);self.name=name
    class Table:
        def iter_symbols(self):
            return [Symbol(name,i) for i,name in enumerate(names)
                    if not (bad=='missing' and i==7 or bad=='consume_missing' and i==len(names)-1)]
    class Elf(dict):
        little_endian=True
        def __init__(self):super().__init__(e_machine='EM_AARCH64',e_type='ET_EXEC')
        def iter_sections(self):return []
        def get_section_by_name(self,name):return Table()
    monkeypatch.setattr(elftools.elf.elffile,'ELFFile',lambda *args:Elf())
    def forbidden(*args):pytest.fail('颜色扩展元数据错误时创建了CPU')
    monkeypatch.setattr(unicorn,'Uc',forbidden)
    with pytest.raises(ValueError,match='颜色.*扩展|限定入口'):JointMachine(b'metadata fixture')
