"""文档名称到原文字组件的拥有者副本；不是保存成功或机身显示证据。"""
import ctypes as c
from pathlib import Path
import subprocess
import pytest

HOME=Path(__file__).resolve().parents[1]
class Label(c.Structure):
    _fields_=[('generation',c.c_uint64),('bytes',c.c_uint32),('text',c.c_char*64)]
class Labels(c.Structure):
    _fields_=[('slots',Label*20)]

@pytest.fixture(scope='module')
def api(tmp_path_factory):
    out=tmp_path_factory.mktemp('labels')/'labels.so'
    subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        str(HOME/'native/af_labels.c'),'-o',str(out)],capture_output=True,text=True,check=True)
    lib=c.CDLL(str(out));lib.af_labels_init.argtypes=[c.c_void_p]
    lib.af_labels_publish.argtypes=[c.c_void_p,c.c_uint32,c.c_uint64,c.c_void_p,c.c_size_t]
    lib.af_labels_read.argtypes=[c.c_void_p,c.c_uint32,c.c_void_p,c.c_void_p]
    return lib

def test_copied_utf8_name_survives_source_reuse_and_tombstone_restores_default(api):
    labels=Labels();api.af_labels_init(c.byref(labels))
    raw='暖色 C07'.encode();source=c.create_string_buffer(raw)
    assert api.af_labels_publish(c.byref(labels),7,3,source,len(raw))==0
    c.memset(source,0,len(raw));pointer=c.c_void_p();size=c.c_size_t()
    assert api.af_labels_read(c.byref(labels),7,c.byref(pointer),c.byref(size))==0
    assert size.value==len(raw) and c.string_at(pointer,size.value+1)==raw+b'\0'
    before=bytes(labels)
    assert api.af_labels_publish(c.byref(labels),7,2,b'old',3)==-5
    assert api.af_labels_publish(c.byref(labels),7,3,b'new',3)==-5
    assert bytes(labels)==before
    assert api.af_labels_publish(c.byref(labels),7,3,raw,len(raw))==0
    assert api.af_labels_publish(c.byref(labels),7,4,None,0)==0
    pointer.value=123;size.value=777
    assert api.af_labels_read(c.byref(labels),7,c.byref(pointer),c.byref(size))==-2
    assert (pointer.value,size.value)==(123,777) and labels.slots[7].generation==0

@pytest.mark.parametrize('raw',[b'',b'bad\0name',b'\xc0\xaf',b'\xed\xa0\x80',b'\xf4\x90\x80\x80',b'\xc2\x80',b'x'*64])
def test_invalid_name_never_replaces_committed_label(api,raw):
    labels=Labels();api.af_labels_init(c.byref(labels))
    assert api.af_labels_publish(c.byref(labels),20,1,b'original',8)==0
    before=bytes(labels)
    assert api.af_labels_publish(c.byref(labels),20,2,raw,len(raw))==-1
    assert bytes(labels)==before
