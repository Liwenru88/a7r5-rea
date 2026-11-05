"""通过真实本机HTTP、批量合并和网页函数验证24槽导出。"""
import copy
import http.client
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'R5ColorLab/web'), str(ROOT / 'R5ColorLab/scripts'), str(ROOT / 'R5ColorLab/tests')]
import core
import server
import batch_training
import grid_distillation
import export_policy423
import test_compression_workflow as compression_fixtures


def project(slots):
    from stock_grids import catalog
    stock = catalog()[0]
    value = []
    for n in slots:
        e = copy.deepcopy(core.presets()[0][0])
        e.update(number=n, short_name=f'TEST{n}', full_name=f'容量测试槽 {n}')
        e['grid_5x9x9'] = copy.deepcopy(stock['grid_5x9x9'])
        value.append(e)
    cfg = core.config(value)
    cfg['export_sources'] = {str(n): dict(kind='stock', id=stock['id']) for n in slots}
    return cfg


@pytest.fixture
def http_server(tmp_path):
    with patch.object(server, 'RUNS', tmp_path):
        http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        yield http
        http.shutdown(); thread.join(timeout=5); http.server_close()


def request(service, method, path, body=None):
    conn = http.client.HTTPConnection('127.0.0.1', service.server_port, timeout=20)
    headers = {'Host': f'127.0.0.1:{service.server_port}', 'X-R5-Token': server.TOKEN, 'Content-Type': 'application/json'}
    conn.request(method, path, None if body is None else server.dump(body), headers)
    response = conn.getresponse(); status, raw = response.status, response.read(); conn.close()
    return status, raw


@pytest.mark.parametrize('slots,version', [(range(1, 13), 4), ([24], 5), (range(1, 25), 5)])
def test_http_bootstrap_validate_export_and_reimport(http_server, slots, version):
    status, raw = request(http_server, 'GET', '/api/bootstrap')
    assert status == 200, raw
    bootstrap = json.loads(raw)
    assert bootstrap['slot_limit'] == 24 and len(bootstrap['presets']) == 12
    assert bootstrap['max_project_bytes'] >= 2 * 1024 * 1024
    cfg = project(slots)
    status, raw = request(http_server, 'POST', '/api/validate', cfg)
    assert status == 200, raw
    status, raw = request(http_server, 'POST', '/api/export', cfg)
    assert status == 200, raw
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        binary = bundle.read('R5NATIVE.BIN')
        saved = json.loads(bundle.read('native_config.json'))
        audit = json.loads(bundle.read('export_audit.json'))
    assert saved == cfg
    assert audit['format_version'] == version
    assert audit['bytes'] == 128 + len(slots) * 2452
    assert core.compiler.unpack(binary)['entries'] == cfg['entries']
    assert len(audit['grid_sources']) == len(slots)
    status, raw = request(http_server, 'POST', '/api/validate', saved)
    assert status == 200, raw
    changed = copy.deepcopy(cfg)
    changed['entries'][-1]['grid_5x9x9']['coefficients'][0][0][0][0] += 1
    status, _ = request(http_server, 'POST', '/api/export', changed)
    assert status == 400


def test_slot24_fit_validation_and_overflow():
    body = dict(target_kind='lut', gamut='S-Gamut3', lut='test LUT placeholder', evaluations=1,
                number=24, short_name='TEST24', full_name='容量测试槽24')
    # 此处只验证提交与配方转换边界，不执行昂贵的色彩求解。
    assert server.validate_fit(copy.deepcopy(body))['number'] == 24
    for number in (25, 0, True):
        with pytest.raises(ValueError, match='1–24'):
            server.validate_fit(dict(body, number=number))


def test_slot24_compression_export_preserves_identity(tmp_path):
    job, key, _, _ = compression_fixtures.CompressionWorkflowTests().fixture(tmp_path)
    cfg = project([24]); cfg.pop('export_sources')
    (job / 'native_config.json').write_text(json.dumps(cfg))
    binary_bundle = grid_distillation.firmware_config(job, key)
    with zipfile.ZipFile(io.BytesIO(binary_bundle)) as bundle:
        saved = json.loads(bundle.read('native_config.json'))
        audit = json.loads(bundle.read('export_audit.json'))
        binary = bundle.read('R5NATIVE.BIN')
    assert binary[:8] == b'R5CUST5\0'
    assert audit['format_version'] == 5
    assert list(saved['export_sources']) == ['24']
    assert core.compiler.unpack(binary)['entries'][0]['number'] == 24


def test_real_native_fit_conversion_uses_slot24_without_color_change(tmp_path):
    import baseline
    from edit_parameter_context import ParameterContext, RuntimeColor
    capture, context = baseline.resolve(baseline.V45_ID)
    model = RuntimeColor.from_capture(capture, context)
    parameters = ParameterContext(model)
    recipe = dict(schema='r5-edit-native-color-fit/1', camera_apply_allowed=False,
                  complete_edit_fitter=False, renderer='measured-Edit-color-subchain-with-native-matrix-builder',
                  input_domain='Edit post-SSCS/pre-matrix integer RGB',
                  additional_compensation_matrix_enabled=False, compensation_grid_enabled=False,
                  source=dict(context=context, capture_report_sha256=core.sha((capture/'report.json').read_bytes()),
                              runtime_sha256=core.sha(model.runtime), raw_sha256=core.sha(model.raw), settings_sha256=core.sha(model.settings)),
                  parameters=dict(matrix_780f_hex=parameters.payload.hex(), cc1_direct_raw=parameters.cc1.tolist(),
                                  gamma_7806_y=parameters.gamma_y.tolist(), gamma_7805_x=parameters.axis.tolist()))
    source = tmp_path / 'recipe.json'; source.write_text(json.dumps(recipe))
    before = source.read_bytes()
    outputs = []
    for slot in (12, 24):
        converted, audit = core.compiler.from_fit(source, capture, slot, 'TEST', '转换测试')
        outputs.append(core.compiler.pack(converted))
        assert audit['format_version'] == (4 if slot == 12 else 5)
    # 使用真实原生配方读取和量化实现；这里只检验转换，不声称完成色彩训练。
    assert outputs[0][128+4:] == outputs[1][128+4:]
    assert source.read_bytes() == before


def test_calibrator_reads_v5_source_and_keeps_twelve_probe_format(monkeypatch):
    from test_native24 import load_codec
    codec = load_codec(ROOT / 'R5GridCalibrator/bin_v4.py')
    monkeypatch.syspath_prepend(str(ROOT / 'R5GridCalibrator'))
    monkeypatch.setitem(sys.modules, 'bin_v4', codec)
    import probe_sets
    source = project([24]); source.pop('export_sources')
    binary = codec.pack(source)
    packed, meta = probe_sets.build(binary, 24)
    assert meta['source_number'] == 24
    assert packed[:8] == b'R5CUST4\0' and len(codec.unpack(packed)['entries']) == 12


def test_full_batch_merges_24_and_never_truncates(tmp_path):
    files = [dict(filename=f'TEST{n:02d}.jpg', target_id=f'{n:032x}') for n in range(1, 25)]
    assert len(batch_training.folder_names(files)) == 24
    with pytest.raises(ValueError): batch_training.folder_names(files + [dict(filename='extra.jpg')])
    with patch.object(server.core, 'HERE', tmp_path), patch.object(server, 'JOBS', {}), \
            patch.object(server, 'validate_fit') as validate, patch.object(server.POOL, 'submit'):
        result = batch_training.submit(dict(files=files, options=dict(evaluations=1)), server)
        assert [call.args[0]['number'] for call in validate.call_args_list] == list(range(1, 25))
        destination = tmp_path / 'batches' / result['id']
        state = json.loads((destination / 'batch.json').read_text())
        configs = {item['id']: project([item['options']['number']]) for item in state['jobs']}
        jobs = {item['id']: dict(status='done', result=dict(grid_key='fixture')) for item in state['jobs']}
        # 训练任务完成是明确夹具；合并、格式选择、来源验证和写出执行实际实现。
        def validated(project_value, runs):
            return export_policy423.configuration(project_value), []
        with patch.object(server, 'JOBS', jobs), patch.object(server, 'work'), \
                patch.object(grid_distillation, 'firmware_config', side_effect=lambda path, *a, **kw: configs[path.name]), \
                patch.object(server.export_policy423, 'validate', side_effect=validated):
            batch_training.run(state, destination, server)
        assert state['status'] == 'done', state.get('error')
        binary = (destination / 'R5NATIVE.BIN').read_bytes()
        assert len(binary) == 58976 and binary[:8] == b'R5CUST5\0'
        assert [e['number'] for e in core.compiler.unpack(binary)['entries']] == list(range(1, 25))


def test_browser_slot_buttons_format_and_folder_limits():
    result = subprocess.run(['node', str(ROOT / 'tests/native24_ui.cjs'), str(ROOT / 'R5ColorLab/web/static/app.js')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['slots'] == 24


def test_browser_unified_training_and_duplicate_prevention():
    result = subprocess.run(['node', str(ROOT / 'tests/unified_training_ui.cjs'),
                             str(ROOT / 'R5ColorLab/web/static')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'PASS'
