"""固定实际数值blob进入现有参考构表主路径，不把数据绑定当机身标定。"""
import ctypes as c
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from joint_support import Recipe
from test_edit_chain import Chain
from test_edit_context import Input as ContextInput
from test_edit_joint import Input as JointInput,Cache,Work,Progress,SOURCES,source,evaluate
from test_edit_matrix_table import Domain
from test_edit_reference import ChromaSource

HOME=Path(__file__).resolve().parents[1]


class Owner(c.Structure):
    _fields_=[('valid',c.c_uint32),('raw',c.c_void_p),('baseline',Chain),
              ('matrix_domain',Domain),('chroma_source',ChromaSource),
              ('context',ContextInput),('joint',JointInput)]


def numeric_asset():
    raw=(HOME/'assets/reference-context4.bin').read_bytes()
    manifest=json.loads((HOME/'assets/reference-context4.json').read_text())
    assert len(raw)==377304 and hashlib.sha256(raw).hexdigest()==manifest['asset_sha256']
    for segment in manifest['segments']:
        part=raw[segment['offset']:segment['offset']+segment['bytes']]
        assert len(part)==segment['bytes'] and hashlib.sha256(part).hexdigest()==segment['sha256']
    storage=(c.c_uint64*((len(raw)+8)//8))();c.memmove(storage,raw,len(raw))
    return raw,storage,manifest


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output=tmp_path_factory.mktemp('reference-assets')/'native.so'
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffp-contract=off',
        '-shared','-fPIC',*[str(HOME/'native'/n) for n in [*SOURCES,'af_reference_assets.c']],
        '-o',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    lib=c.CDLL(str(output));lib.af_reference_assets_owner_bytes.restype=c.c_size_t
    lib.af_reference_assets_bind.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p]
    lib.af_reference_assets_seed.argtypes=[c.c_void_p,c.c_void_p]
    lib.af_edit_joint_init.argtypes=[c.c_void_p]
    lib.af_edit_joint_prepare.argtypes=[c.c_void_p]*4+[Progress,c.c_void_p]
    lib.af_edit_joint_eval.argtypes=[c.c_void_p]*4
    return lib


def test_actual_numeric_asset_binds_and_rebuilds_identical_reference_candidate(api):
    raw,storage,manifest=numeric_asset();owner=Owner();seed=Recipe()
    assert api.af_reference_assets_owner_bytes()==c.sizeof(Owner)
    assert api.af_reference_assets_bind(storage,len(raw),c.byref(owner))==0
    assert owner.valid==1 and owner.joint.edit==c.addressof(owner.context)
    assert owner.context.baseline==c.addressof(owner.baseline)
    assert api.af_reference_assets_seed(c.byref(owner),c.byref(seed))==0
    data,expected_input,owners,expected_seed=source()
    assert bytes(seed)==bytes(expected_seed)
    assert manifest['origin_commit']==data['commit'] and manifest['context']==4
    cache=Cache();expected=Cache();work=Work();expected_work=Work()
    for candidate in (Recipe.from_buffer_copy(seed),Recipe.from_buffer_copy(seed)):
        if cache.valid:
            candidate.gamma[:]=[x*3//4 for x in seed.gamma]
            candidate.matrix[6]=32;candidate.cc1[8]=8
        assert api.af_edit_joint_prepare(c.byref(owner.joint),c.byref(candidate),c.byref(work),c.byref(cache),Progress(),None)==0
        assert api.af_edit_joint_prepare(c.byref(expected_input),c.byref(candidate),c.byref(expected_work),c.byref(expected),Progress(),None)==0
        assert bytes(cache.source_sha256)==bytes(expected.source_sha256)
        assert bytes(cache.recipe_sha256)==bytes(expected.recipe_sha256)
        for name in ('matrix_table','angles','main_gamma','main_inverse','secondary_gamma','secondary_inverse'):
            assert bytes(getattr(cache.context,name))==bytes(getattr(expected.context,name))
        assert [evaluate(api,cache,p)for p in ((1736,1000,9000),(8000,8000,8000))]==[
            evaluate(api,expected,p)for p in ((1736,1000,9000),(8000,8000,8000))]
    moved=Owner.from_buffer_copy(owner);out=Recipe.from_buffer_copy(b'\xa5'*c.sizeof(Recipe));before=bytes(out)
    assert api.af_reference_assets_seed(c.byref(moved),c.byref(out))==-1 and bytes(out)==before


@pytest.mark.parametrize('failure',['hash','length','unaligned','alias'])
def test_invalid_asset_never_publishes_owner(api,failure):
    raw,storage,manifest=numeric_asset();owner=Owner.from_buffer_copy(b'\xa5'*c.sizeof(Owner))
    output=c.byref(owner);input=storage;count=len(raw)
    if failure=='hash':storage[100]^=1
    elif failure=='length':count-=1
    elif failure=='unaligned':input=c.byref(storage,1)
    else:output=storage
    before=bytes(owner),bytes(storage)
    assert api.af_reference_assets_bind(input,count,output)==-1
    assert (bytes(owner),bytes(storage))==before
