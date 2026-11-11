"""真实HTTP覆盖工程扩展槽位后的预览格式选择，不替换编译器校验。"""
import copy
import http.client
import io
import json
from unittest.mock import patch

import numpy as np
from PIL import Image
import pytest
import tifffile

from test_native24_web import http_server, project
import core
import projects
import server


@pytest.mark.parametrize('slots,stored_format,selected,expected_format,input_kind', [
    ([12], 4, 12, 4, 'raw'),
    ([1, 13], 4, 13, 5, 'raw'),
    ([24], 4, 24, 5, 'image'),
    ([1], 5, 1, 5, 'image'),
    ([1, 13], 4, 1, 5, 'image'),
])
def test_saved_slot_preview_uses_effective_project_format(
        http_server, slots, stored_format, selected, expected_format, input_kind):
    value = projects.empty('槽位预览回归')
    value.update(format=stored_format, entries=project(slots)['entries'], selected=selected)
    projects.validate_state(value)
    store = projects.Store(server.RUNS)
    store.write(value)
    before = copy.deepcopy(store.get(value['id']))
    payload = b'preview-regression-input'
    calibrated = input_kind == 'raw'
    path = f"/api/preview?project={value['id']}&slot={selected}&input={input_kind}&grid_effect=1&raw_calibrated={int(calibrated)}"
    # 仅截住昂贵的异步解码边界，格式判断、上传落盘及BIN编译使用真实实现。
    with patch.object(server, 'PREVIEWS', {}), patch.object(server.PREVIEW_POOL, 'submit') as queue:
        connection = http.client.HTTPConnection('127.0.0.1', http_server.server_port, timeout=20)
        connection.request('POST', path, payload, headers={
            'Host': f'127.0.0.1:{http_server.server_port}',
            'X-R5-Token': server.TOKEN, 'Content-Type': 'application/octet-stream'})
        response = connection.getresponse()
        status, raw = response.status, response.read()
        connection.close()
        assert status == 202, raw
        preview = json.loads(raw)
        saved = server.RUNS/'_slot_previews'/'photo_previews'/preview['id']
        config = json.loads((saved/'slot_config.json').read_text())
        assert core.compiler.format_version(config) == expected_format
        decoded = core.compiler.unpack(core.compiler.pack(config))
        assert decoded['entries'] == [next(e for e in before['entries'] if e['number'] == selected)]
        assert queue.call_count == 1
        assert server.PREVIEWS[preview['id']]['slot'] == selected
        assert server.PREVIEWS[preview['id']]['raw_calibrated'] is calibrated
        assert (saved/('input.ARW' if input_kind == 'raw' else 'input.photo')).read_bytes() == payload
    assert store.get(value['id']) == before


def test_comparison_tiff_preserves_orientation_and_camera_lane_requires_jpeg(http_server):
    pixels = np.zeros((2, 3, 3), dtype=np.uint16)
    pixels[0, 0] = [65535, 32768, 0]
    buf = io.BytesIO()
    tifffile.imwrite(buf, pixels, photometric='rgb', compression='deflate',
                     extratags=[(274, 'H', 1, 6, False)])
    tif = buf.getvalue()

    def upload(payload, query='', token=server.TOKEN):
        connection = http.client.HTTPConnection('127.0.0.1', http_server.server_port, timeout=20)
        connection.request('POST', '/api/preview-comparison-image'+query, payload, headers={
            'X-R5-Token': token, 'Content-Type': 'application/octet-stream'})
        response = connection.getresponse()
        result = response.status, response.getheader('Content-Type'), response.read()
        connection.close()
        return result

    assert upload(tif, token='')[0] == 403
    status, mime, body = upload(tif)
    assert (status, mime) == (200, 'image/png')
    with Image.open(io.BytesIO(body)) as image:
        assert image.size == (2, 3)
        assert image.info['icc_profile']
        assert image.getpixel((1, 0)) == (255, 128, 0)
    assert upload(tif, '?kind=camera')[0] == 400
    jpg = io.BytesIO()
    Image.new('RGB', (3, 2), (50, 100, 150)).save(jpg, format='JPEG')
    assert upload(jpg.getvalue(), '?kind=camera')[:2] == (200, 'image/png')


def test_photo_metrics_report_independent_rows_and_the_delta_e_percentile(http_server):
    target = bytes([0]*6 + [255]*6)
    one_changed = bytes([255]*3) + target[3:]
    inverted = bytes(255-value for value in target)
    payload = target + target + one_changed + inverted
    path = '/api/preview-color-metrics?rows=model,calibrated,camera&width=2&height=2'

    def post(body, token=server.TOKEN):
        connection = http.client.HTTPConnection('127.0.0.1', http_server.server_port, timeout=20)
        connection.request('POST', path, body, headers={
            'X-R5-Token': token, 'Content-Type': 'application/octet-stream'})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    status, metrics = post(payload)
    assert status == 200, metrics
    assert metrics['model'] == dict(rgb_rmse=0, delta_e00_mean=0, delta_e00_p95=0)
    assert metrics['calibrated'] == pytest.approx(dict(rgb_rmse=127.5, delta_e00_mean=25, delta_e00_p95=85))
    assert metrics['camera'] == pytest.approx(dict(rgb_rmse=255, delta_e00_mean=100, delta_e00_p95=100))
    assert post(payload[:-1])[0] == 400
    assert post(payload, token='')[0] == 403
