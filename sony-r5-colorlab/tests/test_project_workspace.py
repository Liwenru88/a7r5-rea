"""通过本机 HTTP 验证工程保存、编译和独立迁移。"""
import copy
import http.client
import io
import json
import zipfile
from unittest.mock import patch

import pytest

import core
import projects
import server
from test_bin_import import upload
from test_native24_web import http_server, project, request


def call(service, action, body, status=200):
    actual, raw = request(service, 'POST', '/api/projects/' + action, body)
    assert actual == status, raw
    return json.loads(raw)


def ref(value):
    return {k: value[k] for k in ('id', 'revision')}


def open_project(service, value):
    status, raw = request(service, 'GET', '/api/projects/open?id=' + value['id'])
    assert status == 200, raw
    return json.loads(raw)


def save(service, value, **edits):
    return call(service, 'save', {**ref(value), **{k: value[k] for k in projects.EDITABLE}, **edits})


def export(service, value, **flags):
    status, raw = request(service, 'POST', '/api/projects/export', {**ref(value), **flags})
    assert status == 200, raw
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        payload = archive.read('R5NATIVE.BIN')
        return payload, json.loads(archive.read('export_audit.json'))


def import_bin(service, slots, version):
    data = project(slots)
    data.pop('export_sources')
    data['schema'] = core.compiler.SCHEMAS[version]
    payload = core.compiler.pack(data)
    status, raw = upload(service, payload)
    assert status == 200, raw
    return payload, json.loads(raw)['audit']['binary_sha256']


@pytest.mark.parametrize('slots,version', [([1, 12], 4), ([1, 12], 5), ([1, 24], 5)])
def test_edit_imported_and_export_without_training(http_server, slots, version):
    original, digest = import_bin(http_server, slots, version)
    value = call(http_server, 'create', {'name': '原始配方', 'sha256': digest})
    payload, audit = export(http_server, value)
    assert payload == original and audit['format_version'] == version

    value = open_project(http_server, value)
    edits = copy.deepcopy(value['entries'])
    entry = edits[0]
    entry['full_name'] = '手动调参'
    entry['grid_5x9x9']['coefficients'][0][0][0][0] = 7
    entry['gamma_native_129'][-1] = entry['gamma_native_129'][-2]
    entry['cc1_delta'][0][0] = 3
    entry['block13'][0][0][0] = 4
    working = save(http_server, value, drafts={'1': {'entry': entry, 'source': value['sources']['1']}})
    assert open_project(http_server, value)['drafts']['1']['entry'] == entry
    call(http_server, 'export', ref(working), status=400)
    assert export(http_server, working, allow_saved=True)[0] == original

    working = open_project(http_server, working)
    saved = save(http_server, working, entries=edits, drafts={})
    assert saved['history']['1'][0]['entry'] == value['entries'][0]
    updated, audit = export(http_server, saved)
    assert updated != original
    assert core.compiler.unpack(updated)['entries'] == edits
    assert audit['binary_sha256'] == core.sha(updated)
    assert (server.RUNS / '_bin_imports' / (digest + '.bin')).read_bytes() == original


def test_backup_reopens_in_clean_store_and_rejects_collision(http_server, tmp_path):
    original, digest = import_bin(http_server, [24], 5)
    first = call(http_server, 'create', {'name': '可迁移', 'sha256': digest})
    call(http_server, 'merge', {**ref(first), 'sha256': digest}, status=409)
    assert open_project(http_server, first) == first

    edited = copy.deepcopy(first['entries'][0])
    edited['short_name'] = 'DRAFT'
    saved = save(http_server, first, selected=24, settings={'weightGray': '2'},
                 jobs={'a'*32: 24}, drafts={'24': {'entry': edited, 'source': first['sources']['24']}})
    stale = {**ref(first), **{k: first[k] for k in projects.EDITABLE}}
    call(http_server, 'save', stale, status=409)
    assert open_project(http_server, first) == saved
    status, archive = request(http_server, 'POST', '/api/projects/backup', ref(saved))
    assert status == 200
    with patch.object(server, 'RUNS', tmp_path / 'another-machine'):
        connection = http.client.HTTPConnection('127.0.0.1', http_server.server_port, timeout=20)
        try:
            connection.request('POST', '/api/projects/restore', archive, headers={
                'X-R5-Token': server.TOKEN, 'Content-Type': 'application/octet-stream'})
            response = connection.getresponse()
            status, raw = response.status, response.read()
        finally:
            connection.close()
        assert status == 200, raw
        restored = json.loads(raw)
        assert restored['id'] != first['id']
        assert all(restored[k] == saved[k] for k in projects.EDITABLE)
        assert export(http_server, restored, allow_saved=True)[0] == original

    with pytest.raises(ValueError):
        projects.restore(projects.zip_bytes({'../project.json': b'{}'}))
    with zipfile.ZipFile(io.BytesIO(archive)) as packed:
        broken = json.loads(packed.read('project.json'))
    broken['imports'][digest] = 'AAAA'
    with pytest.raises(ValueError, match='原始 BIN 校验失败'):
        projects.restore(projects.zip_bytes({'project.json': projects.encoded(broken)}))


def test_merge_free_slots_and_invalid_save_is_atomic(http_server):
    _, digest = import_bin(http_server, [1], 4)
    value = call(http_server, 'create', {'name': '目标', 'sha256': digest})
    _, high = import_bin(http_server, [24], 5)
    merged = call(http_server, 'merge', {**ref(value), 'sha256': high})
    assert [entry['number'] for entry in merged['entries']] == [1, 24]
    invalid = copy.deepcopy(merged['entries'])
    invalid[-1]['grid_5x9x9']['coefficients'][0][0][0][0] = 64
    call(http_server, 'save', {**ref(merged), **{k: merged[k] for k in projects.EDITABLE},
                              'entries': invalid}, status=400)
    assert open_project(http_server, value) == merged


def test_export_preview_matches_each_mode_and_original_bin(http_server):
    _, digest = import_bin(http_server, [1, 2], 4)
    original = call(http_server, 'create', {'name': '原始库', 'sha256': digest})
    edited = dict(original['entries'][0], full_name='已改名')
    high = dict(original['entries'][1], number=24, full_name='新槽')
    current = save(http_server, original, entries=[edited], sources={'1': original['sources']['1']},
                   drafts={'24': {'entry': high, 'source': None}})
    preview = call(http_server, 'export-preview', ref(current))
    assert preview['draft_slots'] == [24]
    assert preview['saved']['slots'] == [{'number': 1, 'name': '已改名'}]
    assert preview['saved']['format'] == 4 and preview['with_drafts']['format'] == 5
    assert preview['saved']['differences'][digest] == {'added': [], 'changed': [1], 'removed': [2]}
    assert preview['with_drafts']['differences'][digest] == {'added': [24], 'changed': [1], 'removed': [2]}
    assert open_project(http_server, current) == current
    call(http_server, 'export-preview', ref(original), status=409)


@pytest.mark.parametrize('slot,version', [(12, 4), (24, 5)])
def test_shared_st_export_preserves_stock_differences_without_editing_project(http_server, slot, version):
    recipe = project([1, slot])
    recipe.pop('export_sources')
    first, second = recipe['entries']
    first['cc1_delta'][0][7] = 0
    first['cc1_delta'][1][7] = first['cc1_delta'][2][7] = 0
    first['block13'][0][0][0] = 8191
    original = core.compiler.pack(recipe)
    status, raw = upload(http_server, original)
    assert status == 200, raw
    digest = json.loads(raw)['audit']['binary_sha256']
    value = call(http_server, 'create', {'name': '共享增量', 'sha256': digest})
    draft = copy.deepcopy(second)
    draft['cc1_delta'][0][7] = 0
    draft['cc1_delta'][1][7] = draft['cc1_delta'][2][7] = 0
    value = save(http_server, value, drafts={str(slot): {'entry': draft, 'source': None}})

    mode = {'endpoint_mode': 'shared-st'}
    limited = {'cc1': [1], 'matrix': [1]}
    preview = call(http_server, 'export-preview', ref(value))
    assert preview['saved']['differences'][digest]['changed'] == []
    assert preview['shared_st']['saved']['differences'][digest]['changed'] == [1]
    assert preview['shared_st']['saved']['limited'] == limited
    assert preview['shared_st']['with_drafts']['limited'] == {'cc1': [1, slot], 'matrix': [1]}
    call(http_server, 'export', {**ref(value), **mode}, status=400)
    call(http_server, 'export', {**ref(value), 'allow_saved': True, 'endpoint_mode': 'typo'}, status=400)
    assert open_project(http_server, value) == value

    binary, audit = export(http_server, value, allow_saved=True, **mode)
    assert audit['endpoint_export']['limited_slots'] == limited
    result = core.compiler.unpack(binary)
    assert core.compiler.format_version(result) == version
    converted, untouched = result['entries']
    assert untouched == second
    assert [row[7] for row in converted['cc1_delta']] == [197, -154, -197]
    assert [plane[0][0] for plane in converted['block13']] == [8163, 8160, 8191]
    for key in ('number', 'short_name', 'full_name', 'gamma_native_129', 'grid_5x9x9'):
        assert converted[key] == first[key]
    current = open_project(http_server, value)
    assert current['entries'] == value['entries'] and current['drafts'] == value['drafts']
    assert export(http_server, current, allow_saved=True)[0] == original


@pytest.mark.parametrize('slot,version', [(12, 4), (24, 5)])
def test_median_offset_export_limits_only_secondary_endpoints(http_server, slot, version):
    recipe = project([1, slot])
    recipe.pop('export_sources')
    first, edge = recipe['entries']
    edge['cc1_delta'] = [[0, 1023, 0, 0, 1023, 0, 0, 0], [0]*8, [0]*8]
    edge['block13'][0][0] = [8191, -8192, 0, 0, 0, 0]
    original = core.compiler.pack(recipe)
    status, raw = upload(http_server, original)
    assert status == 200, raw
    digest = json.loads(raw)['audit']['binary_sha256']
    value = call(http_server, 'create', {'name': '通用偏差', 'sha256': digest})
    draft = dict(first, number=2, full_name='新增草稿')
    value = save(http_server, value, drafts={'2': {'entry': draft, 'source': None}})

    preview = call(http_server, 'export-preview', ref(value))['median_offset']
    limited = {'cc1': [slot], 'matrix': [slot]}
    assert preview['saved']['limited'] == preview['with_drafts']['limited'] == limited
    assert preview['saved']['differences'][digest] == {'added': [], 'changed': [1, slot], 'removed': []}
    assert preview['with_drafts']['differences'][digest]['added'] == [2]
    assert open_project(http_server, value) == value

    binary, audit = export(http_server, value, allow_saved=True, endpoint_mode='median-offset')
    endpoint_audit = audit['endpoint_export']
    assert endpoint_audit['mode'] == 'median-offset' and endpoint_audit['anchor'] == 'B'
    assert endpoint_audit['reference_looks'] == ['ST', 'PT', 'NT', 'VV', 'VV2', 'FL', 'IN', 'SH']
    assert endpoint_audit['limited_slots'] == limited
    assert len(endpoint_audit['offsets_sha256']) == 64
    decoded = core.compiler.unpack(binary)
    assert core.compiler.format_version(decoded) == version
    normal, converted_edge = decoded['entries']
    assert normal['cc1_delta'][1:] == [[0, 21, -72, -7, 32, -54, 0, -73],
                                       [-34, 55, 1, 0, 53, -106, 0, -102]]
    assert converted_edge['cc1_delta'][1:] == [[0, 0, -72, -7, 0, 0, 0, 0],
                                               [-34, 0, 1, 0, 0, 0, 0, 0]]
    assert converted_edge['block13'][1][0] == [8191, -8168, -76, 105, 85, -93]
    assert converted_edge['block13'][2][0] == [8191, -8180, 2, 45, 244, -193]
    for before, after in zip(recipe['entries'], decoded['entries']):
        for field in ('cc1_delta', 'block13'):
            assert before[field][0] == after[field][0]
        for field in ('number', 'short_name', 'full_name', 'gamma_native_129', 'grid_5x9x9'):
            assert before[field] == after[field]
    current = open_project(http_server, value)
    assert all(current[key] == value[key] for key in projects.EDITABLE)
    assert export(http_server, current, allow_saved=True)[0] == original


def test_compare_slot_rebuilds_edited_gamma_on_measured_samples(http_server):
    entry = project([3])['entries'][0]
    tail_only = copy.deepcopy(entry)
    tail_only['gamma_native_129'][-1] = tail_only['gamma_native_129'][-2]
    status, raw = request(http_server, 'POST', '/api/compare-slot',
                          {'saved': entry, 'draft': tail_only, 'endpoint': 2})
    assert status == 200, raw
    result = json.loads(raw)
    assert result['samples'] == 96 and result['endpoint'] == 2
    assert result['saved'] == result['draft'] and result['mae'] == 0
    changed = dict(entry, gamma_native_129=[value // 2 for value in entry['gamma_native_129']])
    status, raw = request(http_server, 'POST', '/api/compare-slot',
                          {'saved': entry, 'draft': changed, 'endpoint': 0})
    assert status == 200, raw
    result = json.loads(raw)
    assert result['saved'] != result['draft'] and result['rmse'] > 0
    assert result['gamma_tail_changed']


def test_training_reuses_same_project_request_and_retries_explicitly(http_server):
    import grid_distillation
    value = call(http_server, 'create', {'name': '重训'})
    body = dict(number=3, short_name='TEST', full_name='TEST', evaluations=5,
                lut='test LUT', gamut='S-Gamut3', project_id=value['id'], compression_training=True)
    with patch.object(server, 'JOBS', {}), patch.object(server.POOL, 'submit') as queue:
        status, raw = request(http_server, 'POST', '/api/fit', body)
        assert status == 202, raw
        job_id = json.loads(raw)['id']
        server.JOBS[job_id].update(status='done', result={'grid_key': 'test'})
        server.write_job(job_id)
        with patch.object(grid_distillation, 'firmware_config', return_value=core.config([])):
            status, raw = request(http_server, 'POST', '/api/fit', body)
        assert status == 202 and json.loads(raw) == {'id': job_id, 'number': 3, 'reused': True}
        assert queue.call_count == 1
        status, raw = request(http_server, 'POST', '/api/fit/retry', {'id': job_id})
        assert status == 202, raw
        retried = json.loads(raw)['id']
        assert retried != job_id
        assert server.fit_request(job_id) == server.fit_request(retried)
        assert queue.call_count == 2


def test_batch_retry_only_queues_failed_slots(tmp_path):
    import batch_training
    files = [dict(filename='AA.tiff', number=3, target_id='a'*32),
             dict(filename='BB.tiff', number=24, target_id='b'*32)]
    with patch.object(server.core, 'HERE', tmp_path), patch.object(server, 'JOBS', {}), \
            patch.object(server, 'validate_fit'), patch.object(server.POOL, 'submit') as queue:
        initial = batch_training.submit(dict(files=files), server)
        old_a, old_b = initial['jobs']
        assert [job['number'] for job in initial['jobs']] == [3, 24]
        server.JOBS[old_a['id']]['status'] = 'done'
        server.JOBS[old_b['id']]['status'] = 'error'
        retried = batch_training.retry(initial['id'], server)
        new_a, new_b = retried['jobs']
        assert new_a == old_a
        assert new_b['number'] == 24 and new_b['id'] != old_b['id']
        state = queue.call_args.args[1]
        assert [item['id'] for item in state['jobs'] if not item.get('reused')] == [new_b['id']]
