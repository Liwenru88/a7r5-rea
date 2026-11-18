"""真实参考链实际可达样本；精确成对域映射不插值，不声称照片色准。"""
import ctypes as c
from pathlib import Path
import subprocess

import pytest

from grid_support import Sample,Progress
from joint_support import Recipe
from test_edit_joint import Cache,Work,SOURCES,evaluate
from test_reference_assets import Owner,numeric_asset
from test_reference_joint import Map

HOME=Path(__file__).resolve().parents[1]


class Config(c.Structure):
    _fields_=[('schema',c.c_uint32),('base',c.c_uint32),('side',c.c_uint32),
              ('native_maximum',c.c_uint16*3),('baseline',c.c_void_p)]


class Report(c.Structure):
    _fields_=[(k,c.c_uint32)for k in ('evaluations','unique','duplicates','training','validation',
                                    'gray_validation','warm_validation','occupied_cells','research_only','camera_apply_allowed')]+[
        ('training_cells',c.c_uint64),('validation_cells',c.c_uint64)]+[
        (k,c.c_uint8*32)for k in ('context_sha256','recipe_sha256','policy_sha256','source_sha256')]


class Buffers(c.Structure):
    _fields_=[('pairs',c.c_void_p),('pair_capacity',c.c_size_t),
              ('output_values',c.c_void_p),('output_capacity',c.c_size_t),
              ('training',c.c_void_p),('training_capacity',c.c_size_t),
              ('validation',c.c_void_p),('validation_capacity',c.c_size_t),
              ('input_map',c.c_void_p),('output_map',c.c_void_p),('report',c.c_void_p)]


def memory(size):return (c.c_uint64*((size+7)//8))()


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output=tmp_path_factory.mktemp('reference-samples')/'native.so'
    names=[*SOURCES,'af_reference_assets.c','af_reference_samples.c','af_reference_domain.c',
           'af_reference_joint.c','af_grid.c','af_slots.c','af_cube.c']
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffp-contract=off',
        '-shared','-fPIC',*[str(HOME/'native'/name)for name in names],'-o',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    lib=c.CDLL(str(output))
    for name in ('af_reference_samples_state_bytes','af_reference_samples_work_bytes'):
        getattr(lib,name).restype=c.c_size_t
    lib.af_reference_assets_bind.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p]
    lib.af_reference_assets_seed.argtypes=[c.c_void_p,c.c_void_p]
    lib.af_edit_joint_prepare.argtypes=[c.c_void_p]*4+[Progress,c.c_void_p]
    lib.af_edit_joint_eval.argtypes=[c.c_void_p]*4
    lib.af_reference_samples_start.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p,Progress,c.c_void_p]
    lib.af_reference_samples_step.argtypes=[c.c_void_p,c.c_uint32]
    lib.af_reference_map_eval.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p]
    return lib


@pytest.fixture(scope='module')
def baseline(api):
    raw,storage,manifest=numeric_asset();owner=Owner();seed=Recipe();cache=Cache();work=Work()
    assert api.af_reference_assets_bind(storage,len(raw),c.byref(owner))==0
    assert api.af_reference_assets_seed(c.byref(owner),c.byref(seed))==0
    assert api.af_edit_joint_prepare(c.byref(owner.joint),c.byref(seed),c.byref(work),c.byref(cache),Progress(),None)==0
    return cache,(storage,owner,seed,work,manifest)


def setup(api,baseline,side=9,maximum=16383):
    cache,owners=baseline;state=memory(api.af_reference_samples_state_bytes());work=memory(api.af_reference_samples_work_bytes())
    count=(side**3+130)*6;pairs=(c.c_float*count)();out=(c.c_float*24)()
    training=(Sample*512)();validation=(Sample*4096)()
    incoming=Map.from_buffer_copy(b'\xa5'*c.sizeof(Map));outgoing=Map.from_buffer_copy(b'\xa5'*c.sizeof(Map))
    report=Report.from_buffer_copy(b'\xa5'*c.sizeof(Report))
    config=Config(1,0,side,(c.c_uint16*3)(maximum,maximum,maximum),c.addressof(cache))
    buffers=Buffers(c.addressof(pairs),count,c.addressof(out),24,c.addressof(training),512,
                    c.addressof(validation),4096,c.addressof(incoming),c.addressof(outgoing),c.addressof(report))
    return state,work,config,buffers,(pairs,out,training,validation,incoming,outgoing,report)


def cell(rgb):
    key=0
    for v in rgb:key=key*4+min(3,int(v*4))
    return key


def drain(api,state,budget):
    for _ in range(9000):
        result=api.af_reference_samples_step(state,budget)
        if result!=1:return result
    pytest.fail('有界采样未结束')


def test_actual_forward_pairs_exact_lookup_and_region_holdout_are_batch_invariant(api,baseline):
    results=[]
    for batch in (1,64):
        state,work,config,buffers,objects=setup(api,baseline)
        pairs,out,training,validation,incoming,outgoing,report=objects
        before=bytes(incoming),bytes(outgoing),bytes(report);calls=[]
        progress=Progress(lambda _,done,total:calls.append((done,total))or 0)
        assert api.af_reference_samples_start(state,c.byref(config),c.byref(buffers),work,progress,None)==1
        assert (bytes(incoming),bytes(outgoing),bytes(report))==before
        assert drain(api,state,batch)==0
        assert api.af_reference_samples_step(state,1)==-5
        assert report.evaluations==859 and report.unique+report.duplicates==859
        assert 2<=report.training<=512 and 3<=report.validation<=4096
        assert report.gray_validation and report.warm_validation and report.occupied_cells>2
        assert report.research_only==1 and report.camera_apply_allowed==0
        assert incoming.schema==2 and incoming.dimension==0 and incoming.count==report.unique*6
        assert outgoing.schema==1 and outgoing.dimension==2 and outgoing.count==24
        rows=[tuple(pairs[i*6:i*6+6])for i in range(report.unique)]
        assert [r[:3]for r in rows]==sorted(set(r[:3]for r in rows))
        for i in (0,len(rows)//2,len(rows)-1):
            row=rows[i];actual=evaluate(api,baseline[0],tuple(int(v)for v in row[3:]))
            assert row[:3]==tuple(c.c_float(v/16383).value for v in actual)
        train=[training[i]for i in range(report.training)];valid=[validation[i]for i in range(report.validation)]
        tc={cell(x.rgb)for x in train};vc={cell(x.rgb)for x in valid}
        assert not(tc&vc) and not(report.training_cells&report.validation_cells)
        assert sum(1<<key for key in tc)==report.training_cells and sum(1<<key for key in vc)==report.validation_cells
        found={row[:3]:row[3:]for row in rows}
        native=(c.c_float*3)()
        for entry in train+valid:
            assert tuple(entry.rgb)in found
            assert api.af_reference_map_eval(c.byref(incoming),entry.rgb,native)==0
            assert tuple(native)==found[tuple(entry.rgb)]
        unknown=(c.c_float*3)(.12345,.23456,.34567);old=bytes(native)
        assert api.af_reference_map_eval(c.byref(incoming),unknown,native)==-21 and bytes(native)==old
        assert calls[-1]==(860,860)
        assert all(0<=min(b[0],859)-min(a[0],859)<=64 for a,b in zip(calls,calls[1:]))
        results.append((rows,bytes(training)[:report.training*c.sizeof(Sample)],
                        bytes(validation)[:report.validation*c.sizeof(Sample)],bytes(report)))
    assert results[0]==results[1]


def test_cancel_reentry_and_context_change_do_not_publish_descriptors(api,baseline):
    state,work,config,buffers,objects=setup(api,baseline)
    incoming,outgoing,report=objects[-3:];before=bytes(incoming),bytes(outgoing),bytes(report)
    stopped=[False];reentrant=[]
    def progress(_,done,total):
        if done:reentrant.append(api.af_reference_samples_step(state,1))
        return int(stopped[0])
    callback=Progress(progress)
    assert api.af_reference_samples_start(state,c.byref(config),c.byref(buffers),work,callback,None)==1
    assert api.af_reference_samples_start(state,c.byref(config),c.byref(buffers),work,callback,None)==-4
    assert api.af_reference_samples_step(state,1)==1
    stopped[0]=True
    assert api.af_reference_samples_step(state,1)==-20 and reentrant and set(reentrant)=={-4}
    assert (bytes(incoming),bytes(outgoing),bytes(report))==before
    stopped[0]=False
    assert api.af_reference_samples_start(state,c.byref(config),c.byref(buffers),work,callback,None)==1
    baseline[0].source_sha256[0]^=1
    assert api.af_reference_samples_step(state,1)==-5
    baseline[0].source_sha256[0]^=1
    assert (bytes(incoming),bytes(outgoing),bytes(report))==before


def test_insufficient_actual_colors_or_aliased_buffers_never_invent_groups(api,baseline):
    state,work,config,buffers,objects=setup(api,baseline,side=3,maximum=1)
    incoming,outgoing,report=objects[-3:];before=bytes(incoming),bytes(outgoing),bytes(report)
    assert api.af_reference_samples_start(state,c.byref(config),c.byref(buffers),work,Progress(),None)==1
    assert drain(api,state,64)==-32
    assert (bytes(incoming),bytes(outgoing),bytes(report))==before
    state,work,config,buffers,objects=setup(api,baseline)
    buffers.pairs=c.addressof(baseline[0])
    assert api.af_reference_samples_start(state,c.byref(config),c.byref(buffers),work,Progress(),None)==-1
