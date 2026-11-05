"""完整候选到普通目录的实际C事务；没有相机/SD或默认颜色后端。"""
import ctypes as c
import hashlib
import math
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grid_support import samples, Progress, Report, cube
from joint_support import seed, model, Predict
from import_support import HOME, Asset, ASSET_BYTES, SCHEMA, Request, Candidate, ImportWork, ReportWork, bind
from test_native_persistence import LocalStore, alloc, Document, Io, Phase, document
from test_native_slots import Preset, preset


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    target = tmp_path_factory.mktemp('import') / 'native.so'
    names = ('af_joint.c', 'af_joint_fit.c', 'af_joint_asset.c', 'af_joint_report.c', 'af_import.c',
             'af_grid.c', 'af_grid_fit.c', 'af_cube.c', 'af_sha256.c', 'af_slots.c', 'af_document.c',
             'af_record.c', 'af_store.c', 'af_persist.c', 'af_posix.c', 'af_ui.c')
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
        *[str(HOME / 'native' / n) for n in names], str(HOME / 'tests/native_joint_target.c'),
        str(HOME / 'tests/native_import_target.c'), '-o', str(target)],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return bind(c.CDLL(str(target)))


def request(api, transform=None):
    transform = transform or (lambda r, g, b: (r*1.015625+(g-r)/64, g*1.015625+(b-g)/64, b*1.015625+r*b/64))
    _, _, text = cube(api, transform)
    # 保留全部缓冲和回调的明确拥有者。
    raw = text.encode() if isinstance(text, str) else text
    q = Request()
    q._source, q._name = c.create_string_buffer(raw), c.create_string_buffer('暖色试验'.encode())
    q.source, q.source_bytes = c.addressof(q._source), len(raw)
    q.name, q.name_bytes = c.addressof(q._name), len('暖色试验'.encode())
    q._callback = Predict(('af_joint_synthetic_predict', api)); q._model = model(q._callback); q.model = c.pointer(q._model)
    q.initial = preset(0); q._seed = seed(); q.seed = c.pointer(q._seed)
    q._training = samples([(.1+.6*r, .15+.55*g, .12+.5*b) for b in range(2) for g in range(2) for r in range(2)])
    q._validation = samples([(.22, .22, .22, 1), (.41, .41, .41, 1), (.61, .39, .28, 2), (.8, .2, .55, 0)])
    q.training, q.training_count = q._training, len(q._training)
    q.validation, q.validation_count = q._validation, len(q._validation)
    q.options.evaluations = 65
    for n, value in [('gamma_step', 256), ('tone_step', 16), ('matrix_step', 16), ('cc1_step', 16), ('grid_step', 4)]:
        setattr(q.options, n, value)
    return q


def convert(api, q, progress=None):
    storage = (c.c_float * 24)(); work = ImportWork(); candidate = Candidate()
    cb = progress or Progress()
    assert api.af_import_cube(c.byref(q), storage, 24, c.byref(work), c.byref(candidate), cb, None) == 0
    return candidate


def test_complete_asset_wire_is_independent_of_abi_and_marks_final_gamma(api):
    asset = Asset(base=18); asset.model_sha256[:] = hashlib.sha256(b'full test model').digest(); asset.recipe = seed()
    asset.recipe.matrix[:] = range(-9, 9); asset.recipe.cc1[:] = range(-12, 12)
    asset.recipe.grid[:] = [(i*29)%128-64 for i in range(1215)]
    body = struct.pack('<129I18h24h', *asset.recipe.gamma, *asset.recipe.matrix, *asset.recipe.cc1) + bytes((v & 255) for v in asset.recipe.grid)
    header = struct.pack('<4sHH6I', b'AJR1', 1, 128, 1815, 3, 18, 1, 15, 0)
    prefix = header + bytes.fromhex('18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97') + bytes(asset.model_sha256)
    expected = prefix + hashlib.sha256(prefix + bytes(32) + body).digest() + body
    output = c.create_string_buffer(ASSET_BYTES); count = c.c_size_t(777)
    assert api.af_joint_asset_encode(c.byref(asset), output, len(output), c.byref(count)) == 0
    assert count.value == ASSET_BYTES and output.raw == expected
    restored = Asset(); assert api.af_joint_asset_decode(output, len(output), c.byref(restored)) == 0
    assert list(restored.recipe.gamma) == list(asset.recipe.gamma) and bytes(restored.recipe.grid) == bytes(asset.recipe.grid)
    for offset in (4, 12, 16, 28, 32, 64, 97, 128, ASSET_BYTES-1):
        raw = bytearray(expected); raw[offset] ^= 1
        c.memset(c.byref(restored), 0xa5, c.sizeof(restored)); before = bytes(restored)
        assert api.af_joint_asset_decode(bytes(raw), len(raw), c.byref(restored)) < 0 and bytes(restored) == before


def test_target_transaction_harness_runs_on_host_with_same_contract(api):
    assert api.af_import_target_check() == 0
    report = (c.c_uint32*8).in_dll(api, 'af_import_target_report')
    assert report[0] == 0x49323231 and report[1] > 2200 and report[2] == c.sizeof(ImportWork)
    assert report[3:] == [c.sizeof(Candidate), 1943, 5, 71, 1]


def test_joint_holdout_nonzero_percentile_and_clipping_match_scalar_math(api):
    callback = Predict(lambda ctx, recipe, rgb, out: [out.__setitem__(j, rgb[j]) for j in range(3)] and 0)
    m = model(callback); recipe = seed()
    target, storage, _ = cube(api, lambda r, g, b: (1.3*r-.15, .78*g+.08, .67*b+.17))
    points = samples([(i/23, .17+.61*(i%7)/6, .13+.71*(i%5)/4, 1 if i%3 == 0 else 2 if i%3 == 1 else 0) for i in range(24)])
    report = Report(); work = ReportWork()
    assert api.af_joint_report(c.byref(m), 0, c.byref(target), c.byref(recipe), points, len(points),
        c.byref(work), c.byref(report), Progress(), None) == 0
    def lab(v):
        v = [math.floor(max(0, min(1, x))*255+.5)/255 for x in v]
        lin = [x/12.92 if x <= .04045 else ((x+.055)/1.055)**2.4 for x in v]
        xyz = [sum(a*b for a, b in zip(row, lin))/white for row, white in zip(
            ((.4124564, .3575761, .1804375), (.2126729, .7151522, .072175), (.0193339, .119192, .9503041)), (.95047, 1, 1.08883))]
        f = [math.cbrt(x) if x > (6/29)**3 else x/(3*(6/29)**2)+4/29 for x in xyz]
        return 116*f[1]-16, 500*(f[0]-f[1]), 200*(f[1]-f[2])
    errors, clipped = [], 0
    for p in points:
        r, g, b = p.rgb; wanted = (1.3*r-.15, .78*g+.08, .67*b+.17)
        errors.append(math.dist(lab(wanted), lab(p.rgb)))
        clipped += any(x < 0 or x > 1 for x in wanted)
    expected = [sum(errors)/24, sorted(errors)[math.ceil(.95*24)-1], max(errors),
                sum(errors[::3])/8, sum(errors[1::3])/8]
    assert 0 < expected[0] < expected[2] and expected[1] < expected[2]
    assert list(report.delta_e76) == pytest.approx(expected, abs=.00015)
    assert report.clipped == clipped and report.gray_samples == report.skin_samples == 8


def test_candidate_has_full_components_holdout_report_and_no_storage_side_effect(api):
    q = request(api); events = []
    callback = Progress(lambda ctx, done, total: events.append((done, total)) or 0)
    result = convert(api, q, callback)
    assert result.fit.attempted_components == 15 and all(result.fit.accepted)
    assert result.fit.final_mse < result.fit.initial_mse and result.report.samples == 4
    assert result.validation.gray_samples == 2 and result.validation.skin_samples == 1
    assert result.report.scope == 1 and result.report.delta_e[2] < 300  # 合成模型，不是实拍精度。
    assert bytes(result.initial.lut_sha256) == hashlib.sha256(c.string_at(q.source, q.source_bytes)).digest()
    assert bytes(result.initial.payload_sha256) == hashlib.sha256(bytes(result.image)).digest()
    assert events[0] == (0, 71) and events[-1] == (71, 71) and all(a[0] <= b[0] for a, b in zip(events, events[1:]))
    d = Document(); assert api.af_import_document(c.byref(result), c.byref(d)) == 0
    assert d.schema == SCHEMA and d.converter == 1 and d.image_bytes == ASSET_BYTES
    assert api.af_document_report_applies(c.byref(d), c.byref(d.initial)) == 1
    # 由真实C后端输出，与独立标量sRGB/D65实现比较，训练色不参加这里的期望计算。
    def lab(rgb):
        linear = [(x/12.92 if x <= .04045 else ((x+.055)/1.055)**2.4) for x in [math.floor(max(0, min(1, v))*255+.5)/255 for v in rgb]]
        xyz = [sum(a*b for a, b in zip(row, linear))/white for row, white in zip(
            ((.4124564, .3575761, .1804375), (.2126729, .7151522, .072175), (.0193339, .119192, .9503041)), (.95047, 1, 1.08883))]
        f = [math.cbrt(x) if x > (6/29)**3 else x/(3*(6/29)**2)+4/29 for x in xyz]
        return 116*f[1]-16, 500*(f[0]-f[1]), 200*(f[1]-f[2])
    asset = Asset(); assert api.af_joint_asset_decode(result.image, ASSET_BYTES, c.byref(asset)) == 0
    target, storage, _ = cube(api, lambda r, g, b: (r*1.015625+(g-r)/64, g*1.015625+(b-g)/64, b*1.015625+r*b/64))
    errors = []
    for sample in q._validation:
        predicted = (c.c_float*3)(); wanted = (c.c_float*3)()
        api.af_joint_synthetic_predict(None, c.byref(asset.recipe), sample.rgb, predicted)
        api.af_cube_eval(c.byref(target), sample.rgb, wanted)
        errors.append(math.dist(lab(predicted), lab(wanted)))
    expected = [sum(errors)/4, max(errors), max(errors), sum(errors[:2])/2, errors[2]]
    assert list(result.validation.delta_e76) == pytest.approx(expected, abs=.00015)


@pytest.mark.parametrize('case', ['cancel_fit', 'cancel_report', 'cancel_package', 'model_error', 'overlap_samples', 'grid_only', 'bad_cube', 'short_budget'])
def test_import_failure_never_publishes_candidate(api, case):
    q = request(api); candidate = Candidate.from_buffer_copy(b'\xa5'*c.sizeof(Candidate)); before = bytes(candidate)
    work = ImportWork(); storage = (c.c_float*24)(); calls = []
    if case == 'overlap_samples':
        q._validation[0].rgb[:] = q._training[0].rgb
    elif case == 'grid_only': q._model.components = 8
    elif case == 'short_budget': q.options.evaluations = 8
    elif case == 'bad_cube':
        q._source[0] = b'!'
    elif case == 'model_error':
        def fail(ctx, recipe, rgb, out):
            calls.append(1)
            if len(calls) > 100: return -6
            return api.af_joint_synthetic_predict(ctx, recipe, rgb, out)
        q._callback = Predict(fail); q._model.predict = q._callback
    cutoff = {'cancel_fit': 4, 'cancel_report': 68, 'cancel_package': 71}.get(case, -1)
    cb = Progress(lambda ctx, done, total: done == cutoff)
    status = api.af_import_cube(c.byref(q), storage, 24, c.byref(work), c.byref(candidate), cb, None)
    assert status == (-20 if case.startswith('cancel_') else -22 if case == 'model_error' else -1)
    assert bytes(candidate) == before


def local(api, directory, slot=20):
    s = LocalStore(api, directory, slot)
    # 旧测试适配器默认schema=7；本例明确使用仅研究的完整联合格式。
    assert api.af_store_init(s.native, slot, SCHEMA, 262463) == 0
    return s


def test_import_edit_rename_save_export_save_as_clear_and_reboot_form_one_transaction_chain(api, tmp_path):
    q = request(api); candidate = convert(api, q); d = Document()
    assert api.af_import_document(c.byref(candidate), c.byref(d)) == 0
    catalog = alloc(api.af_catalog_bytes()); api.af_catalog_init(catalog)
    s, other = local(api, tmp_path), local(api, tmp_path, 7)
    args = [catalog, s.native, c.byref(s.io), c.byref(s.buffers)]
    assert api.af_persist_load(*args, 1) == 1
    assert api.af_persist_load(catalog, other.native, c.byref(other.io), c.byref(other.buffers), 1) == 1
    assert api.af_persist_replace(*args, c.byref(d), 0) == 0
    for parameter, value in enumerate([-9, 9, -8, 7, 6, 5, 4, 3]):
        current = c.c_int()
        assert api.af_ui_assign(catalog, 0x15e6, parameter, value, c.byref(current)) == 0
    assert api.af_persist_rename(*args, '新名称'.encode(), len('新名称'.encode())) == 0
    working, saved = Preset(), Preset()
    assert api.af_read(catalog, 20, 0, c.byref(working)) == 0 and list(working.params) == [-9, 9, -8, 7, 6, 5, 4, 3]
    assert api.af_dirty(catalog, 20) == 1
    assert api.af_read(catalog, 20, 1, c.byref(saved)) == 0 and bytes(saved) == bytes(d.initial)
    for choose_work in (0, 1):
        raw = c.create_string_buffer(8192); count = c.c_size_t()
        assert api.af_persist_export(*args, choose_work, raw, len(raw), c.byref(count)) == 0
        decoded = Document(); assert api.af_document_decode(raw, count.value, SCHEMA, c.byref(decoded)) == 0
        assert c.string_at(decoded.name, decoded.name_bytes) == '新名称'.encode()
        assert bytes(decoded.saved) == bytes(working if choose_work else saved)
        assert api.af_document_report_applies(c.byref(decoded), c.byref(decoded.saved)) == (not choose_work)
    assert api.af_persist_save(*args) == 0 and api.af_dirty(catalog, 20) == 0
    assert api.af_persist_copy(catalog, s.native, other.native, c.byref(s.io), c.byref(other.io), c.byref(s.buffers), b'copy', 4, 0) == 0
    assert api.af_persist_clear(*args) == 0
    s.close(); other.close()
    # 输入CUBE和源候选全部擦除，重启仅依赖本地记录中的完整副本。
    c.memset(q.source, 0, q.source_bytes); c.memset(c.byref(candidate), 0, c.sizeof(candidate))
    reboot = alloc(api.af_catalog_bytes()); api.af_catalog_init(reboot)
    s, other = local(api, tmp_path), local(api, tmp_path, 7)
    assert api.af_persist_load(reboot, s.native, c.byref(s.io), c.byref(s.buffers), 0) == 0
    assert api.af_read(reboot, 20, 0, c.byref(working)) == -2
    assert api.af_persist_load(reboot, other.native, c.byref(other.io), c.byref(other.buffers), 0) == 0
    assert api.af_read(reboot, 7, 0, c.byref(working)) == 0 and working.params[0] == -9
    status, recovered = other.recover()
    restored = Asset()
    assert status == 0 and api.af_import_asset(c.byref(recovered), c.byref(restored)) == 0
    assert restored.recipe.gamma[128] == 133120 and restored.recipe.matrix[0] == restored.recipe.cc1[0] == 16 and restored.recipe.grid[0] == 4
    assert api.af_restore(reboot, 7, 1) == 0 and api.af_read(reboot, 7, 0, c.byref(working)) == 0 and bytes(working) == bytes(d.initial)
    s.close(); other.close()


@pytest.mark.parametrize('failure', ['payload', 'model', 'future', 'overlap'])
def test_restored_asset_and_export_aliases_are_checked_before_publication(api, tmp_path, failure):
    candidate = convert(api, request(api)); d = Document(); assert api.af_import_document(c.byref(candidate), c.byref(d)) == 0
    asset = Asset.from_buffer_copy(b'\xa5'*c.sizeof(Asset)); before = bytes(asset)
    if failure == 'payload': candidate.image[-1] ^= 1
    elif failure == 'model': d.report.model_sha256[0] ^= 1
    elif failure == 'future': d.converter += 1
    target = c.cast(d.image, c.POINTER(Asset)) if failure == 'overlap' else c.byref(asset)
    snapshot = bytes(candidate)
    assert api.af_import_asset(c.byref(d), target) < 0 and bytes(asset) == before and bytes(candidate) == snapshot
    s = local(api, tmp_path); catalog = alloc(api.af_catalog_bytes()); api.af_catalog_init(catalog)
    args = [catalog, s.native, c.byref(s.io), c.byref(s.buffers)]
    assert api.af_persist_load(*args, 1) == 1 and api.af_persist_replace(*args, c.byref(document()), 0) == 0
    size = c.c_size_t(999); raw_before = [b.raw for b in s.raw]
    assert api.af_persist_export(*args, 0, s.buffers.a, s.buffers.capacity, c.byref(size)) == -1
    assert size.value == 999 and [b.raw for b in s.raw] == raw_before
    assert api.af_persist_rename(*args, s.buffers.a, 7) == -1
    s.close()


@pytest.mark.parametrize('bad', ['missing', 'range'])
def test_import_extension_metadata_rejected_before_cpu_creation(monkeypatch, bad):
    from a7filters.native_joint import JointMachine
    import elftools.elf.elffile
    import unicorn
    names = ('af_joint_gamma_record', 'af_joint_expand_matrix', 'af_joint_target_check',
             'af_joint_target_report', 'af_joint_target_metrics', 'af_import_target_check',
             'af_import_target_report', 'af_import_target_metrics')
    class Symbol(dict):
        def __init__(self, name, i):
            super().__init__(st_value=0x90000000 if bad == 'range' and i == 5 else 0x9080000+i*4, st_shndx=1); self.name = name
    class Table:
        def iter_symbols(self): return [Symbol(name, i) for i, name in enumerate(names) if bad != 'missing' or i != 7]
    class Elf(dict):
        little_endian = True
        def __init__(self): super().__init__(e_machine='EM_AARCH64', e_type='ET_EXEC')
        def iter_sections(self): return []
        def get_section_by_name(self, name): return Table()
    monkeypatch.setattr(elftools.elf.elffile, 'ELFFile', lambda *args: Elf())
    def forbidden(*args): pytest.fail('导入扩展元数据不合法时创建了CPU')
    monkeypatch.setattr(unicorn, 'Uc', forbidden)
    with pytest.raises(ValueError, match='导入扩展|限定入口'): JointMachine(b'metadata fixture')


def test_rename_publish_uncertainty_and_export_capacity_preserve_state(api, tmp_path):
    s = local(api, tmp_path); catalog = alloc(api.af_catalog_bytes()); api.af_catalog_init(catalog)
    args = [catalog, s.native, c.byref(s.io), c.byref(s.buffers)]
    assert api.af_persist_load(*args, 1) == 1
    d = document('manual')
    assert api.af_persist_replace(*args, c.byref(d), 0) == 0
    raw = c.create_string_buffer(b'keep', 4); count = c.c_size_t(777)
    assert api.af_persist_export(*args, 0, raw, 4, c.byref(count)) == -9
    assert raw.raw == b'keep' and count.value == 777
    original = Io.from_buffer_copy(s.io)
    callback = Phase(lambda *_: -1); s.io.sync_directory = callback
    assert api.af_persist_rename(*args, b'new', 3) == -7
    assert api.af_persist_rename(*args, b'no retry', 8) == -7
    assert api.af_persist_save(*args) == -7
    c.memmove(c.byref(s.io), c.byref(original), c.sizeof(Io))
    assert api.af_persist_load(*args, 0) == 0
    assert api.af_persist_rename(*args, b'recovered', 9) == 0
    s.close()
