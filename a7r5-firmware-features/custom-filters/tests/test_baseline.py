"""基线入口的外部契约；合成输入只验证拒绝，不冒充真实固件。"""
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a7filters.baseline import check_file, check_component, regular_path, output_path, write_report
from a7filters.baseline import audit


def test_identity_and_same_length_mutation(tmp_path):
    path = tmp_path / 'input.dat'
    path.write_bytes(b'baseline')
    expected = {'bytes': 8, 'sha256': hashlib.sha256(b'baseline').hexdigest()}
    assert check_file(path, expected)['sha256'] == expected['sha256']
    path.write_bytes(b'Baseline')
    with pytest.raises(ValueError, match='摘要'):
        check_file(path, expected)


def test_input_links_devices_and_wrong_size_are_refused(tmp_path):
    path = tmp_path / 'input'
    path.write_bytes(b'data')
    link = tmp_path / 'alias'
    link.symlink_to(path)
    expected = {'bytes': 5, 'sha256': '0' * 64}
    for forbidden in (link, Path('/dev/null'), Path('/Volumes/SD/BODYDATA.DAT')):
        with pytest.raises(ValueError):
            check_file(forbidden, expected)
    with pytest.raises(ValueError, match='长度'):
        check_file(path, expected)
    for forbidden in ('/Users/../dev/null', '/Users/../Volumes/SD/BODYDATA.DAT'):
        for boundary in (regular_path, output_path):
            with pytest.raises(ValueError, match='设备'):
                boundary(forbidden)


def test_component_contract_and_no_success_report_overwrite(tmp_path):
    expected = {'bytes': 2, 'sha256': hashlib.sha256(b'AP').hexdigest()}
    assert check_component('AP', b'AP', expected)['bytes'] == 2
    with pytest.raises(ValueError, match='AP'):
        check_component('AP', b'CP', expected)
    output = tmp_path / 'receipt.json'
    write_report(output, {'status': 'PASS'})
    before = output.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        write_report(output, {'status': 'FAILED'})
    assert output.read_bytes() == before
    link = tmp_path / 'receipt-link'
    link.symlink_to(tmp_path / 'not-created')
    with pytest.raises(ValueError):
        write_report(link, {})
    assert not (tmp_path / 'not-created').exists()


def test_adapter_requires_ui_mode_before_any_input_read(monkeypatch):
    def forbidden(*args,**kwargs):
        pytest.fail('参数组合拒绝前发生了文件读取')
    monkeypatch.setattr('a7filters.baseline.regular_path',forbidden)
    with pytest.raises(ValueError,match='界面研究'):
        audit('/does-not-exist.dat',ui_adapter='/does-not-exist.elf')
    with pytest.raises(ValueError,match='界面研究'):
        audit('/does-not-exist.dat',ap_ui_module='/does-not-exist.elf')
    with pytest.raises(ValueError,match='接入研究'):
        audit('/does-not-exist.dat',cp_parameter_adapter='/does-not-exist.elf')
    with pytest.raises(ValueError,match='接入研究'):
        audit('/does-not-exist.dat',cp_atomic_adapter='/does-not-exist.elf')
    with pytest.raises(ValueError,match='成对'):
        audit('/does-not-exist.dat',ap_handshake_module='/does-not-exist.elf')
    with pytest.raises(ValueError,match='接入研究'):
        audit('/does-not-exist.dat',ap_handshake_module='/does-not-exist.elf',cp_handshake_module='/no-cp.elf')
