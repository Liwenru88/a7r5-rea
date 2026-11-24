"""构建闭环、原厂委派和诊断边界。"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct

import pytest
from elftools.elf.elffile import ELFFile

from replay import AP, BUILD, Replay, candidate, receipt, recipe


def test_continuous_derivation_and_owned_sources_match_compiled_candidate():
    rows = json.loads((BUILD / 'work/derive-ledger.json').read_text())
    latest = {}
    for row in rows:
        if row['path'] in latest:
            assert row['before_sha256'] == latest[row['path']]
        latest[row['path']] = row['after_sha256']
    for name, value in latest.items():
        assert hashlib.sha256((BUILD / 'work' / name).read_bytes()).hexdigest() == value
    here = Path(__file__).resolve().parents[1]
    for name, value in receipt['owned_sources'].items():
        assert hashlib.sha256((here / name).read_bytes()).hexdigest() == value
    assert receipt['CP_code_bytes'] <= receipt['contract']['CP_code_capacity']
    assert receipt['stack_budget']['conservative_sum'] + receipt['stack_budget']['external_reserve'] < 262144


def test_ambiguous_replacement_is_rejected():
    path = Path(__file__).resolve().parents[1] / 'stability.py'
    spec = importlib.util.spec_from_file_location('stable_build_contract', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for text in ('absent', 'before before'):
        with pytest.raises(ValueError, match='替换次数'):
            module.replace_exact(text, 'before', 'after')


@pytest.mark.parametrize('base', [0, 0x10000000])
def test_retired_private_page_only_delegates_native_factories(base):
    ap = AP(candidate[0])
    if base:
        ap.cpu.mem_map(base, 0x9200000)
        elf = ELFFile(io.BytesIO(candidate[0]))
        for segment in elf.iter_segments():
            if segment['p_type'] == 'PT_LOAD':
                ap.write(base + segment['p_vaddr'], segment.data())
        for at, info, addend in struct.iter_unpack('<QQq', elf.get_section_by_name('.rela.dyn').data()):
            if info == 1027:
                ap.write(base + at, struct.pack('<Q', base + addend))
        ap.symbols = {key: value + base for key, value in ap.symbols.items()}
    calls = []
    for name, native in [('r5_filter_parent_presenter425', 0x1d90c7c),
                         ('r5_filter_controller425', 0x1d2e488), ('r5_filter_presenter425', 0x1e1e1a4)]:
        ap.stub(native + base, lambda a, target=native: calls.append((target, tuple(a.arg(i) for i in range(6)))) or 0x12345)
        assert ap.call(name, 1, 2, 3, 4, 5, 6) == 0x12345
    assert [args for _, args in calls] == [(1, 2, 3, 4, 5, 6)] * 3
    assert ap.call('r5_filter_page_text425', 0x02ff4502) == 0


def test_ram_diagnostics_do_not_write_sd_and_remain_bounded():
    r = Replay(files={'R5NATIVE.BIN': recipe()})
    r.ap.stubs.pop(r.ap.symbols['r5_log420_emit'])
    def unexpected_write(ap):
        raise AssertionError('RAM诊断不得写SD')
    r.ap.stub(0x3691174, unexpected_write)
    r.boot()
    stage, values = r.ap.DATA + 0x7c000, r.ap.DATA + 0x7c100
    r.ap.write(stage, b'BOUNDED_TEST\0')
    for i in range(100):
        r.ap.write(values, struct.pack('<I', i))
        assert r.ap.call('r5_log420_emit', ord('A'), stage, values, 1) == 0
    records = r.ap.words(r.ap.symbols['r5_log420_state'] + 16, 1)[0]
    assert records >= 100
    last = r.ap.symbols['r5_ram_log425'] + ((records - 1) & 15) * 108
    assert r.ap.string(last).startswith('BOUNDED_TEST')
    assert r.ap.words(last + 40, 2) == (1, 99)
    assert not [e for e in r.trace if e[0] == 'card_open']
    r.record('stable-ram-log')
