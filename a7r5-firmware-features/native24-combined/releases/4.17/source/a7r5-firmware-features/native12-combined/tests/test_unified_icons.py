"""图形编号的原生资源及解码验证；不生成或替换菜单截图。"""
import ctypes as C
from pathlib import Path
import struct
import subprocess
import pytest
import unified_icons as icons


def fixture():
    table=bytearray(b'\xff\xff'*icons.COUNT);struct.pack_into('<2H',table,0,0,5)
    stream=icons.literal_stream(icons.icon_pixels(1))
    other=icons.literal_stream(bytes((i*37)%256 for i in range(2048)))
    bitmap=struct.pack('<5I',0x1a000000,0xc0000000,35<<16|70,len(stream),56)
    complex_record=struct.pack('<10I',0x1a000001,0xc8000000,32<<16|32,0x10002,0,0x80000,0x80008,8,len(other),36+len(stream))
    return icons.HEADER+struct.pack('<I',icons.COUNT|(icons.COUNT<<12))+table+bitmap+complex_record+stream+other


def test_twelve_resources_preserve_original_payloads_and_decode_with_sony_decoder(tmp_path):
    source=Path(__file__).resolve().parents[3]/'a7r5-qemu/source/guest/sony-lz77.c'
    output=tmp_path/'lz77.dylib'
    result=subprocess.run(['clang','-shared','-fPIC','-O2','-Wall','-Werror',str(source),'-o',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    decoder=C.CDLL(str(output)).sony_lz77_decode
    decoder.argtypes=[C.c_void_p,C.c_ulong,C.c_void_p,C.c_ulong];decoder.restype=C.c_int
    raw=fixture();candidate,proof=icons.append_icons(raw)
    count,_,_,records,_=icons.layout(candidate)
    assert count==7868 and proof['inverse_exact'] and proof['old_records_preserved']==2
    assert proof['old_bitmap_payloads_identical']==proof['old_complex_payloads_identical']==1
    hashes=set()
    for index in range(24):
        slot,selected=index//2+1,bool(index&1)
        at,flags,shape,size,offset=records[icons.COUNT+index]
        assert flags==0xc0000000 and shape==35<<16|70
        compressed=candidate[at+4+offset:at+4+offset+size];expected=icons.icon_pixels(slot,selected)
        target=C.create_string_buffer(len(expected));assert decoder(compressed,len(compressed),target,len(expected))==0
        assert target.raw==expected
        row=proof['new_icons'][index];assert (row['resource'],row['label'],row['selected'])==(hex(icons.FIRST+index),f'F{slot:02d}',selected)
        hashes.add(row['pixel_sha256'])
    assert len(hashes)==24


def test_unknown_truncated_or_already_extended_resource_is_rejected():
    source=fixture();candidate,_=icons.append_icons(source)
    for raw in (b'bad',source[:-4],candidate):
        with pytest.raises(ValueError):icons.append_icons(raw)
