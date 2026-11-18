"""默认名称夹具只扩展尾部，不破坏当前包的原记录。"""
import struct
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from a7filters.ui_resources import append_name_fixture, decode


def source():
    count=3038
    raw=bytearray(bytes.fromhex('757863070000000008000500')+struct.pack('<I',count|(count<<12)))
    raw.extend(b'\xff\xff'*count)
    base=len(raw)
    for i in range(3032,3038):
        struct.pack_into('<H',raw,16+i*2,(len(raw)-base)//4)
        raw.extend(struct.pack('<I',0x1e00a000+i)+f'original-{i}'.encode()+b'\0')
        raw.extend(b'\0'*(-len(raw)%4))
    return bytes(raw)


def test_append_preserves_old_entries_and_exact_inverse():
    raw=source()
    candidate,report=append_name_fixture(raw)
    before,after=decode(raw),decode(candidate)
    assert after['count']==3052
    assert {k:after['entries'][k] for k in before['entries']} == before['entries']
    assert [after['entries'][0x0200abde+i]['text'] for i in range(14)] == [f'C{i:02d}' for i in range(7,21)]
    inverse=bytearray(candidate[:6092]+candidate[6120:len(raw)+28])
    inverse[12:16]=raw[12:16]
    assert inverse==raw and report['inverse_exact']


@pytest.mark.parametrize('case',['version','count_copy','pointer','unterminated'])
def test_bad_input_is_refused_without_mutation(case):
    raw=bytearray(source())
    if case=='version':raw[3]=8
    elif case=='count_copy':raw[15]^=1
    elif case=='pointer':struct.pack_into('<H',raw,16,65534)
    else:raw[-16:]=b'x'*16
    before=bytes(raw)
    with pytest.raises(ValueError):append_name_fixture(raw)
    assert bytes(raw)==before


def test_record_pointer_overflow_is_refused():
    raw=source()
    raw+=b'\0'*(6092+4*65535-len(raw))
    with pytest.raises(ValueError,match='指针'):
        append_name_fixture(raw)
