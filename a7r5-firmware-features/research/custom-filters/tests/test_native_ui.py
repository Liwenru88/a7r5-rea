"""验证菜单身份在进入原厂18项数组前分流；不模拟机身已安装。"""
import ctypes as c
from pathlib import Path
import shutil
import subprocess
import struct

import pytest

from test_native_slots import Preset, catalog, preset, read

NATIVE = Path(__file__).resolve().parents[1]/'native'


class Route(c.Structure):
    _fields_ = [('menu', c.c_uint32), ('kind', c.c_uint32), ('slot', c.c_uint32),
                ('selector', c.c_uint32), ('native_index', c.c_uint32)]


@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    compiler = shutil.which('clang') or shutil.which('cc')
    assert compiler
    output = tmp_path_factory.mktemp('af-ui')/'af_ui.so'
    subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    '-fPIC', '-shared', str(NATIVE/'af_slots.c'), str(NATIVE/'af_ui.c'),
                    '-o', str(output)], check=True, capture_output=True, text=True)
    api = c.CDLL(str(output))
    api.af_catalog_bytes.restype = c.c_size_t
    api.af_catalog_init.argtypes = [c.c_void_p]
    api.af_install.argtypes = [c.c_void_p, c.c_uint32, c.POINTER(Preset), c.c_int]
    api.af_read.argtypes = [c.c_void_p, c.c_uint32, c.c_int, c.POINTER(Preset)]
    api.af_dirty.argtypes = [c.c_void_p, c.c_uint32]
    api.af_ui_item.argtypes = [c.c_uint32, c.POINTER(Route)]
    api.af_ui_resolve.argtypes = [c.c_uint32, c.POINTER(Route)]
    api.af_ui_read.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32, c.POINTER(c.c_int)]
    api.af_ui_step.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32, c.c_uint32, c.POINTER(c.c_int)]
    api.af_ui_snapshot.argtypes = [c.c_void_p, c.c_uint32, c.c_void_p, c.c_void_p]
    api.af_ui_assign.argtypes = [c.c_void_p,c.c_uint32,c.c_uint32,c.c_int,c.POINTER(c.c_int)]
    return api


def test_fixed_identity_order_is_unique_and_users_never_have_native_array_index(lib):
    rows = []
    for index in range(33):
        row = Route()
        assert lib.af_ui_item(index, c.byref(row)) == 0
        decoded = Route()
        assert lib.af_ui_resolve(row.menu, c.byref(decoded)) == 0
        assert bytes(row) == bytes(decoded)
        rows.append(row)
    assert len({r.menu for r in rows}) == 33
    assert [r.menu for r in rows[:18]] == list(range(0x84c, 0x85e))
    assert [r.menu for r in rows[18:32]] == list(range(0x15d9, 0x15e7))
    assert [r.selector for r in rows[:12]] == [0,1,2,3,4,5,17,18,6,7,8,9]
    assert [r.native_index for r in rows[:12]] == [0,1,2,3,4,5,16,17,6,7,8,9]
    assert [r.slot for r in rows[12:32]] == list(range(1, 21))
    assert all(r.kind == 1 and r.native_index == 0xffffffff for r in rows[12:32])
    assert (rows[32].menu, rows[32].kind, rows[32].slot) == (0x85e, 2, 0)


@pytest.mark.parametrize('parameter,low,high', [(0,-9,9),(1,-9,9),(2,-9,9),(3,0,9),
                                              (4,-9,9),(5,0,9),(6,1,5),(7,0,9)])
def test_all_user_routes_edit_working_values_and_saturate_like_native_controls(lib, parameter, low, high):
    ctx = catalog(lib)
    p = preset(18)
    for slot in range(1, 21):
        assert lib.af_install(ctx, slot, c.byref(p), 0) == 0
    row = Route()
    for index in range(12, 32):
        assert lib.af_ui_item(index, c.byref(row)) == 0
        value = c.c_int(99)
        for _ in range(20):
            assert lib.af_ui_step(ctx, row.menu, parameter, 0, c.byref(value)) == 0
        assert value.value == high
        assert read(lib, ctx, row.slot).params[parameter] == high
        for _ in range(20):
            assert lib.af_ui_step(ctx, row.menu, parameter, 1, c.byref(value)) == 0
        assert value.value == low
        assert lib.af_ui_read(ctx, row.menu, parameter, c.byref(value)) == 0
        assert value.value == low
        assert read(lib, ctx, row.slot, 1).params[parameter] == p.params[parameter]
        for other in range(8):
            if other != parameter:
                assert read(lib, ctx, row.slot).params[other] == p.params[other]


def test_native_delegation_and_rejected_inputs_do_not_mutate_or_publish(lib):
    ctx = catalog(lib)
    before = bytes(ctx)
    for menu in range(0x84c, 0x858):
        output = c.c_int(99)
        assert lib.af_ui_step(ctx, menu, 7, 0, c.byref(output)) == 1
        assert lib.af_ui_read(ctx, menu, 7, c.byref(output)) == 1
        assert output.value == 99 and bytes(ctx) == before
    for menu in (0, 0x857fffff, 0x85e, 0x15d6, 0x15d7, 0x15d8, 0x15e7):
        output = c.c_int(99)
        assert lib.af_ui_step(ctx, menu, 0, 0, c.byref(output)) < 0
        assert output.value == 99 and bytes(ctx) == before
    output = c.c_int(99)
    assert lib.af_ui_step(ctx, 0x15e6, 0, 0, c.byref(output)) == -2
    p = preset()
    assert lib.af_install(ctx, 20, c.byref(p), 0) == 0
    before = bytes(ctx)
    for parameter, direction in ((8,0),(0,2),(0,0xffffffff)):
        assert lib.af_ui_step(ctx, 0x15e6, parameter, direction, c.byref(output)) < 0
        assert output.value == 99 and bytes(ctx) == before
    route = Route()
    c.memset(c.byref(route), 0xa5, c.sizeof(route))
    before = bytes(route)
    assert lib.af_ui_item(33, c.byref(route)) < 0
    assert bytes(route) == before


def test_native_snapshot_has_eight_independent_values_and_preserves_padding(lib):
    ctx = catalog(lib)
    flags = c.create_string_buffer(bytes([1,0,1,1,0,1,1,1]), 8)
    for slot in range(1,21):
        p = preset(18)
        p.params[0] = slot % 10
        assert lib.af_install(ctx, slot, c.byref(p), 0) == 0
    for index in range(12,32):
        route = Route()
        assert lib.af_ui_item(index,c.byref(route)) == 0
        out = c.create_string_buffer(b'\xa5'*176,176)
        assert lib.af_ui_snapshot(ctx,route.menu,flags,c.byref(out,8)) == 0
        data = bytes(out)[8:]
        expected = read(lib,ctx,route.slot)
        for parameter in range(8):
            assert struct.unpack_from('<iiB',data,0x34+parameter*12) == (
                parameter,expected.params[parameter],flags.raw[parameter])
            assert data[0x3d+parameter*12:0x40+parameter*12] == b'\xa5'*3
        assert struct.unpack_from('<I',data,0x94)[0] == 0
        assert bytes(out)[:8+0x34] == b'\xa5'*(8+0x34)
        assert bytes(out)[8+0x98:] == b'\xa5'*(176-8-0x98)


def test_snapshot_rejection_and_native_delegation_publish_nothing(lib):
    ctx = catalog(lib)
    flags = c.create_string_buffer(b'\x01'*8,8)
    out = c.create_string_buffer(b'\xa5'*160,160)
    for menu,result in ((0x84c,1),(0x15d9,-2),(0x15d8,-1),(0x85e,-1)):
        assert lib.af_ui_snapshot(ctx,menu,flags,out) == result
        assert bytes(out) == b'\xa5'*160
    p = preset()
    assert lib.af_install(ctx,7,c.byref(p),0) == 0
    flags[7] = b'\x02'
    assert lib.af_ui_snapshot(ctx,0x15d9,flags,out) == -1
    assert bytes(out) == b'\xa5'*160


def test_direct_value_assignment_validates_domain_and_preserves_saved_values(lib):
    ctx = catalog(lib)
    p = preset(18)
    assert lib.af_install(ctx,20,c.byref(p),0) == 0
    limits=[(-9,9),(-9,9),(-9,9),(0,9),(-9,9),(0,9),(1,5),(0,9)]
    for parameter,(low,high) in enumerate(limits):
        for value in (low,high):
            output=c.c_int(99)
            assert lib.af_ui_assign(ctx,0x15e6,parameter,value,c.byref(output)) == 0
            assert output.value == value
            assert read(lib,ctx,20).params[parameter] == value
        before=bytes(ctx)
        for invalid in (low-1,high+1,-129,128):
            output=c.c_int(99)
            assert lib.af_ui_assign(ctx,0x15e6,parameter,invalid,c.byref(output)) == -1
            assert output.value == 99 and bytes(ctx) == before
    assert bytes(read(lib,ctx,20,1)) == bytes(p)
    for menu,result in ((0x84c,1),(0x85e,-1),(0x15d9,-2),(0x15d8,-1)):
        output=c.c_int(99);before=bytes(ctx)
        assert lib.af_ui_assign(ctx,menu,0,0,c.byref(output)) == result
        assert output.value == 99 and bytes(ctx) == before
