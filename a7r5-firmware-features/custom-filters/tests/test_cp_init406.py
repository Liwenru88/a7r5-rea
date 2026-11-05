"""四核研究探针的源准入，测试夹具不代表CP启动或像素。"""
import importlib.util
from pathlib import Path
import struct
import sys

import pytest

EXPERIMENT=Path(__file__).resolve().parents[1]/'experiments/cp-init406'
sys.path.insert(0,str(EXPERIMENT))
spec=importlib.util.spec_from_file_location('cp_init406_verify',EXPERIMENT/'verify.py')
verify=importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
from audit_trace import audit
from tomco import load as load_tomco


def observer(path):
    # 独立ELF32格式夹具，仅包含一条ARM返回指令。
    header=bytearray(84)
    header[:6]=b'\x7fELF\x01\x01'
    struct.pack_into('<I',header,28,52)
    struct.pack_into('<HH',header,42,32,1)
    struct.pack_into('<8I',header,52,1,84,0x40000,0x40000,4,4,5,4)
    path.write_bytes(header+bytes.fromhex('1eff2fe1'))
    return path


def trace(extra=''):
    return ('IN:\n0x00040000:\nOBJD-T: 1eff2fe1\n\n'+
            ''.join(f'Trace {n}: 0x1 [00000000/00040000/00000000/ff000000]\n' for n in range(4))+extra)


def test_wrong_cp_rejected_before_export(tmp_path):
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):
        verify.prepare_pages(b'changed CP',tmp_path)
    assert not (tmp_path/'source-pages').exists()


def test_tomco_rejects_unlocked_archive_before_reading_configuration(tmp_path):
    # 修改后的组值或关闭看门狗的归档不能成为原启动证据。
    archive=tmp_path/'changed.cpio'
    archive.write_bytes(b'[TOMCO]\nusrrtn_cfggrp=2\nwdt_on=0\n')
    with pytest.raises(ValueError,match='原CPIO身份不符'):
        load_tomco(archive)


@pytest.mark.parametrize('gap',('omitted_page','cross_page','untranslated_exec','data_page'))
def test_missing_translation_source_never_passes(tmp_path,gap):
    elf=observer(tmp_path/'probe.elf')
    page=tmp_path/'code.bin';page.write_bytes(b'\x00'*16)
    manifest={'pages':[{'address':0x53b000,'file':'code.bin','bytes':16,'executable':True}]}
    clean=audit(trace(),manifest,tmp_path,elf)
    assert clean['status']=='PASS'
    if gap=='omitted_page':
        event='IN:\n0x0053b50c:\nOBJD-T: 00bf\n\nTrace 0: 0x2 [00000000/0053b50c/00000000/ff000000]\n'
    elif gap=='cross_page':
        event='IN:\n0x0053b00c:\nOBJD-T: 0000000000000000\n\nTrace 0: 0x2 [00000000/0053b00c/00000000/ff000000]\n'
    elif gap=='untranslated_exec':
        event='Trace 0: 0x2 [00000000/0053b000/00000000/ff000000]\n'
    else:
        manifest['pages'][0]['executable']=False
        event='IN:\n0x0053b000:\nOBJD-T: 00000000\n\nTrace 0: 0x2 [00000000/0053b000/00000000/ff000000]\n'
    refused=audit(trace(event),manifest,tmp_path,elf)
    assert refused['status']=='INCOMPLETE_SOURCE'
    assert refused['invalid_full_TB_bytes'] or refused['exec_references_without_approved_translation']


def test_translation_only_mode_requires_explicit_policy_and_rejects_gaps(tmp_path):
    elf=observer(tmp_path/'probe.elf')
    manifest={'pages':[]}
    translated='IN:\n0x00040000:\nOBJD-T: 1eff2fe1\n\n'
    assert audit(translated,manifest,tmp_path,elf)['status']=='INCOMPLETE_SOURCE'
    accepted=audit(translated,manifest,tmp_path,elf,require_exec_references=False)
    assert accepted['status']=='PASS'
    assert accepted['per_core_exec_references_required'] is False
    bad=translated+'IN:\n0x0053b50c:\nOBJD-T: 00bf\n\n'
    assert audit(bad,manifest,tmp_path,elf,require_exec_references=False)['status']=='INCOMPLETE_SOURCE'
