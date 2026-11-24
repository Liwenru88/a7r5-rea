"""混合目录回归不能让局部 pytest 插件把未收到的报告误判失败。"""
import importlib.util
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

FEATURES = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('reported', [True, False])
def test_native_evidence_covers_its_own_selected_tests(tmp_path, monkeypatch, reported):
    path = FEATURES / 'firmware-runtime/tests/conftest.py'
    spec = importlib.util.spec_from_file_location('cpu_scope_plugin', path)
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    own = 'firmware-runtime/tests/test_tabs.py::sample'
    outside = 'research/photo-aspect-ratios/src/test_cp.py::sample'
    plugin.REPORTS = [dict(nodeid=own, when='call', outcome='passed')] if reported else []
    monkeypatch.setenv('A7R5_NATIVE24_EVIDENCE', str(tmp_path / 'report'))
    monkeypatch.setattr(plugin, 'sources', lambda: {})
    monkeypatch.setattr(plugin, 'sha', lambda path: 'receipt')
    session = SimpleNamespace(
        stability_state=dict(build=tmp_path, record=dict(AP_sha256='AP', CP_sha256='CP'), sources={}, started=time.monotonic()),
        config=SimpleNamespace(args=['one', 'two'], option=SimpleNamespace(keyword='', markexpr='', lf=False)),
        items=[SimpleNamespace(nodeid=own, path=FEATURES / 'firmware-runtime/tests/test_tabs.py'),
               SimpleNamespace(nodeid=outside, path=FEATURES / 'research/photo-aspect-ratios/src/test_cp.py')],
        exitstatus=0)
    plugin.pytest_sessionfinish(session, 0)
    result = json.loads((tmp_path / 'report/session-result.json').read_text())
    assert result['status'] == ('PASS' if reported else 'FAIL')
    assert result['tests'] == [own]
