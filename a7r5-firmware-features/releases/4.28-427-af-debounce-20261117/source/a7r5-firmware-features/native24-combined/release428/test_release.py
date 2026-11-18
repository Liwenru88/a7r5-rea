"""4.28 封包配置的定向身份测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import container_package as p


def test_428_identity_and_three_usr_files_only():
    assert p.VERSION == '4.28'
    assert len(p.COMPONENTS) == 4
    assert len(p.CandidatePatch._bindings) == 3
    assert set(p.CandidatePatch._bindings) == {
        '/lib/appFw.so',
        '/share/app/image_00_23_IPSX.uxc',
        '/share/app/image_00_32_IPSX.uxc',
    }
    assert p.COMPONENTS['appFw.so'] == '202289fa2ce9e1084b989941580d5eeeb82c837aa9c5971f85f129236096de1e'
    assert p.COMPONENTS['cpapp-b.bin'] == '8a722c463f6d52a3ee25d2a6739ef4f23a7ed0dae88c3650bf4c0c6d0fa55503'


def test_428_archive_change_checker_rejects_unlisted_changes():
    before = [dict(name='AP', size=1, sha256='old', crc32='old')]
    after = [dict(name='AP', size=1, sha256='new', crc32='new')]
    assert p.check_members(before, after, {'AP': 'new'}) == ['AP']


def test_428_output_roots_allow_persistent_builds_and_reject_stray_paths():
    root = p.ROOT
    assert p.output_allowed(root / 'a7r5-firmware-features/builds/x-y')
    assert p.output_allowed(root / '.local/x-y')
    assert not p.output_allowed(root / 'a7r5-firmware-features/releases/x-y')
    assert not p.output_allowed(Path('/tmp/x-y'))
