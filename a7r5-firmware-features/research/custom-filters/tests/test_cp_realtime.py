"""CP执行前像边界；真实窗口在锁定DAT集成审计中验证。"""
from pathlib import Path
import sys
import weakref
import struct

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a7filters import cp_machine, cp_realtime, target_cp406
from a7filters.access_evidence import AP_SHA
from a7filters.investigate import CP_BASE


def test_changed_cp_is_rejected_before_creating_machine(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('错误CP在身份核对前创建了执行器')
    monkeypatch.setattr(cp_realtime, 'CpMachine', forbidden)
    with pytest.raises(ValueError, match='CP不是已锁定4.06'):
        cp_realtime.collect(b'changed CP')
    with pytest.raises(ValueError, match='CP不是已锁定4.06'):
        cp_machine.CpMachine(b'changed CP')


def test_target_bridge_checks_both_components_before_elf_or_machine(monkeypatch):
    calls = []
    # AP的正确字节不作为单元测试输入；只在测试中确认第二个身份检查不能省略。
    def source(raw, expected, name):
        calls.append(name)
        if name == 'CP':
            raise ValueError('CP不是已锁定4.06')
        assert expected == AP_SHA
    monkeypatch.setattr(target_cp406, 'require_source', source)
    with pytest.raises(ValueError, match='CP不是已锁定4.06'):
        target_cp406.collect(b'AP fixture', b'changed CP', b'not ELF')
    assert calls == ['AP', 'CP']


@pytest.fixture
def isolated_machine(monkeypatch):
    # 只在测试中替换摘要门槛，执行微型Thumb程序检查隔离器本身；不代替CP证据。
    monkeypatch.setattr(cp_machine, 'require_source', lambda *args: None)
    return cp_machine.CpMachine(bytes.fromhex('012008607047'))


def test_explicit_ram_permissions_and_instruction_execution(isolated_machine):
    from unicorn import UcError
    m = isolated_machine
    target = cp_machine.WORK + 0x100
    assert m.run(CP_BASE, arguments=(0, target))['r0'] == 1
    assert m.word(target) == 1 and len(m.writes) == 1
    with pytest.raises(ValueError, match='显式RAM'):
        m.put(CP_BASE, b'\x00')
    with pytest.raises(UcError):
        m.run(CP_BASE, arguments=(0, CP_BASE))


def test_unmapped_access_scope_overlap_and_ram_budget_are_rejected(isolated_machine):
    from unicorn import UcError
    m = isolated_machine
    with pytest.raises(UcError):
        m.run(CP_BASE, arguments=(0, 0x1234))
    for address, size in ((CP_BASE, 4096), (cp_machine.WORK, 4096),
                           (0x1200001, 4096), (0x1200000, 3),
                           (0x2000, 4096), (0x1200000, 0x400000)):
        with pytest.raises(ValueError):
            m.map_ram(address, size)
    assert m.ram_bytes == 0x20000


def test_explicit_semaphore_model_never_acks_an_image(isolated_machine):
    m = isolated_machine
    state = m.model_semaphore()
    m.register('r0', 0x24)
    m.register('lr', cp_machine.STOP | 1)
    m._code(m.cpu, 0x5b8f58, 4, None)
    assert state['held'] and m.register('r0') == 0
    m.register('r0',0x24)
    with pytest.raises(ValueError,match='阻塞互斥模型未获锁'):
        m._code(m.cpu,0x5b8d6c,4,None)
    m.register('r0', 0x24)
    m._code(m.cpu, 0x5b8f58, 4, None)
    assert m.register('r0') == 1
    m.register('r0', 0x24)
    m._code(m.cpu, 0x5b8910, 4, None)
    assert not state['held']
    m.register('r0', 0x24)
    with pytest.raises(ValueError, match='未持有'):
        m._code(m.cpu, 0x5b8910, 4, None)
    m.register('r0', 0x25)
    with pytest.raises(ValueError, match='未声明'):
        m._code(m.cpu, 0x5b8f58, 4, None)
    assert [e['operation'] for e in m.semaphore_events] == ['acquire', 'acquire', 'release']


def test_cpu_hooks_do_not_keep_dead_machine_alive(isolated_machine):
    # 保留CPU及其回调，删除所有者后引用必须能释放；不依赖循环GC回收CP映像。
    # 第二个执行器用于隔离pytest持有的fixture寿命。
    other = cp_machine.CpMachine(bytes.fromhex('7047'))
    ref = weakref.ref(other)
    cpu = other.cpu
    del other
    assert ref() is None and cpu is not None


def test_initialized_data_requires_exact_descriptor_and_stays_non_executable(monkeypatch):
    from unicorn import UcError
    monkeypatch.setattr(cp_machine, 'require_source', lambda *args: None)
    raw = bytearray(0x108f000)
    raw[:6] = bytes.fromhex('012008607047')
    struct.pack_into('<3I', raw, 0x2013c, 0xf57000, 0x117f5c, 0x107f000)
    m = cp_machine.CpMachine(bytes(raw))
    target = 0x10ff000
    for at, size in ((CP_BASE,4096), (0x107e000,4096), (0x1196000,8192),
                      (target+1,4096), (target,3)):
        with pytest.raises(ValueError):
            m.enable_initialized_data(at, size)
    m.enable_initialized_data(target,4096)
    assert m.run(CP_BASE, arguments=(0,target))['r0']==1 and m.word(target)==1
    with pytest.raises(ValueError):
        m.enable_initialized_data(target,4096)
    with pytest.raises(UcError):
        m.run(target)
    with pytest.raises(ValueError):
        m.put(CP_BASE,b'\x00')
    assert m.ram_bytes==0x21000
    altered=bytearray(raw)
    struct.pack_into('<I',altered,0x20140,0x117f60)
    other=cp_machine.CpMachine(bytes(altered))
    with pytest.raises(ValueError,match='数据段描述符'):
        other.enable_initialized_data(target,4096)


def test_bss_prefix_requires_exact_descriptor_source_span_and_stays_nx(monkeypatch):
    from unicorn import UcError
    monkeypatch.setattr(cp_machine,'require_source',lambda *args:None)
    raw=bytearray(0x1095000)
    raw[:6]=bytes.fromhex('012008607047')
    struct.pack_into('<3I',raw,0x20148,0x106f000,0x8a3b40,0x1197000)
    target=0x119c000
    raw[target-CP_BASE:target-CP_BASE+4]=b'\x6a'*4
    m=cp_machine.CpMachine(bytes(raw))
    for at,size in ((0x1196000,8192),(target+1,4096),(target,3),(target,8192),(0x1200000,4096)):
        with pytest.raises(ValueError):m.enable_bss_prefix(at,size)
    m.enable_bss_prefix(target,4096)
    assert m.word(target)==0x6a6a6a6a
    assert m.run(CP_BASE,arguments=(0,target))['r0']==1 and m.word(target)==1
    with pytest.raises(UcError):m.run(target)
    with pytest.raises(ValueError):m.enable_bss_prefix(target,4096)
    altered=bytearray(raw);struct.pack_into('<I',altered,0x2014c,0x8a3b44)
    other=cp_machine.CpMachine(bytes(altered))
    with pytest.raises(ValueError,match='BSS描述符'):other.enable_bss_prefix(target,4096)
