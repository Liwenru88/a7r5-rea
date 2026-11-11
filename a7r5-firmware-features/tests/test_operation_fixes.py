"""修复后单项构建和全功能组件共存；不生成或验证新的 DAT。"""
import json
import hashlib
import importlib.util
import os
from pathlib import Path
import sys

import pytest

FEATURES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FEATURES))
from core import native24
from core.plan import make_plan


def test_repaired_look24_single_build_keeps_strict_component_identity(tmp_path, monkeypatch):
    folder = os.environ.get('A7R5_LOOK24_REPAIR_BUILD')
    if not folder:
        pytest.skip('需要当前修复后的原厂 4.00 单项组件')
    source = Path(folder)
    def reuse(work, plan, output, script, *options):
        output.mkdir(parents=True)
        record = json.loads((source / 'build.json').read_text())
        for name in ('build.json', *record['components']):
            os.link(source / name, output / name)
    monkeypatch.setattr(native24, 'run_builder', reuse)
    plan = make_plan(dict(base='ilce-7rm5-4.00', modules=['look24']))
    output, receipt = native24.build_runtime(tmp_path, plan, tmp_path)
    assert receipt['components'] == json.loads((source / 'build.json').read_text())['components']
    # 摘要保护仍应拒绝损坏的目标；只替换测试读取，不改动已构建文件。
    real_digest = native24.digest
    monkeypatch.setattr(native24, 'digest', lambda p: '0' * 64 if p.name == 'appFw.so' else real_digest(p))
    with pytest.raises(ValueError, match='摘要不符'):
        native24.build_runtime(tmp_path, plan, tmp_path / 'corrupt')


@pytest.fixture(scope='module')
def components():
    path = os.environ.get('A7R5_COMPONENT_CAPTURE')
    if not path:
        pytest.skip('需要本次修复的非安装组合组件')
    sys.path.insert(0, str(FEATURES / 'native24-combined/tests'))
    import replay
    view = Path(path)
    assert replay.candidate[0] == (view / 'appFw.so').read_bytes()
    assert replay.cp_raw == (view / 'cpapp-b.bin').read_bytes()
    spec = importlib.util.spec_from_file_location('operation_component_checks', FEATURES / 'tests/test_full419_integration.py')
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    return (None, view, replay.BUILD, replay.runtime_support), checks


def test_repaired_components_preserve_cp_boot_mapping_and_audio_guards(components):
    final, checks = components
    checks.test_actual_sound_page_keeps_original_root_and_rejects_corrupted_code_and_pte(final)


def test_repaired_components_keep_sound_menus_ntsc_and_framing_markers(components, tmp_path):
    final, checks = components
    checks.test_final_sound_menu_relocations_and_crc_use_packaged_components(final, tmp_path)
    checks.test_final_ntsc_and_marker_native_behavior(final)


def test_imaging_components_match_the_sealed_419_candidate(components):
    final, _ = components
    assert hashlib.sha256((final[1] / 'cpapp-b.bin').read_bytes()).hexdigest() == \
        'e5e31c36f3d17290eedca5845fdc76781d2b62d5effdd112ae1d534f5791ab12'
    capture = Path(os.environ['A7R5_ASPECT_CAPTURE'])
    for name, pin in [('AV-CAM.BIN', '23fb43cb2e5d79aad19414d375c9bb6df97ef3042ecb696e8424243e64ff55bc'),
                      ('libmpr.so', '46fad4e180a90006e5df246400fd4b281c7da5643701ed38d6ab645417efd236')]:
        assert hashlib.sha256((capture / name).read_bytes()).hexdigest() == pin
