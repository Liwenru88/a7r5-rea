"""编号图形资源、原记录保持及真实Sony LZ77解码，不生成或替换验收帧。"""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

FEATURE=Path(__file__).resolve().parents[1]
ROOT=FEATURE.parents[1]
sys.path.insert(0,str(FEATURE))
from a7filters.ui_icons import COUNT,FIRST,HEADER,append_icons_fixture,icon_pixels,layout,literal_stream


@pytest.fixture(scope='module')
def native_decoder(tmp_path_factory):
    output=tmp_path_factory.mktemp('native-icon-lz77')/'decoder.dylib'
    source=ROOT/'a7r5-qemu/source/guest/sony-lz77.c'
    result=subprocess.run([shutil.which('clang'),'-dynamiclib' if sys.platform=='darwin' else '-shared',
        '-fPIC','-O2','-Wall','-Werror',str(source),'-o',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    library=ctypes.CDLL(str(output));function=library.sony_lz77_decode
    function.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong]
    function.restype=ctypes.c_int
    return function


def source_fixture(complex_flags=0xc8000000):
    table=bytearray(b'\xff\xff'*COUNT);struct.pack_into('<2H',table,0,0,5)
    stream=literal_stream(icon_pixels(7))
    bitmap=struct.pack('<5I',0x1a000000,0xc0000000,35<<16|70,len(stream),56)
    complex_stream=literal_stream(bytes((i*37)%256 for i in range(32*32*2)))
    # 原生复杂图像的+32/+36才是size/offset，相对基准仍为record+4。
    complex_record=struct.pack('<10I',0x1a000001,complex_flags,32<<16|32,0x10002,
                               0,0x80000,0x80008,8,len(complex_stream),36+len(stream))
    return HEADER+struct.pack('<I',COUNT|(COUNT<<12))+table+bitmap+complex_record+stream+complex_stream


def test_new_icons_preserve_original_records_and_native_decoder_reads_exact_numbered_pixels(native_decoder):
    original=source_fixture();candidate,receipt=append_icons_fixture(original)
    count,base,boundary,records,bitmap=layout(candidate)
    assert count==COUNT+14 and receipt['inverse_exact']
    assert receipt['old_records_preserved']==2 and receipt['old_bitmap_payloads_identical']==1
    hashes=set()
    for slot in range(7,21):
        at,flags,shape,size,offset=records[COUNT+slot-7]
        assert flags==0xc0000000 and shape==35<<16|70
        compressed=candidate[at+4+offset:at+4+offset+size]
        pixels=icon_pixels(slot);output=ctypes.create_string_buffer(len(pixels))
        assert native_decoder(compressed,len(compressed),output,len(pixels))==0
        assert output.raw==pixels
        icon=receipt['new_icons'][slot-7]
        assert icon['resource']==hex(FIRST+slot-7) and icon['label']==f'C{slot:02d}'
        hashes.add(icon['pixel_sha256'])
    assert len(hashes)==14


def test_bad_or_already_extended_resource_is_rejected():
    source=source_fixture()
    candidate,_=append_icons_fixture(source)
    for bad in (b'bad',source[:-4],candidate):
        with pytest.raises(ValueError):append_icons_fixture(bad)


@pytest.mark.parametrize('flags',[0xc8000000,0x48000000])
def test_complex_original_image_payload_moves_with_inserted_records(flags):
    original=source_fixture(flags);candidate,_=append_icons_fixture(original)
    _,_,_,before,_=layout(original);_,_,_,after,_=layout(candidate)
    old_at=before[1][0];new_at=after[1][0]
    old_size,old_offset=struct.unpack_from('<II',original,old_at+32)
    new_size,new_offset=struct.unpack_from('<II',candidate,new_at+32)
    assert new_size==old_size and new_offset==old_offset+14*20
    assert candidate[new_at+4+new_offset:new_at+4+new_offset+new_size]==original[old_at+4+old_offset:old_at+4+old_offset+old_size]
