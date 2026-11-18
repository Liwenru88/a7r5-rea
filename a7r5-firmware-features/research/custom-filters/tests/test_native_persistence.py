"""真实C载荷/保存事务与普通临时目录联验；不使用相机或SD。"""
import ctypes as c
import hashlib
import os
from pathlib import Path
import struct
import subprocess

import pytest

from test_native_slots import Preset, preset

NATIVE = Path(__file__).resolve().parents[1] / 'native'
Read = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint32, c.c_uint32,
                  c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t))
Write = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint32, c.c_uint32,
                   c.c_void_p, c.c_size_t)
Phase = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint32, c.c_uint32)


class Report(c.Structure):
    _fields_ = [('samples', c.c_uint32), ('clipped', c.c_uint32),
                ('delta_e', c.c_uint32 * 5), ('scope', c.c_uint32),
                ('model_sha256', c.c_uint8 * 32)]


class Document(c.Structure):
    _fields_ = [('present', c.c_uint32), ('initial', Preset), ('saved', Preset),
                ('schema', c.c_uint32), ('converter', c.c_uint32),
                ('name', c.c_void_p), ('name_bytes', c.c_size_t),
                ('image', c.c_void_p), ('image_bytes', c.c_size_t), ('report', Report)]


class Io(c.Structure):
    _fields_ = [('context', c.c_void_p), ('read', Read), ('stage', Write),
                ('sync_data', Phase), ('publish', Phase), ('sync_directory', Phase),
                ('discard', Phase)]


class Buffers(c.Structure):
    _fields_ = [('a', c.c_void_p), ('b', c.c_void_p), ('next', c.c_void_p),
                ('capacity', c.c_size_t)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output = tmp_path_factory.mktemp('af-persist-build') / 'persist.so'
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    '-fPIC', '-shared', *[str(NATIVE / n) for n in
                    ('af_slots.c', 'af_record.c', 'af_sha256.c', 'af_document.c',
                     'af_store.c', 'af_posix.c', 'af_persist.c', 'af_ui.c',
                     'af_labels.c', 'af_labels_store.c')], '-o', str(output)],
                   check=True, capture_output=True, text=True)
    lib = c.CDLL(str(output))
    lib.af_sha256.argtypes = [c.c_void_p, c.c_size_t, c.c_void_p]
    lib.af_document_encode.argtypes = [c.POINTER(Document), c.c_uint32,
                                       c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    lib.af_document_decode.argtypes = [c.c_void_p, c.c_size_t, c.c_uint32,
                                       c.POINTER(Document)]
    lib.af_document_report_applies.argtypes = [c.POINTER(Document), c.POINTER(Preset)]
    for name in ('af_store_bytes', 'af_posix_bytes', 'af_catalog_bytes'):
        getattr(lib, name).restype = c.c_size_t
    lib.af_store_init.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32, c.c_size_t]
    lib.af_store_recover.argtypes = [c.c_void_p, c.POINTER(Io), c.POINTER(Buffers),
                                     c.c_int, c.POINTER(Document)]
    lib.af_store_commit.argtypes = [c.c_void_p, c.POINTER(Io), c.POINTER(Buffers),
                                    c.POINTER(Document)]
    lib.af_store_generation.argtypes = [c.c_void_p]
    lib.af_store_generation.restype = c.c_uint64
    lib.af_posix_init.argtypes = [c.c_void_p, c.c_int, c.POINTER(Io)]
    lib.af_posix_close.argtypes = [c.c_void_p]
    lib.af_catalog_init.argtypes = [c.c_void_p]
    lib.af_catalog_load.argtypes = [c.c_void_p, c.c_uint32, c.POINTER(Preset),
                                    c.POINTER(Preset), c.c_uint64]
    lib.af_read.argtypes = [c.c_void_p, c.c_uint32, c.c_int, c.POINTER(Preset)]
    lib.af_edit.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32, c.c_int]
    lib.af_edit_base.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32]
    lib.af_dirty.argtypes = [c.c_void_p, c.c_uint32]
    lib.af_restore.argtypes = [c.c_void_p, c.c_uint32, c.c_int]
    lib.af_ui_assign.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32, c.c_int, c.POINTER(c.c_int)]
    base_args = [c.c_void_p, c.c_void_p, c.POINTER(Io), c.POINTER(Buffers)]
    lib.af_persist_load.argtypes = base_args + [c.c_int]
    lib.af_persist_replace.argtypes = base_args + [c.POINTER(Document), c.c_int]
    lib.af_persist_save.argtypes = base_args
    lib.af_persist_clear.argtypes = base_args
    lib.af_persist_copy.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p,
                                    c.POINTER(Io), c.POINTER(Io), c.POINTER(Buffers),
                                    c.c_void_p, c.c_size_t, c.c_int]
    lib.af_persist_rename.argtypes = base_args + [c.c_void_p, c.c_size_t]
    lib.af_labels_init.argtypes = [c.c_void_p]
    lib.af_labels_read.argtypes = [c.c_void_p, c.c_uint32, c.c_void_p, c.c_void_p]
    lib.af_labels_from_store.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.POINTER(Buffers), c.c_int]
    return lib


def document(name='自定义 C20', base=18, image=None):
    d = Document(present=1, initial=preset(base), saved=preset(base))
    d._name = c.create_string_buffer(name.encode())
    d.name, d.name_bytes = c.addressof(d._name), len(name.encode())
    if image is not None:
        d._image = c.create_string_buffer(image)
        d.image, d.image_bytes = c.addressof(d._image), len(image)
        d.schema, d.converter = 7, 2  # 仅测试格式，不是已批准的ISP schema。
        d.report.samples, d.report.scope = 100, 1
        d.report.delta_e[:] = [100, 300, 400, 200, 250]
        d.report.model_sha256[:] = hashlib.sha256(b'test model').digest()
        for p in (d.initial, d.saved):
            p.kind = 1
            p.payload_sha256[:] = hashlib.sha256(image).digest()
            p.lut_sha256[:] = hashlib.sha256(b'source cube').digest()
    return d


def encode(api, d, schema=7):
    raw, count = c.create_string_buffer(270000), c.c_size_t(0)
    assert api.af_document_encode(c.byref(d), schema, raw, len(raw), c.byref(count)) == 0
    return raw.raw[:count.value]


def test_sha_and_full_document_match_independent_wire(api):
    for raw in (b'', b'abc', b'\x00' * 64, bytes(range(256)) * 4097):
        digest = (c.c_uint8 * 32)()
        assert api.af_sha256(raw, len(raw), digest) == 0
        assert bytes(digest) == hashlib.sha256(raw).digest()
    d = document(image=bytes(range(256)) * 1024)
    d.saved.params[1] = 7
    raw = encode(api, d)
    header = bytearray(256)
    struct.pack_into('<4sHH12I', header, 0, b'AFD1', 1, 256,
                     7, 2, d.name_bytes, d.image_bytes, 100, 0,
                     100, 300, 400, 200, 250, 1)
    header[56:88] = bytes(d.report.model_sha256)
    header[88:162], header[162:236] = bytes(d.initial), bytes(d.saved)
    struct.pack_into('<I', header, 236, 1)
    assert raw == bytes(header) + '自定义 C20'.encode() + bytes(range(256)) * 1024
    decoded = Document()
    assert api.af_document_decode(raw, len(raw), 7, c.byref(decoded)) == 0
    assert bytes(decoded.initial) == bytes(d.initial)
    assert bytes(decoded.saved) == bytes(d.saved)
    assert c.string_at(decoded.image, decoded.image_bytes) == d._image.raw[:-1]
    assert api.af_document_report_applies(c.byref(decoded), c.byref(decoded.initial)) == 1
    assert api.af_document_report_applies(c.byref(decoded), c.byref(decoded.saved)) == 0


@pytest.mark.parametrize('image,expected', [(None, 0), (b'bound LUT fixture', -1)])
def test_saved_base_can_change_only_for_a_pure_parameter_filter(api, image, expected):
    d = document(base=0, image=image)
    d.saved.base = 18
    d.saved.params[0] = 4
    raw = c.create_string_buffer(b'\xa5'*4096, 4096)
    count = c.c_size_t(777)
    before = raw.raw
    assert api.af_document_encode(c.byref(d), 7, raw, len(raw), c.byref(count)) == expected
    if expected:
        assert raw.raw == before and count.value == 777
    else:
        decoded = Document()
        assert api.af_document_decode(raw, count.value, 7, c.byref(decoded)) == 0
        assert decoded.initial.base == 0 and decoded.saved.base == 18
        assert decoded.initial.params[0] == 0 and decoded.saved.params[0] == 4


@pytest.mark.parametrize('mutation', ['digest', 'unknown_schema', 'future', 'params',
                                      'utf8', 'reserved', 'report', 'truncated'])
def test_bad_document_never_publishes_or_changes_output(api, mutation):
    raw = bytearray(encode(api, document(image=b'converted fixture')))
    if mutation == 'digest': raw[-1] ^= 1
    elif mutation == 'unknown_schema': struct.pack_into('<I', raw, 8, 9)
    elif mutation == 'future': raw[4] = 2
    elif mutation == 'params': raw[164] = 20
    elif mutation == 'utf8': raw[256] = 0xff
    elif mutation == 'reserved': raw[240] = 1
    elif mutation == 'report': struct.pack_into('<I', raw, 28, 101)
    elif mutation == 'truncated': raw.pop()
    out = Document()
    c.memset(c.byref(out), 0xa5, c.sizeof(out))
    before = bytes(out)
    assert api.af_document_decode(bytes(raw), len(raw), 7, c.byref(out)) < 0
    assert bytes(out) == before


def alloc(size):
    return (c.c_uint64 * ((size + 7) // 8))()


class LocalStore:
    def __init__(self, api, directory, slot=20):
        self.api, self.slot = api, slot
        self.native = alloc(api.af_store_bytes())
        self.posix = alloc(api.af_posix_bytes())
        self.raw = [c.create_string_buffer(270000) for _ in range(3)]
        self.buffers = Buffers(*[c.addressof(b) for b in self.raw], 270000)
        self.io = Io()
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            assert api.af_posix_init(self.posix, fd, c.byref(self.io)) == 0
        finally:
            os.close(fd)
        assert api.af_store_init(self.native, slot, 7, 262463) == 0

    def recover(self, create=0):
        d = Document()
        return self.api.af_store_recover(self.native, c.byref(self.io),
                                        c.byref(self.buffers), create, c.byref(d)), d

    def commit(self, d):
        return self.api.af_store_commit(self.native, c.byref(self.io),
                                       c.byref(self.buffers), c.byref(d))

    def close(self):
        assert self.api.af_posix_close(self.posix) == 0


def test_real_directory_save_reload_reset_save_as_and_tombstone(api, tmp_path):
    s = LocalStore(api, tmp_path)
    assert s.recover(create=1)[0] == 1
    first = document(image=b'complete independent image bytes')
    assert s.commit(first) == 0
    status, recovered = s.recover()
    assert status == 0
    catalog = alloc(api.af_catalog_bytes())
    api.af_catalog_init(catalog)
    assert api.af_catalog_load(catalog, 20, c.byref(recovered.initial),
                               c.byref(recovered.saved), 1) == 0
    assert api.af_edit(catalog, 20, 2, -9) == 0
    current = Preset()
    assert api.af_read(catalog, 20, 0, c.byref(current)) == 0
    recovered.saved = current
    # 恢复结果借用工作区；提交必须先编码再重新读取副本，避免别名失效。
    assert s.commit(recovered) == 0
    s.close()
    reboot = LocalStore(api, tmp_path)
    status, recovered = reboot.recover()
    assert status == 0 and recovered.saved.params[2] == -9
    assert recovered.initial.params[2] == 0
    assert c.string_at(recovered.image, recovered.image_bytes) == b'complete independent image bytes'
    other = LocalStore(api, tmp_path, slot=7)
    assert other.recover(create=1)[0] == 1
    assert other.commit(recovered) == 0
    # 清空是可恢复的墓碑，不让旧副本在重启后复活。
    assert reboot.commit(Document()) == 0
    reboot.close()
    again = LocalStore(api, tmp_path)
    status, cleared = again.recover()
    assert status == 0 and cleared.present == 0
    assert other.recover()[1].present == 1
    again.close()
    other.close()


def test_verified_document_snapshot_uses_current_readback_and_rejects_reused_buffers(api, tmp_path):
    api.af_store_snapshot.argtypes = [c.c_void_p, c.POINTER(Buffers), c.POINTER(Document)]
    s = LocalStore(api, tmp_path, slot=7)
    try:
        assert s.recover(create=1)[0] == 1
        output = Document()
        c.memset(c.byref(output), 0xa5, c.sizeof(output))
        before = bytes(output)
        assert api.af_store_snapshot(s.native, c.byref(s.buffers), c.byref(output)) == 1
        assert bytes(output) == before
        assert s.commit(document('暖色 C07', base=0)) == 0
        assert api.af_store_snapshot(s.native, c.byref(s.buffers), c.byref(output)) == 0
        assert c.string_at(output.name, output.name_bytes) == '暖色 C07'.encode()
        assert s.commit(document('新名称 C07', base=18)) == 0
        assert api.af_store_snapshot(s.native, c.byref(s.buffers), c.byref(output)) == 0
        assert output.saved.base == 18 and c.string_at(output.name, output.name_bytes) == '新名称 C07'.encode()
        before = bytes(output)
        for raw in s.raw:
            raw[0] = b'!'
        assert api.af_store_snapshot(s.native, c.byref(s.buffers), c.byref(output)) == -6
        assert bytes(output) == before
        assert s.recover()[0] == 0
        assert api.af_store_snapshot(s.native, c.byref(s.buffers), c.byref(output)) == 0
        assert c.string_at(output.name, output.name_bytes) == '新名称 C07'.encode()
    finally:
        s.close()


def label_text(api, labels, slot):
    pointer, count = c.c_void_p(), c.c_size_t()
    status = api.af_labels_read(c.byref(labels), slot, c.byref(pointer), c.byref(count))
    return status, c.string_at(pointer, count.value) if status == 0 else None


def test_base_edit_save_copy_reboot_and_committed_names_share_one_document(api, tmp_path):
    from test_native_labels import Labels
    labels = Labels();api.af_labels_init(c.byref(labels))
    catalog = alloc(api.af_catalog_bytes());api.af_catalog_init(catalog)
    s, target = LocalStore(api, tmp_path, slot=7), LocalStore(api, tmp_path, slot=20)
    args = [catalog, s.native, c.byref(s.io), c.byref(s.buffers)]
    try:
        assert api.af_persist_load(*args, 1) == 1
        assert api.af_persist_replace(*args, c.byref(document('Warm C07', base=0)), 0) == 0
        assert api.af_labels_from_store(c.byref(labels), catalog, s.native, c.byref(s.buffers), 0) == 0
        assert label_text(api, labels, 7) == (0, b'Warm C07')
        assert api.af_edit_base(catalog, 7, 17) == 0
        assert api.af_edit(catalog, 7, 0, 4) == 0
        assert api.af_persist_save(*args) == 0
        assert api.af_labels_from_store(c.byref(labels), catalog, s.native, c.byref(s.buffers), 0) == 0
        name = '暖光·城市'.encode()
        assert api.af_persist_rename(*args, name, len(name)) == 0
        assert api.af_labels_from_store(c.byref(labels), catalog, s.native, c.byref(s.buffers), 0) == 0
        assert label_text(api, labels, 7) == (0, name)
        assert api.af_persist_load(catalog, target.native, c.byref(target.io), c.byref(target.buffers), 1) == 1
        assert api.af_persist_copy(catalog, s.native, target.native, c.byref(s.io), c.byref(target.io),
                                   c.byref(s.buffers), b'Evening C20', 11, 0) == 0
        assert api.af_labels_from_store(c.byref(labels), catalog, target.native, c.byref(s.buffers), 0) == 0
        assert label_text(api, labels, 20) == (0, b'Evening C20')
        restarted = alloc(api.af_catalog_bytes());api.af_catalog_init(restarted)
        assert api.af_persist_load(restarted, s.native, c.byref(s.io), c.byref(s.buffers), 0) == 0
        current = Preset()
        assert api.af_read(restarted, 7, 0, c.byref(current)) == 0
        assert current.base == 17 and current.params[0] == 4
        assert api.af_labels_from_store(c.byref(labels), restarted, s.native, c.byref(s.buffers), 1) == 0
        assert label_text(api, labels, 7) == (0, name)
        assert api.af_persist_clear(restarted, s.native, c.byref(s.io), c.byref(s.buffers)) == 0
        assert api.af_labels_from_store(c.byref(labels), restarted, s.native, c.byref(s.buffers), 0) == 0
        assert label_text(api, labels, 7)[0] == -2 and label_text(api, labels, 20) == (0, b'Evening C20')
    finally:
        s.close();target.close()


def test_uncertain_save_cannot_publish_name_and_explicit_recovery_can_roll_back(api, tmp_path):
    from test_native_labels import Labels
    labels = Labels();api.af_labels_init(c.byref(labels))
    catalog = alloc(api.af_catalog_bytes());api.af_catalog_init(catalog)
    s = LocalStore(api, tmp_path, slot=7)
    args = [catalog, s.native, c.byref(s.io), c.byref(s.buffers)]
    try:
        assert api.af_persist_load(*args, 1) == 1
        assert api.af_persist_replace(*args, c.byref(document('old name', base=0)), 0) == 0
        assert api.af_labels_from_store(c.byref(labels), catalog, s.native, c.byref(s.buffers), 0) == 0
        original = Io.from_buffer_copy(s.io)
        @Phase
        def uncertain(ctx, slot, bank):
            assert original.publish(ctx, slot, bank) == 0
            return -1
        s.io.publish = uncertain
        assert api.af_persist_rename(*args, b'new name', 8) == -7
        before = bytes(labels)
        assert api.af_labels_from_store(c.byref(labels), catalog, s.native, c.byref(s.buffers), 0) == -7
        assert bytes(labels) == before
        c.memmove(c.byref(s.io), c.byref(original), c.sizeof(Io))
        assert api.af_persist_load(*args, 0) == 0
        assert api.af_labels_from_store(c.byref(labels), catalog, s.native, c.byref(s.buffers), 1) == 0
        assert label_text(api, labels, 7) == (0, b'new name')
        latest = tmp_path/'C07_B.rec'
        raw = latest.read_bytes();latest.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        assert api.af_persist_load(*args, 0) == 0
        assert api.af_labels_from_store(c.byref(labels), catalog, s.native, c.byref(s.buffers), 0) == -6
        assert label_text(api, labels, 7) == (0, b'new name')
        assert api.af_labels_from_store(c.byref(labels), catalog, s.native, c.byref(s.buffers), 1) == 0
        assert label_text(api, labels, 7) == (0, b'old name')
    finally:
        s.close()


@pytest.mark.parametrize('phase', ['stage', 'sync_data', 'publish',
                                  'sync_directory', 'readback'])
def test_faults_preserve_old_or_return_uncertain_and_freeze(api, tmp_path, phase):
    s = LocalStore(api, tmp_path)
    assert s.recover(create=1)[0] == 1
    assert s.commit(document('old')) == 0
    original = Io.from_buffer_copy(s.io)
    callbacks = []
    if phase == 'readback':
        count = 0

        @Read
        def failure(ctx, slot, bank, out, cap, size):
            nonlocal count
            count += 1
            return -1 if count == 3 else original.read(ctx, slot, bank, out, cap, size)
    else:
        callback_type = Write if phase == 'stage' else Phase

        @callback_type
        def failure(*args):
            # publish模拟已改名但错误回执，必须作为不确定结果处理。
            if phase in ('stage', 'publish'):
                assert getattr(original, phase)(*args) == 0
            return -1
    callbacks.append(failure)
    setattr(s.io, 'read' if phase == 'readback' else phase, failure)
    expected = -7 if phase in ('publish', 'sync_directory', 'readback') else -2
    assert s.commit(document('new')) == expected
    c.memmove(c.byref(s.io), c.byref(original), c.sizeof(Io))
    if expected == -7:
        assert s.commit(document('cannot silently retry')) == -7
    status, restored = s.recover()
    assert status == 0
    assert c.string_at(restored.name, restored.name_bytes) == (
        b'new' if expected == -7 else b'old')
    assert not list(tmp_path.glob('*.new'))
    s.close()


def test_corruption_fallback_future_refusal_stale_owner_and_symlink(api, tmp_path):
    s = LocalStore(api, tmp_path)
    assert s.recover(create=1)[0] == 1
    assert s.commit(document('old')) == 0
    stale = LocalStore(api, tmp_path)
    assert stale.recover()[0] == 0
    assert s.commit(document('new')) == 0
    assert stale.commit(document('stale')) == -6
    path = tmp_path / 'C20_B.rec'
    good = path.read_bytes()
    path.write_bytes(good[:-1] + bytes([good[-1] ^ 1]))
    assert s.recover()[0] == 0
    assert s.api.af_store_generation(s.native) == 1
    future = bytearray(good)
    future[4] = 2
    path.write_bytes(future)
    assert s.recover()[0] == -4
    assert s.commit(document('no downgrade')) < 0
    path.unlink()
    sentinel = tmp_path / 'sentinel'
    sentinel.write_bytes(b'keep')
    path.symlink_to(sentinel)
    assert s.recover()[0] == -2
    assert sentinel.read_bytes() == b'keep'
    s.close()
    stale.close()


def test_editor_to_durable_snapshot_save_as_and_reboot(api, tmp_path):
    s, target = LocalStore(api, tmp_path), LocalStore(api, tmp_path, slot=7)
    catalog = alloc(api.af_catalog_bytes())
    api.af_catalog_init(catalog)
    args = [catalog, s.native, c.byref(s.io), c.byref(s.buffers)]
    assert api.af_persist_load(*args, 1) == 1
    d = document(image=b'complete native-format fixture')
    assert api.af_persist_replace(*args, c.byref(d), 0) == 0
    assert api.af_persist_replace(*args, c.byref(d), 0) == -11
    # C20的真实通用UI分流、八项参数和保存目录共用同一C对象。
    for parameter, value in enumerate([-9, 9, -8, 7, 6, 5, 4, 3]):
        out = c.c_int()
        assert api.af_ui_assign(catalog, 0x15e6, parameter, value, c.byref(out)) == 0
        assert out.value == value
    original = Io.from_buffer_copy(s.io)

    @Write
    def edit_during_save(ctx, slot, bank, raw, size):
        assert api.af_edit(catalog, 20, 0, 8) == 0
        return original.stage(ctx, slot, bank, raw, size)

    s.io.stage = edit_during_save
    assert api.af_persist_save(*args) == 0
    saved, working = Preset(), Preset()
    assert api.af_read(catalog, 20, 1, c.byref(saved)) == 0
    assert api.af_read(catalog, 20, 0, c.byref(working)) == 0
    assert saved.params[0] == -9 and working.params[0] == 8
    assert api.af_dirty(catalog, 20) == 1
    c.memmove(c.byref(s.io), c.byref(original), c.sizeof(Io))
    assert api.af_persist_load(catalog, target.native, c.byref(target.io),
                               c.byref(target.buffers), 1) == 1
    assert api.af_persist_copy(catalog, s.native, target.native, c.byref(s.io),
                               c.byref(target.io), c.byref(s.buffers), b'copy', 4, 0) == 0
    assert api.af_edit(catalog, 7, 1, -2) == 0
    assert api.af_read(catalog, 20, 0, c.byref(working)) == 0 and working.params[1] == 9
    assert api.af_persist_clear(*args) == 0
    assert api.af_read(catalog, 20, 0, c.byref(working)) == -2
    restarted = alloc(api.af_catalog_bytes())
    api.af_catalog_init(restarted)
    assert api.af_persist_load(restarted, target.native, c.byref(target.io),
                               c.byref(target.buffers), 0) == 0
    assert api.af_read(restarted, 7, 0, c.byref(working)) == 0
    assert working.params[0] == 8 and working.params[1] == 9
    assert api.af_restore(restarted, 7, 1) == 0
    assert api.af_read(restarted, 7, 0, c.byref(working)) == 0 and working.params[0] == 0
    s.close()
    target.close()


def test_failed_editor_save_keeps_work_and_saved_version(api, tmp_path):
    s = LocalStore(api, tmp_path)
    catalog = alloc(api.af_catalog_bytes())
    api.af_catalog_init(catalog)
    args = [catalog, s.native, c.byref(s.io), c.byref(s.buffers)]
    assert api.af_persist_load(*args, 1) == 1
    d = document()
    assert api.af_persist_replace(*args, c.byref(d), 0) == 0
    assert api.af_edit(catalog, 20, 1, 7) == 0
    original = Io.from_buffer_copy(s.io)

    @Phase
    def fail_sync(*_):
        return -1

    s.io.sync_data = fail_sync
    assert api.af_persist_save(*args) == -2
    saved, current = Preset(), Preset()
    assert api.af_read(catalog, 20, 1, c.byref(saved)) == 0 and saved.params[1] == 0
    assert api.af_read(catalog, 20, 0, c.byref(current)) == 0 and current.params[1] == 7
    assert api.af_dirty(catalog, 20) == 1
    c.memmove(c.byref(s.io), c.byref(original), c.sizeof(Io))
    assert api.af_persist_save(*args) == 0
    assert api.af_dirty(catalog, 20) == 0
    s.close()


@pytest.mark.parametrize('case', ['semantic_corrupt', 'truncated', 'inner_future',
                                 'schema_future', 'both_corrupt', 'same_generation_conflict'])
def test_recovery_checks_full_payload_and_never_initializes_corrupt_slot(api, tmp_path, case):
    from test_native_record import wire
    s = LocalStore(api, tmp_path)
    assert s.recover(create=1)[0] == 1
    assert s.commit(document('old', image=b'full image')) == 0
    assert s.commit(document('new', image=b'full image')) == 0
    a, b = tmp_path / 'C20_A.rec', tmp_path / 'C20_B.rec'
    raw = bytearray(b.read_bytes())
    expected = 0
    if case == 'semantic_corrupt':
        # 外层CRC正确、内层UTF-8损坏，仍应选择完整旧副本。
        raw[32 + 256] = 0xff
        raw = bytearray(wire(bytes(raw[32:]), generation=2))
    elif case == 'truncated':
        raw = raw[:100]
    elif case == 'inner_future':
        raw[32 + 4] = 2
        raw = bytearray(wire(bytes(raw[32:]), generation=2))
        expected = -4
    elif case == 'schema_future':
        struct.pack_into('<I', raw, 32 + 8, 9)
        raw = bytearray(wire(bytes(raw[32:]), generation=2))
        expected = -4
    elif case == 'both_corrupt':
        raw = raw[:100]
        a.write_bytes(b'bad')
        expected = -3
    else:
        raw = bytearray(wire(bytes(raw[32:]), generation=1))
        expected = -5
    b.write_bytes(raw)
    assert s.recover(create=1)[0] == expected
    if expected == 0:
        assert api.af_store_generation(s.native) == 1
    else:
        assert s.commit(document('must not overwrite')) < 0
    assert b.read_bytes() == raw
    s.close()


@pytest.fixture(scope='module')
def fault_api(api, tmp_path_factory):
    build = tmp_path_factory.mktemp('af-posix-faults')
    obj, output = build / 'posix.o', build / 'faults.so'
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                             '-fPIC', '-Dwrite=af_test_write', '-Dfsync=af_test_fsync',
                             '-Dclose=af_test_close', '-c', str(NATIVE / 'af_posix.c'),
                             '-o', str(obj)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                             '-fPIC', '-shared', *[str(NATIVE / n) for n in
                             ('af_slots.c', 'af_record.c', 'af_sha256.c', 'af_document.c',
                              'af_store.c', 'af_persist.c', 'af_ui.c',
                              'af_labels.c', 'af_labels_store.c')], str(obj),
                             str(Path(__file__).with_name('posix_faults.c')),
                             '-o', str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lib = c.CDLL(str(output))
    for name in dir(api):
        if name.startswith('af_'):
            getattr(lib, name).argtypes = getattr(api, name).argtypes
            getattr(lib, name).restype = getattr(api, name).restype
    lib.af_test_fault.argtypes = [c.c_int]
    return lib


@pytest.mark.parametrize('mode', [1, 2, 3, 4], ids=['eintr-short-write', 'enospc', 'fsync', 'close'])
def test_actual_posix_syscall_failures_and_short_write_loop(fault_api, tmp_path, mode):
    api = fault_api
    api.af_test_fault(0)
    s = LocalStore(api, tmp_path)
    assert s.recover(create=1)[0] == 1
    assert s.commit(document('old')) == 0
    api.af_test_fault(mode)
    assert s.commit(document('new')) == (0 if mode == 1 else -2)
    api.af_test_fault(0)
    status, d = s.recover()
    assert status == 0
    assert c.string_at(d.name, d.name_bytes) == (b'new' if mode == 1 else b'old')
    assert not list(tmp_path.glob('*.new'))
    s.close()
