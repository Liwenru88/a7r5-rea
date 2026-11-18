"""候选参数确实重建参考颜色链；自持表和事务不代表机身/sRGB桥。"""
import ctypes as c
import json
from pathlib import Path
import struct
import subprocess

import pytest

from test_edit_chain import Chain,Work as PixelWork,parameters as chain_parameters
from test_edit_reference import ChromaSource,unpack,u16
from test_edit_gamma_table import Work as GammaWork
from test_edit_matrix_table import Domain,Work as MatrixWork

HOME=Path(__file__).resolve().parents[1]
Progress=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_uint32,c.c_uint32)


class Input(c.Structure):
    _fields_=[(name,c.c_void_p) for name in ('baseline','axis','gamma_y','contrast','matrix_payload',
        'cc1','matrix_domain','chroma_source','secondary_inverse','secondary_gamma')]+[
        ('secondary_inverse_entries',c.c_size_t),('secondary_entries',c.c_size_t),('main_inverse_initial_zero',c.c_uint16)]


class Context(c.Structure):
    _fields_=[('chain',Chain),('chroma_source',ChromaSource),('matrix_config',c.c_uint8*552),
        ('matrix_table',c.c_float*18432),('angles',c.c_float*512),('main_gamma',c.c_uint16*65536),
        ('main_inverse',c.c_int16*65536),('secondary_gamma',c.c_int16*65536),('secondary_inverse',c.c_int16*16384)]


class Work(c.Structure):
    _fields_=[('candidate',Context),('gamma',GammaWork),('matrix',MatrixWork)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    target=tmp_path_factory.mktemp('edit-context')/'native.so'
    sources=['af_edit_reference.c','af_edit_chain.c','af_edit_gamma_table.c','af_edit_matrix_table.c','af_edit_context.c']
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffp-contract=off',
        '-shared','-fPIC',*[str(HOME/'native'/name) for name in sources],'-o',str(target)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    result=c.CDLL(str(target));result.af_edit_context_build.argtypes=[c.c_void_p]*3+[Progress,c.c_void_p]
    result.af_edit_ref_color.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t,c.c_size_t,c.c_void_p,c.c_void_p]
    return result


def parameters():
    data=json.loads((HOME/'tests/fixtures/edit_reference_context4.json').read_text())
    axis=json.loads((HOME/'tests/fixtures/edit_gamma_axis_bridge.json').read_text())
    matrix=json.loads((HOME/'tests/fixtures/edit_matrix_table_context4.json').read_text())
    base,tables=chain_parameters(data);source=data['chroma_source']
    owners=dict(baseline=base,baseline_tables=tables,
        axis=(c.c_uint32*128)(*axis['edit_x']),gamma_y=(c.c_uint32*128)(*axis['edit_y']),
        contrast=(c.c_int32*1025)(*[i*64 for i in range(1024)],65535),
        matrix_payload=c.create_string_buffer(bytes.fromhex(matrix['payload_hex']),276),
        cc1=(c.c_int16*8)(*data['cc1']),matrix_domain=Domain(1,1,3,(c.c_uint8*2)(255,255)),
        chroma_source=ChromaSource((c.c_int16*3)(*source['slopes']),(c.c_int16*3)(*source['thresholds']),
            source['low_slope'],source['low_threshold'],source['gain_raw'],source['exposure_300']),
        secondary_inverse=(c.c_int16*16384).from_buffer_copy(unpack(data['chroma_tables']['inverse_secondary'])),
        secondary_gamma=(c.c_int16*65536).from_buffer_copy(unpack(data['chroma_tables']['secondary_gamma'])))
    zero=struct.unpack_from('<H',unpack(data['chroma_tables']['inverse_main']))[0]
    fields=[name for name,_ in Input._fields_[:10]]
    value=Input(*(c.addressof(owners[name]) for name in fields),16384,65536,zero)
    return data,value,owners


def assert_self_owned(value):
    base=c.addressof(value)
    assert value.chain.matrix.table==base+Context.matrix_table.offset
    assert value.chain.matrix.angles==base+Context.angles.offset
    assert value.chain.main_gamma==base+Context.main_gamma.offset
    assert value.chain.y_gamma==base+Context.secondary_gamma.offset+32768*2


def render(api,chain,source,width,height):
    out=(c.c_uint16*len(source))();work=PixelWork()
    assert api.af_edit_ref_color(c.byref(chain),source,width,height,c.byref(work),out)==0
    return bytes(out)


def test_full_runtime_baseline_constructs_self_owned_tables_and_same_color_chain(api):
    data,value,owners=parameters();work=Work();result=Context()
    before=bytes(owners['baseline']),[bytes(t) for t in owners['baseline_tables']]
    assert api.af_edit_context_build(c.byref(value),c.byref(work),c.byref(result),Progress(),None)==0
    assert c.sizeof(result)==502544 and c.sizeof(work)==707896
    assert_self_owned(result)
    for field,key in (('main_gamma','main_gamma'),('matrix_table','matrix_table'),('angles','matrix_angles')):
        assert bytes(getattr(result,field))==unpack(data[key])
    for field,key in (('main_inverse','inverse_main'),('secondary_gamma','secondary_gamma'),('secondary_inverse','inverse_secondary')):
        assert bytes(getattr(result,field))==unpack(data['chroma_tables'][key])
    matrix=json.loads((HOME/'tests/fixtures/edit_matrix_table_context4.json').read_text())
    assert bytes(result.matrix_config)==bytes.fromhex(matrix['config_hex'])
    assert bytes(result.chain.chroma)==bytes(owners['baseline'].chroma)
    pixels=u16(unpack(data['goldens']['matrix16']['input']));height,width=data['goldens']['matrix16']['shape']
    assert render(api,result.chain,pixels,width,height)==unpack(data['goldens']['ycc-rgb']['output'])
    assert (bytes(owners['baseline']),[bytes(t) for t in owners['baseline_tables']])==before


def test_nonzero_three_components_enter_chain_rebuild_cutoff_and_survive_work_reuse(api):
    data,value,owners=parameters();work=Work();baseline=Context()
    assert api.af_edit_context_build(c.byref(value),c.byref(work),c.byref(baseline),Progress(),None)==0
    baseline_before=bytes(baseline);source_before=bytes(owners['baseline']),[bytes(t) for t in owners['baseline_tables']]
    old_y=list(owners['gamma_y']);old_matrix=owners['matrix_payload'].raw;old_cc1=list(owners['cc1'])
    owners['gamma_y'][:]=[v*3//4 for v in old_y]
    raw=bytearray(old_matrix);struct.pack_into('<H',raw,26,2048);owners['matrix_payload'].raw=bytes(raw)
    owners['cc1'][0]+=4;owners['cc1'][4]+=8
    result=Context();assert api.af_edit_context_build(c.byref(value),c.byref(work),c.byref(result),Progress(),None)==0
    assert_self_owned(result);result_before=bytes(result)
    assert bytes(result.main_gamma)!=bytes(baseline.main_gamma) and bytes(result.main_inverse)!=bytes(baseline.main_inverse)
    assert bytes(result.matrix_table)!=bytes(baseline.matrix_table)
    assert struct.unpack_from('<f',bytes(result.matrix_config),0x28)[0]==0.5
    assert list(result.chain.cc1)==list(owners['cc1'])!=old_cc1
    # 当前公开端点gain=1、exposure=0；用新逆表/新Gamma独立取回预期cutoff。
    s=owners['chroma_source'];assert s.gain_raw==64 and s.exposure_300==0
    inv_secondary=result.secondary_inverse[s.thresholds[0]]
    code=result.main_inverse[32768+inv_secondary]
    gamma=result.main_gamma[32768+min(code,32767)]
    expected_cutoff=result.secondary_gamma[32768+gamma]
    assert result.chain.chroma.high_cutoff==expected_cutoff!=baseline.chain.chroma.high_cutoff
    probe=(c.c_uint16*24)(*([1736,1000,9000]*8))
    full=render(api,result.chain,probe,8,1)
    # 每次只撤掉一个非零组件，捕捉字段已保存但链未消费的接线错误。
    for component in ('gamma','matrix','cc1'):
        if component=='gamma':owners['gamma_y'][:]=old_y
        elif component=='matrix':owners['matrix_payload'].raw=old_matrix
        else:owners['cc1'][:]=old_cc1
        alternative=Context()
        assert api.af_edit_context_build(c.byref(value),c.byref(work),c.byref(alternative),Progress(),None)==0
        assert render(api,alternative.chain,probe,8,1)!=full
        owners['gamma_y'][:]=[v*3//4 for v in old_y];owners['matrix_payload'].raw=bytes(raw)
        owners['cc1'][:]=old_cc1;owners['cc1'][0]+=4;owners['cc1'][4]+=8
    assert bytes(baseline)==baseline_before and bytes(result)==result_before
    assert render(api,result.chain,probe,8,1)==full
    assert (bytes(owners['baseline']),[bytes(t) for t in owners['baseline_tables']])==source_before


def test_late_context_mismatch_cancel_or_alias_never_publishes(api):
    _,value,owners=parameters();work=Work();result=Context.from_buffer_copy(b'\xa5'*c.sizeof(Context));before=bytes(result)
    owners['secondary_inverse'][16383]^=1
    assert api.af_edit_context_build(c.byref(value),c.byref(work),c.byref(result),Progress(),None)==-1 and bytes(result)==before
    owners['secondary_inverse'][16383]^=1;calls=[]
    def progress(context,done,total):calls.append((done,total));return done==148481
    callback=Progress(progress)
    assert api.af_edit_context_build(c.byref(value),c.byref(work),c.byref(result),callback,None)==-20
    assert calls[-1]==(148481,148481) and bytes(result)==before
    owners['cc1'][4]=2048
    assert api.af_edit_context_build(c.byref(value),c.byref(work),c.byref(result),Progress(),None)==-1 and bytes(result)==before
    owners['cc1'][4]=818
    assert api.af_edit_context_build(c.byref(value),c.byref(work),c.byref(work),Progress(),None)==-1
