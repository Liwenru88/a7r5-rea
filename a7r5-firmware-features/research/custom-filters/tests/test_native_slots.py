"""编译真实C核心验证编辑契约；不模拟AP已挂钩或CP已应用。"""
import ctypes as c
from pathlib import Path
import shutil
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'native'


class Preset(c.Structure):
    _fields_ = [('base', c.c_uint8), ('kind', c.c_uint8),
                ('params', c.c_int8 * 8), ('payload_sha256', c.c_uint8 * 32),
                ('lut_sha256', c.c_uint8 * 32)]


class Save(c.Structure):
    _fields_ = [('snapshot', Preset), ('expected_revision', c.c_uint64),
                ('request', c.c_uint64), ('slot', c.c_uint32)]


@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    compiler = shutil.which('clang') or shutil.which('cc')
    assert compiler, '需要本机C编译器，不能用Python假实现替代'
    output = tmp_path_factory.mktemp('af-native') / 'af_slots.so'
    subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    '-fPIC', '-shared', str(NATIVE/'af_slots.c'), '-o', str(output)],
                   check=True, capture_output=True, text=True)
    api = c.CDLL(str(output))
    api.af_catalog_bytes.restype = c.c_size_t
    api.af_catalog_init.argtypes = [c.c_void_p]
    api.af_install.argtypes = [c.c_void_p, c.c_uint32, c.POINTER(Preset), c.c_int]
    api.af_read.argtypes = [c.c_void_p, c.c_uint32, c.c_int, c.POINTER(Preset)]
    api.af_edit.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32, c.c_int]
    api.af_edit_base.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32]
    api.af_catalog_load.argtypes = [c.c_void_p, c.c_uint32, c.POINTER(Preset),c.POINTER(Preset),c.c_uint64]
    api.af_dirty.argtypes = [c.c_void_p, c.c_uint32]
    api.af_restore.argtypes = [c.c_void_p, c.c_uint32, c.c_int]
    api.af_begin_save.argtypes = [c.c_void_p, c.c_uint32, c.POINTER(Save)]
    api.af_finish_save.argtypes = [c.c_void_p, c.POINTER(Save), c.c_int]
    api.af_builtin_selector.argtypes = [c.c_uint32]
    return api


def catalog(lib):
    # 使用uint64数组保证C结构所需的对齐。
    raw = (c.c_uint64 * ((lib.af_catalog_bytes()+7)//8))()
    lib.af_catalog_init(raw)
    return raw


def preset(base=0):
    p = Preset(base=base, kind=0)
    p.params[:] = [0, 0, 0, 0, 0, 0, 3, 0]
    return p


def read(lib, ctx, slot, saved=0):
    p = Preset()
    assert lib.af_read(ctx, slot, saved, c.byref(p)) == 0
    return p


def test_capacity_builtin_order_and_independent_slots(lib):
    ctx = catalog(lib)
    assert [lib.af_builtin_selector(i) for i in range(12)] == [0,1,2,3,4,5,17,18,6,7,8,9]
    assert lib.af_builtin_selector(12) == -1
    p = preset(17)
    for slot in range(1, 21):
        assert lib.af_install(ctx, slot, c.byref(p), 0) == 0
    for slot in (0, 21, 0xffffffff):
        assert lib.af_install(ctx, slot, c.byref(p), 1) < 0
    assert lib.af_edit(ctx, 3, 0, 7) == 0
    assert read(lib, ctx, 3).params[0] == 7
    assert read(lib, ctx, 8).params[0] == 0
    assert read(lib, ctx, 3, 1).params[0] == 0
    assert lib.af_install(ctx, 3, c.byref(p), 0) < 0


def test_saved_snapshot_completion_does_not_clear_newer_edit(lib):
    ctx = catalog(lib)
    p = preset()
    assert lib.af_install(ctx, 1, c.byref(p), 0) == 0
    assert lib.af_edit(ctx, 1, 0, 2) == 0
    first = Save()
    assert lib.af_begin_save(ctx, 1, c.byref(first)) == 0
    assert lib.af_edit(ctx, 1, 0, 5) == 0
    assert lib.af_begin_save(ctx, 1, c.byref(Save())) < 0
    assert lib.af_finish_save(ctx, c.byref(first), 1) == 0
    assert read(lib, ctx, 1, 1).params[0] == 2
    assert read(lib, ctx, 1).params[0] == 5
    assert lib.af_dirty(ctx, 1) == 1
    assert lib.af_finish_save(ctx, c.byref(first), 1) < 0
    second = Save()
    assert lib.af_begin_save(ctx, 1, c.byref(second)) == 0
    assert lib.af_finish_save(ctx, c.byref(second), 0) < 0
    assert read(lib, ctx, 1, 1).params[0] == 2
    assert lib.af_dirty(ctx, 1) == 1
    third = Save()
    assert lib.af_begin_save(ctx, 1, c.byref(third)) == 0
    assert lib.af_finish_save(ctx, c.byref(second), 1) < 0
    assert lib.af_finish_save(ctx, c.byref(third), 1) == 0
    assert lib.af_dirty(ctx, 1) == 0


@pytest.mark.parametrize('param,low,high', [(0,-9,9),(1,-9,9),(2,-9,9),(3,0,9),
                                           (4,-9,9),(5,0,9),(6,1,5),(7,0,9)])
def test_native_ranges_and_restore(lib, param, low, high):
    ctx = catalog(lib)
    p = preset(18)
    assert lib.af_install(ctx, 20, c.byref(p), 0) == 0
    for value in (low, high):
        assert lib.af_edit(ctx, 20, param, value) == 0
        assert read(lib, ctx, 20).params[param] == value
    for value in (low-1, high+1, 256):
        assert lib.af_edit(ctx, 20, param, value) < 0
        assert read(lib, ctx, 20).params[param] == high
    assert lib.af_restore(ctx, 20, 0) == 0
    assert list(read(lib, ctx, 20).params) == list(p.params)
    assert lib.af_dirty(ctx, 20) == 0


def test_invalid_preset_cannot_replace_installed_slot(lib):
    ctx = catalog(lib)
    original = preset()
    assert lib.af_install(ctx, 1, c.byref(original), 0) == 0
    for bad in (preset(16), preset(19), preset(255)):
        assert lib.af_install(ctx, 1, c.byref(bad), 1) < 0
    bad = preset()
    bad.kind = 1
    assert lib.af_install(ctx, 1, c.byref(bad), 1) < 0
    assert read(lib, ctx, 1).base == 0
    assert lib.af_dirty(ctx, 1) == 0


def test_lut_reset_keeps_payload_and_copy_is_independent(lib):
    ctx = catalog(lib)
    p = preset(18)
    p.kind = 1
    p.payload_sha256[:] = [0xab] * 32
    p.lut_sha256[:] = [0x12] * 32
    assert lib.af_install(ctx, 6, c.byref(p), 0) == 0
    assert lib.af_edit(ctx, 6, 0, 4) == 0
    pending = Save()
    assert lib.af_begin_save(ctx, 6, c.byref(pending)) == 0
    assert lib.af_install(ctx, 6, c.byref(p), 1) < 0
    assert lib.af_finish_save(ctx, c.byref(pending), 1) == 0
    assert lib.af_restore(ctx, 6, 1) == 0
    reset = read(lib, ctx, 6)
    assert reset.base == 18 and reset.kind == 1
    assert reset.params[0] == 0 and read(lib, ctx, 6, 1).params[0] == 4
    assert bytes(reset.payload_sha256) == b'\xab' * 32
    assert bytes(reset.lut_sha256) == b'\x12' * 32
    assert lib.af_dirty(ctx, 6) == 1
    # af_install仅模拟持久化后的内存安装，不声明实际另存界面已实现。
    assert lib.af_install(ctx, 7, c.byref(reset), 0) == 0
    assert lib.af_edit(ctx, 7, 1, -3) == 0
    assert read(lib, ctx, 6).params[1] == 0
    assert lib.af_install(ctx, 7, c.byref(p), 2) < 0
    assert read(lib, ctx, 7).params[1] == -3


def test_base_working_edit_keeps_parameters_and_save_snapshot_then_recovers(lib):
    ctx=catalog(lib);initial=preset();initial.params[:]=[-3,4,-5,2,6,7,3,8]
    assert lib.af_install(ctx,7,c.byref(initial),0)==0
    assert lib.af_edit_base(ctx,7,17)==0
    work=read(lib,ctx,7);assert work.base==17 and list(work.params)==list(initial.params)
    assert read(lib,ctx,7,1).base==0 and lib.af_dirty(ctx,7)==1
    pending=Save();assert lib.af_begin_save(ctx,7,c.byref(pending))==0
    assert pending.snapshot.base==17
    assert lib.af_edit_base(ctx,7,18)==0
    assert lib.af_finish_save(ctx,c.byref(pending),1)==0
    saved=read(lib,ctx,7,1);assert saved.base==17 and read(lib,ctx,7).base==18
    assert lib.af_dirty(ctx,7)==1
    reboot=catalog(lib)
    assert lib.af_catalog_load(reboot,7,c.byref(initial),c.byref(saved),3)==0
    assert read(lib,reboot,7).base==17 and lib.af_dirty(reboot,7)==0
    assert lib.af_restore(reboot,7,1)==0 and read(lib,reboot,7).base==0
    assert list(read(lib,reboot,7).params)==list(initial.params)
    assert lib.af_restore(reboot,7,0)==0 and read(lib,reboot,7).base==17


def test_invalid_or_lut_base_edit_is_rejected_without_partial_change(lib):
    ctx=catalog(lib);p=preset(17)
    assert lib.af_edit_base(ctx,7,18)==-2
    p.kind=1;p.payload_sha256[:]=[0xab]*32;p.lut_sha256[:]=[0xcd]*32
    assert lib.af_install(ctx,7,c.byref(p),0)==0
    before=bytes(ctx)
    for slot,base in ((0,0),(21,0),(7,16),(7,19),(7,18),(7,17)):
        assert lib.af_edit_base(ctx,slot,base)==-1
        assert bytes(ctx)==before
    changed=Preset.from_buffer_copy(p);changed.base=18
    assert lib.af_catalog_load(catalog(lib),7,c.byref(p),c.byref(changed),1)==-1
