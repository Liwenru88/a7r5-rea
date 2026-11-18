"""AJR2固定大小原生tone保存、独立字节和64位数学对照；不执行目标。"""
import ctypes as c
import hashlib
from pathlib import Path
import random
import struct
import subprocess

import pytest

from import_support import Asset
from joint_support import seed

NATIVE=Path(__file__).resolve().parents[1]/'native'
CURVE=c.c_uint32*129
TONE=c.c_int16*3


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output=tmp_path_factory.mktemp('native-tone406')/'native.so'
    command=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-DAF_GAMMA_SOFT_DIV406=1',
             '-shared','-fPIC',*[str(NATIVE/name) for name in ('af_joint.c','af_joint_asset.c','af_sha256.c')],'-o',str(output)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    lib=c.CDLL(str(output))
    lib.af_joint_asset_encode.argtypes=[c.POINTER(Asset),c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
    lib.af_joint_asset_decode.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Asset)]
    lib.af_joint_gamma.argtypes=[c.POINTER(c.c_uint32),c.POINTER(c.c_int16),c.POINTER(c.c_uint32)]
    lib.af_joint_gamma_matches.argtypes=[c.POINTER(c.c_uint32),c.POINTER(c.c_int16),c.POINTER(c.c_uint32)]
    return lib


def reference(curve,tone):
    answer=[]
    for y in curve:
        x=(y<<12)//curve[-1];v=4096-x
        value=y+((y*tone[0])>>10)
        value+=((((y*tone[1])>>10)*v>>12)*v)>>12
        value+=((((y*tone[2])>>10)*x>>12)*v)>>12
        answer.append(max(0,min(0x3ffff,value)))
    return answer


def encoded(api,asset):
    output=(c.c_uint8*1943)();written=c.c_size_t()
    assert api.af_joint_asset_encode(c.byref(asset),output,len(output),c.byref(written))==0
    assert written.value==1943
    return bytes(output)


def native_asset():
    asset=Asset(base=0,native_mode=1)
    asset.model_sha256[:]=hashlib.sha256(b'EXPLICIT_HOST_MODEL_NOT_CAMERA').digest()
    asset.recipe=seed();asset.native_seed[:]=list(asset.recipe.gamma)
    asset.native_tone[:]=[32,-48,64]
    asset.recipe.gamma[:]=reference(list(asset.native_seed),list(asset.native_tone))
    return asset


def test_native_tone_exact_math_and_identity_on_distinct_native_columns(api):
    rng=random.Random(406)
    for index in range(256):
        end=[1,31,4095,65535,0x3ffff][index%5]
        curve=[0]+sorted(rng.randrange(end+1) for _ in range(127))+[end]
        tone=[0,0,0] if index%8==0 else [rng.randint(-1024,1024) for _ in range(3)]
        expected=reference(curve,tone);before=bytes([0xa5])*516
        output=CURVE.from_buffer_copy(before)
        result=api.af_joint_gamma(CURVE(*curve),TONE(*tone),output)
        valid=expected[-1]>0 and all(a<=b for a,b in zip(expected,expected[1:]))
        assert result==(0 if valid else -1)
        if valid:
            assert list(output)==expected
            assert api.af_joint_gamma_matches(CURVE(*curve),TONE(*tone),output)==0
            if tone==[0,0,0]:assert list(output)==curve
        else:assert bytes(output)==before


def test_v2_keeps_fixed_size_and_rebuilds_full_recipe_with_independent_bytes(api):
    asset=native_asset();raw=encoded(api,asset)
    assert raw[:8]==b'AJR2\x02\x00\x80\x00' and struct.unpack_from('<I',raw,12)[0]==7
    bits=sum(value<<(18*i) for i,value in enumerate(asset.native_seed))
    body=bytearray(516)
    body[:291]=bits.to_bytes(291,'little')
    struct.pack_into('<3h',body,292,*asset.native_tone)
    body[300:332]=hashlib.sha256(struct.pack('<129I',*asset.native_seed)).digest()
    struct.pack_into('<I',body,332,1)
    assert raw[128:644]==bytes(body)
    restored=Asset();source=c.create_string_buffer(raw)
    assert api.af_joint_asset_decode(source,1943,c.byref(restored))==0
    assert bytes(restored)==bytes(asset)
    # 旧AJR1仍按最终绝对Gamma编码，不把新控制塞入旧保留字。
    old=Asset(base=asset.base);old.recipe=asset.recipe;old.model_sha256[:]=asset.model_sha256
    original=encoded(api,old)
    assert original[:8]==b'AJR1\x01\x00\x80\x00'
    assert original[128:644]==struct.pack('<129I',*asset.recipe.gamma)
    assert original[644:]==raw[644:]


@pytest.mark.parametrize('offset',[128+290,128+291,128+298,128+300,128+332,128+400])
def test_v2_rejects_noncanonical_metadata_after_valid_outer_sha(api,offset):
    raw=bytearray(encoded(api,native_asset()))
    raw[offset]^=0x80 if offset==418 else 1
    raw[96:128]=bytes(32);raw[96:128]=hashlib.sha256(raw).digest()
    output=Asset.from_buffer_copy(b'\x5a'*c.sizeof(Asset));before=bytes(output)
    assert api.af_joint_asset_decode(c.create_string_buffer(bytes(raw)),len(raw),c.byref(output))==-1
    assert bytes(output)==before


def test_v2_encode_refuses_final_curve_that_does_not_match_saved_controls(api):
    asset=native_asset();asset.native_tone[0]+=1
    raw=(c.c_uint8*1943)(*([0x5a]*1943));written=c.c_size_t(77)
    assert api.af_joint_asset_encode(c.byref(asset),raw,len(raw),c.byref(written))==-1
    assert bytes(raw)==b'\x5a'*1943 and written.value==77
