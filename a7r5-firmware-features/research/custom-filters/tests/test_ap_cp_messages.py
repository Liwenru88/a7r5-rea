"""通信证据执行前的身份/长度边界；原指令联验由同包DAT审计执行。"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from a7filters import ap_cp_messages,cp_frame_stages


def test_wrong_library_is_rejected_before_creating_either_cpu(monkeypatch):
    seen=[]
    def source(raw,expected,name):
        seen.append(name)
        if name=='OSAL':raise ValueError('OSAL不是已锁定4.06组件')
    def forbidden(*args,**kwargs):pytest.fail('来源核对前创建CPU')
    monkeypatch.setattr(ap_cp_messages,'require_source',source)
    monkeypatch.setattr(ap_cp_messages,'MessageMachine',forbidden)
    monkeypatch.setattr(ap_cp_messages,'CpMachine',forbidden)
    with pytest.raises(ValueError,match='OSAL不是已锁定'):
        ap_cp_messages.collect(b'ap',b'cp',b'changed library')
    assert seen==['AP','CP','OSAL']


@pytest.mark.parametrize('body',[b'',b'x'*11,b'x'*13])
def test_wrong_message_length_never_touches_cpu(body):
    class Forbidden:
        def __getattr__(self,name):pytest.fail('长度拒绝前访问CPU')
    with pytest.raises(ValueError,match='12字节'):
        ap_cp_messages.receive(Forbidden(),body)
    with pytest.raises(ValueError,match='12字节'):
        ap_cp_messages.MessageMachine.send(Forbidden(),body)


def test_frame_evidence_rejects_changed_cp_before_emulation(monkeypatch):
    def forbidden(*args,**kwargs):pytest.fail('错误CP在身份核对前执行')
    monkeypatch.setattr(cp_frame_stages,'CpMachine',forbidden)
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):
        cp_frame_stages.collect(b'changed CP')
