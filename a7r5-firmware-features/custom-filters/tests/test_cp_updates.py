"""候选调用地址独立对照Capstone；坏CP在扫描之前拒绝。"""
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a7filters.cp_updates import thumb_call, thumb_mov, collect
from a7filters import cp_updates


@pytest.mark.parametrize('raw,address', [('00f000f8', 0x1000),
                                         ('fff7feff', 0x1000),
                                         ('00f000e8', 0x1002)])
def test_thumb_call_matches_independent_decoder(raw, address):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    value = bytes.fromhex(raw)
    insn = next(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(value, address))
    assert insn.mnemonic in ('bl', 'blx')
    assert thumb_call(*struct.unpack('<HH', value), address) == int(insn.op_str.lstrip('#'), 0)


def test_wrong_cp_cannot_enter_scanner():
    with pytest.raises(ValueError, match='CP不是已锁定4.06'):
        collect(b'wrong CP')


@pytest.mark.parametrize('raw', ['4ef6f064', 'c0f26414', '4bf27001', 'c0f29211'])
def test_thumb_mov_matches_independent_decoder(raw):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    value = bytes.fromhex(raw)
    insn = next(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(value, 0x1000))
    mnemonic, register, immediate = thumb_mov(*struct.unpack('<HH', value))
    assert insn.mnemonic == mnemonic
    assert insn.op_str == f'r{register}, #{immediate:#x}'


@pytest.mark.parametrize('count', [300, 600])
def test_large_candidate_population_keeps_exact_counts_and_bounded_windows(monkeypatch, count):
    # 合成流只验证报告预算，不放宽生产组件校验。
    monkeypatch.setattr(cp_updates, 'require_source', lambda *args: None)
    raw = bytes.fromhex('4bf27001c0f29211') * count
    result = collect(raw)
    assert result['immediate_candidate_counts']['context'] == count
    assert len(result['immediate_sites']['context']) == min(count, 512)
    assert len(result['immediate_candidates']) == 32
    assert result['immediate_windows_truncated']
    assert result['candidate_only'] and not result['realtime_update_proven']
