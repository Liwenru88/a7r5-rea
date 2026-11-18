"""新消息入口的来源拒绝在ELF解析和CPU之前发生；真实分支由完整DAT审计验证。"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from a7filters import ap_request,cp_message_pool,cp_notifications,native_handshake,native_runtime


@pytest.mark.parametrize('module',[ap_request,native_handshake])
def test_source_checks_all_components_before_creating_machine(monkeypatch,module):
    seen=[]
    def source(raw,expected,name):
        seen.append(name)
        if name=='OSAL':raise ValueError('OSAL来源变化')
    def forbidden(*args,**kwargs):pytest.fail('来源核对前创建执行器')
    monkeypatch.setattr(module,'require_source',source)
    monkeypatch.setattr(module,'RequestMachine' if module is ap_request else 'HandshakeAP',forbidden)
    with pytest.raises(ValueError,match='OSAL来源变化'):
        if module is ap_request:module.collect(b'ap',b'cp',b'ipc',b'std')
        else:module.collect(b'ap',b'cp',b'ipc',b'not ELF',b'not ELF')
    assert seen==['AP','CP','OSAL']


@pytest.mark.parametrize('module',[cp_message_pool,cp_notifications])
def test_changed_cp_rejected_before_machine(monkeypatch,module):
    def forbidden(*args,**kwargs):pytest.fail('错误CP在身份核对前执行')
    monkeypatch.setattr(module,'NativeMessagePool' if module is cp_message_pool else 'CpMachine',forbidden)
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):
        module.collect(b'changed CP')


def test_wrong_cpp_library_is_rejected_before_original_request(monkeypatch):
    seen=[]
    def source(raw,expected,name):
        seen.append(name)
        if name=='libstdc++':raise ValueError('C++来源变化')
    def forbidden(*args,**kwargs):pytest.fail('错误C++库进入请求执行器')
    monkeypatch.setattr(ap_request,'require_source',source)
    monkeypatch.setattr(ap_request,'RequestMachine',forbidden)
    with pytest.raises(ValueError,match=r'C\+\+来源变化'):
        ap_request.collect(b'ap',b'cp',b'ipc',b'std')
    assert seen==['AP','CP','OSAL','libstdc++']


def test_runtime_rejects_sources_before_creating_machine(monkeypatch):
    seen=[]
    def source(raw,expected,name):
        seen.append(name)
        if name=='libstdc++':raise ValueError('时间符号来源变化')
    def forbidden(*args,**kwargs):pytest.fail('来源核对前创建运行时执行器')
    monkeypatch.setattr(native_runtime,'require_source',source)
    monkeypatch.setattr(native_runtime,'RuntimeAP',forbidden)
    with pytest.raises(ValueError,match='时间符号来源变化'):
        native_runtime.collect(b'ap',b'cp',b'ipc',b'std',b'bad ELF',b'bad ELF')
    assert seen==['AP','CP','OSAL','libstdc++']


def test_runtime_module_pair_and_source_mode_are_required_before_input_io():
    from a7filters.baseline import audit
    with pytest.raises(ValueError,match='必须成对'):
        audit('/missing',ap_runtime_module='/missing')
    with pytest.raises(ValueError,match='启用界面研究'):
        audit('/missing',ap_runtime_module='/missing',cp_runtime_module='/missing')
