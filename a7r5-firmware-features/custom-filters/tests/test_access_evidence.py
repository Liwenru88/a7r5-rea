"""错误组件必须在任何原指令执行前被拒绝。真实窗口由锁定DAT集成运行验证。"""
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from a7filters import access_evidence as evidence
from a7filters import native_paths
from a7filters import ui_evidence, target_ui, ap_ui_hooks, ui_cache, ui_resource_lookup, ui_resource_loader, resource_vm


@pytest.mark.parametrize('module,inputs', [(evidence,(b'wrong AP',b'wrong CP',b'wrong backup',b'wrong manager')),
                                         (native_paths,(b'wrong AP',b'wrong CP',False)),
                                         (ui_evidence,(b'wrong AP',b'wrong C++ library')),
                                         (target_ui,(b'wrong AP',b'wrong adapter')),
                                         (ap_ui_hooks,(b'wrong AP',b'wrong C++ library',b'wrong module')),
                                         (ui_cache,(b'wrong AP',b'wrong C++ library')),
                                         (ui_resource_lookup,(b'wrong AP',b'wrong resource library',{})),
                                         (ui_resource_loader,(b'wrong AP',b'wrong resource library',{}))])
def test_wrong_component_is_refused_before_emulation(monkeypatch,module,inputs):
    def forbidden(*args,**kwargs):
        pytest.fail('错误输入触发了原指令执行')
    monkeypatch.setattr(module,'ResourceMachine' if module is ui_resource_loader else 'arm64_cpu',forbidden)
    with pytest.raises(ValueError,match='AP不是已锁定4.06'):
        module.collect(*inputs)
    expected=hashlib.sha256(b'known component').hexdigest()
    evidence.require_source(b'known component',expected,'CP')
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):
        evidence.require_source(b'changed component',expected,'CP')


@pytest.mark.parametrize('gcc_raw',[None,b'changed libgcc'])
def test_hash_runtime_library_is_verified_before_module_or_cpu(monkeypatch,gcc_raw):
    def require(raw,digest,name):
        if name not in ('AP','libstdc++'):evidence.require_source(raw,digest,name)
    def forbidden(*args,**kwargs):
        pytest.fail('辅助库身份核对前加载了模块或启动模拟器')
    monkeypatch.setattr(ap_ui_hooks,'require_source',require)
    monkeypatch.setattr(ap_ui_hooks,'load_module',forbidden)
    monkeypatch.setattr(ap_ui_hooks,'RegistryMachine',forbidden)
    with pytest.raises(ValueError,match='libgcc_s不是已锁定4.06'):
        ap_ui_hooks.collect(b'AP checked separately',b'std checked separately',b'not loaded',gcc_raw)


def test_resource_library_is_verified_before_any_lookup(monkeypatch):
    def require(raw,digest,name):
        if name!='AP':evidence.require_source(raw,digest,name)
    def forbidden(*args,**kwargs):
        pytest.fail('资源库身份核对前启动了查找窗口')
    monkeypatch.setattr(ui_resource_lookup,'require_source',require)
    monkeypatch.setattr(ui_resource_lookup,'arm64_cpu',forbidden)
    with pytest.raises(ValueError,match='libObj不是已锁定4.06'):
        ui_resource_lookup.collect(b'AP checked separately',b'changed resource library',{})


def test_database_identity_is_checked_before_loading(monkeypatch):
    def require(raw,digest,name):
        if name not in ('AP','libObj'):evidence.require_source(raw,digest,name)
    def forbidden(*args,**kwargs):pytest.fail('数据库身份核对前启动资源机')
    monkeypatch.setattr(ui_resource_loader,'require_source',require)
    monkeypatch.setattr(ui_resource_loader,'ResourceMachine',forbidden)
    with pytest.raises(ValueError,match='global.xdb不是已锁定4.06'):
        ui_resource_loader.collect(b'AP checked',b'Obj checked',{ui_resource_loader.XDB_PATH:b'changed'})


@pytest.mark.parametrize('files',[{'/dev/null':b'x'*16},
                                  {'/usr/share/app/a.uxc':b'x'*(0x80000+1)}])
def test_memory_files_reject_device_paths_and_oversized_data_before_cpu(monkeypatch,files):
    monkeypatch.setattr(resource_vm,'require_source',lambda *args:None)
    def forbidden(*args,**kwargs):pytest.fail('内存文件准入前启动资源机')
    monkeypatch.setattr(resource_vm,'arm64_cpu',forbidden)
    with pytest.raises(ValueError,match='路径或尺寸越界'):
        resource_vm.ResourceMachine(b'Obj checked',files)
