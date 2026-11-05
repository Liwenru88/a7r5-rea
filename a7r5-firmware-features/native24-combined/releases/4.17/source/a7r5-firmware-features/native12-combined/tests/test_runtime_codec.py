"""原v4编解码的原子拒绝、名称生命周期和空配置。"""
import ctypes as C
import pytest
from runtime_support import SOURCE,LookSet,decoded,library
from test_runtime_transport import codec


@pytest.mark.parametrize('bad',['mask','short_utf8','full_utf8','cc1','matrix','gamma_first','gamma_order','gamma_range','grid','padding'])
def test_encoder_rejects_invalid_config_without_touching_output(codec,bad):
    value=decoded(codec)
    if bad=='mask':value.mask=0x1000
    if bad=='short_utf8':value.look[0].short=b'\xc0\xaf'
    if bad=='full_utf8':value.look[0].full=b'\xed\xa0\x80'
    if bad=='cc1':value.look[0].cc1[0]=32767
    if bad=='matrix':value.look[0].matrix[0]=32767
    if bad=='gamma_first':value.look[0].gamma[0]=1
    if bad=='gamma_order':value.look[0].gamma[100]=0
    if bad=='gamma_range':value.look[0].gamma[128]=131072
    if bad=='grid':value.look[0].grid[0]=64
    if bad=='padding':value.look[0].pad=1
    out=C.create_string_buffer(b'\xa5'*30000)
    codec.r5_encode_look_file.restype=C.c_size_t
    assert codec.r5_encode_look_file(C.byref(value),out,30000)==0
    assert out.raw==b'\xa5'*30000+b'\0'


def test_empty_and_sparse_codec_roundtrip_clears_unlisted_slots(codec):
    value=decoded(codec)
    for mask in (0,1,0x805,0xfff):
        value.mask=mask;out=C.create_string_buffer(30000);loaded=LookSet()
        C.memset(C.byref(loaded),0xa5,C.sizeof(loaded))
        codec.r5_encode_look_file.restype=C.c_size_t
        n=codec.r5_encode_look_file(C.byref(value),out,30000)
        assert n==128+mask.bit_count()*2452
        assert codec.r5_decode_look_file(out,n,C.byref(loaded))==0 and loaded.mask==mask
        for slot in range(12):
            assert bytes(loaded.look[slot])==(bytes(value.look[slot]) if mask&(1<<slot) else bytes(2444))


def test_names_versions_remain_immutable_reuse_and_fail_closed_at_limit(tmp_path):
    lib=library(tmp_path,'names',[SOURCE/'import'/s for s in ('r5_stage410_codec.c','r5_filter_names423.c')])
    lib.r5_filter_short_name.restype=C.c_void_p
    value=decoded(lib);pointers=[]
    for version in range(16):
        value.look[0].short=('版本'+str(version)).encode()
        assert lib.r5_filter_names_publish(C.byref(value))==1
        p=lib.r5_filter_short_name(1);pointers.append((p,C.string_at(p)))
        assert lib.r5_filter_names_publish(C.byref(value))==1
    for p,s in pointers:assert C.string_at(p)==s
    value.look[0].short='版本16'.encode()
    assert lib.r5_filter_names_publish(C.byref(value))==-2
    assert lib.r5_filter_available_mask()==0
    for p,s in pointers:assert C.string_at(p)==s
