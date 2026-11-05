"""来源拒绝和原指令可观察契约，不将准备窗口升级为成像完成。"""
from pathlib import Path
import sys

import pytest

FEATURE = Path(__file__).resolve().parents[1]
ROOT = FEATURE.parents[1]
sys.path.insert(0, str(FEATURE))
from a7filters import cp_gamma_lineage406 as lineage


@pytest.mark.parametrize('raw', (b'', b'other-CP'))
def test_source_rejected_before_cpu_construction(monkeypatch, raw):
    def forbidden(*args):
        raise AssertionError('来源拒绝前不能构造CPU')
    monkeypatch.setattr(lineage, 'CpMachine', forbidden)
    with pytest.raises(ValueError):
        lineage.audit(raw)


def test_original_lineage_keeps_version_and_hardware_gates_closed():
    source = ROOT / '.local/fixed-custom-filters/integration52-source406/components/cpapp-b.bin'
    if not source.is_file():
        pytest.skip('本机未准备锁定4.06原CP，只运行来源拒绝契约')
    report = lineage.audit(source.read_bytes())
    assert report['status'] == 'PASS_ORIGINAL_A_Q_AND_GAMMA_PREPARATION_SOFTWARE_ONLY'
    assert len(report['producer_branches']) == 4
    assert {row['target'] for row in report['producer_branches']} == {'0x463bb8', '0x463cd4', '0x463db4'}
    assert [row['output'] for row in report['Gamma_constructor_banks']] == ['0x1f6ff74', '0x1f709f4']
    first, _, other = report['first_Gamma_uploads']
    assert first['A'] != other['A'] and first['descriptor'] == other['descriptor']
    assert report['owner_counter'][0]['owner'] == report['owner_counter'][-1]['owner']
    assert report['Q_pointer_lifecycle']['pointer_copy_does_not_copy_private_Capture_version'] is True
    assert report['bank_reset']['packed_banks_zero'] is True
    assert report['bank_reset']['retained_Q_fixture_still_reaches_register_boundary'] is True
    assert report['bank_reset']['original_scheduler_allows_this_interleaving_verified'] is False
    for key in ('bank_version_association_verified', 'special_2B_Gamma_lineage_closed',
                'production_admission_changed', 'actual_pixels_verified', 'hardware_emulated',
                'semaphore_or_RTOS_executed', 'register_helper_executed', 'camera_io', 'CP_modified'):
        assert report[key] is False
