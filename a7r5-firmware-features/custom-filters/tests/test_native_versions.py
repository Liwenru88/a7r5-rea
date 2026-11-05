"""原生不可变版本与独立引用令牌；回执仅来自测试，不是假冒CP确认。"""
import ctypes as c
from pathlib import Path
import subprocess

import pytest

from test_native_persistence import Document, document, alloc

NATIVE = Path(__file__).resolve().parents[1] / 'native'


class Token(c.Structure):
    _fields_ = [('version', c.c_uint64), ('bank', c.c_uint32)]


class Lease(c.Structure):
    _fields_ = [('version', c.c_uint64), ('lease', c.c_uint64), ('bank', c.c_uint32)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output = tmp_path_factory.mktemp('af-versions') / 'versions.so'
    result = subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                             '-fPIC', '-shared', *[str(NATIVE / n) for n in
                             ('af_slots.c', 'af_sha256.c', 'af_document.c', 'af_versions.c')],
                             '-o', str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lib = c.CDLL(str(output))
    lib.af_versions_bytes.restype = c.c_size_t
    lib.af_versions_init.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p,
                                      c.c_size_t, c.c_uint32]
    lib.af_versions_stage.argtypes = [c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(Token)]
    lib.af_versions_finish.argtypes = [c.c_void_p, c.POINTER(Token), c.c_int]
    lib.af_versions_acquire.argtypes = [c.c_void_p, c.POINTER(Lease)]
    lib.af_versions_view.argtypes = [c.c_void_p, c.POINTER(Lease), c.POINTER(c.c_void_p),
                                      c.POINTER(c.c_size_t)]
    lib.af_versions_release.argtypes = [c.c_void_p, c.POINTER(Lease)]
    lib.af_document_encode.argtypes = [c.POINTER(Document), c.c_uint32, c.c_void_p,
                                       c.c_size_t, c.POINTER(c.c_size_t)]
    return lib


def context(api):
    ctx = alloc(api.af_versions_bytes())
    ctx._banks = [c.create_string_buffer(4096) for _ in range(3)]
    assert api.af_versions_init(ctx, *[c.addressof(b) for b in ctx._banks], 4096, 7) == 0
    return ctx


def raw(api, name):
    d = document(name)
    output, size = c.create_string_buffer(4096), c.c_size_t()
    assert api.af_document_encode(c.byref(d), 7, output, 4096, c.byref(size)) == 0
    return output.raw[:size.value]


def stage(api, ctx, name):
    t, data = Token(), raw(api, name)
    assert api.af_versions_stage(ctx, data, len(data), c.byref(t)) == 0
    return t


def acquire(api, ctx):
    ref = Lease()
    assert api.af_versions_acquire(ctx, c.byref(ref)) == 0
    return ref


def view(api, ctx, ref):
    p, size = c.c_void_p(), c.c_size_t()
    assert api.af_versions_view(ctx, c.byref(ref), c.byref(p), c.byref(size)) == 0
    return c.string_at(p, size.value)


def test_failed_application_stale_ack_and_busy_banks_preserve_pinned_frames(api):
    ctx = context(api)
    assert api.af_versions_acquire(ctx, c.byref(Lease())) == -2
    first = stage(api, ctx, 'first')
    assert api.af_versions_finish(ctx, c.byref(first), 1) == 0
    old = acquire(api, ctx)
    pinned = view(api, ctx, old)
    failed = stage(api, ctx, 'failed')
    assert api.af_versions_finish(ctx, c.byref(failed), 0) == -6
    current = acquire(api, ctx)
    assert current.version == old.version
    assert api.af_versions_release(ctx, c.byref(current)) == 0
    second = stage(api, ctx, 'second')
    assert api.af_versions_finish(ctx, c.byref(first), 1) == -5
    assert api.af_versions_finish(ctx, c.byref(second), 1) == 0
    mid = acquire(api, ctx)
    third = stage(api, ctx, 'third')
    assert api.af_versions_finish(ctx, c.byref(third), 1) == 0
    data, rejected = raw(api, 'fourth'), Token()
    assert api.af_versions_stage(ctx, data, len(data), c.byref(rejected)) == -4
    assert view(api, ctx, old) == pinned
    assert api.af_versions_release(ctx, c.byref(old)) == 0
    assert api.af_versions_release(ctx, c.byref(old)) == -5
    fourth = stage(api, ctx, 'fourth')
    assert fourth.bank == first.bank and fourth.version != first.version
    assert api.af_versions_view(ctx, c.byref(old), c.byref(c.c_void_p()),
                                 c.byref(c.c_size_t())) == -5
    assert api.af_versions_finish(ctx, c.byref(fourth), 1) == 0
    assert api.af_versions_release(ctx, c.byref(mid)) == 0


def test_pending_is_unique_and_invalid_data_or_duplicate_release_never_publishes(api):
    ctx = context(api)
    t = Token()
    assert api.af_versions_stage(ctx, b'bad', 3, c.byref(t)) == -1
    first = stage(api, ctx, 'first')
    good = raw(api, 'another')
    assert api.af_versions_stage(ctx, good, len(good), c.byref(t)) == -4
    assert api.af_versions_finish(ctx, c.byref(first), 2) == -1
    assert api.af_versions_finish(ctx, c.byref(first), 1) == 0
    refs = [acquire(api, ctx) for _ in range(64)]
    assert len({r.lease for r in refs}) == 64
    assert api.af_versions_acquire(ctx, c.byref(Lease())) == -4
    forged = Lease(refs[0].version, refs[0].lease, (refs[0].bank + 1) % 3)
    assert api.af_versions_release(ctx, c.byref(forged)) == -5
    for r in refs:
        assert api.af_versions_release(ctx, c.byref(r)) == 0
    assert api.af_versions_release(ctx, c.byref(refs[-1])) == -5
