"""执行本次组件的真实ARM指令；仅替换原厂服务，不模拟音频硬件。"""
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import struct
import zlib

import pytest
from elftools.elf.elffile import ELFFile

MODULE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def image():
    directory = os.environ.get('R5_SOUND_WORKSPACE')
    if not directory:
        pytest.skip('需要 --custom-sound 构建产物，设置 R5_SOUND_WORKSPACE')
    output = Path(directory).parent
    support = MODULE.parent / 'native24-combined/dependencies/native12-combined/tests/runtime_support.py'
    spec = importlib.util.spec_from_file_location('shutter_bound_support', support)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BASELINE = output
    record = json.loads((output / 'build.json').read_text())
    assert record['sound_layout'] in ('custom-dual-profile-candidate', 'custom-dual-full')
    return output, module, record


def test_native_sound_menu_and_unified_registry(image):
    output, support, record = image
    ap = support.AP((output / 'appFw.so').read_bytes())
    ap.symbols.update(record['unified']['symbols'])
    registered, requests = [], []
    for symbol in ('r5_native_menu_insert', 'r5_native_row_insert'):
        def insert(cpu, name=symbol):
            registered.append((name, [struct.unpack('<QQ', cpu.read(at, 16))
                                       for at in range(cpu.arg(1), cpu.arg(2), 16)]))
            return 0
        ap.stub(symbol, insert)
    ap.stub('r5sound_count', lambda c: 2)
    ap.stub('r5sound_profile_selected', lambda c: [1, 2][c.arg(0)])
    ap.stub('r5sound_profile_volume', lambda c: [3, 8][c.arg(0)])
    ap.stub('r5sound_profile_blocked', lambda c: 0)
    ap.stub('r5sound_profile_request', lambda c: requests.append(('select', c.arg(0), c.arg(1))) or 0)
    ap.stub('r5sound_profile_volume_request', lambda c: requests.append(('volume', c.arg(0), c.arg(1))) or 0)
    ap.call('r5_filter_menu_register', 0, 0, 0)
    ap.call('r5_filter_rows_register', 0, 0, 0)
    sound_menus = [pair for kind, pairs in registered if kind == 'r5_native_menu_insert' for pair in pairs]
    assert [key for key, _ in sound_menus] == list(range(0x636, 0x63a))
    sound_rows = {key for kind, pairs in registered if kind == 'r5_native_row_insert' for key, _ in pairs}
    expected = (set(range(0x1610, 0x1628)) | set(range(0x1680, 0x16bd)) | set(range(0x16c0, 0x16ca))
                | set(range(0x1700, 0x173d)) | set(range(0x1740, 0x174a)))
    assert sound_rows == expected
    for mid, descriptor in sound_menus:
        assert ap.call('r5_filter_menu_normalize', 0, mid) == mid
        assert ap.call(0x1bd2020, 0, mid) == mid
        get, stage, commit = struct.unpack('<QQQ', ap.read(descriptor + 0x78, 24))
        if mid in (0x636, 0x638):
            group = int(mid == 0x636)
            assert ap.words(descriptor + 0x54, 1) == (3,)
            assert ap.call(get) == [1, 2][group]
            ap.call(stage, 1)
            assert not requests
            assert ap.call(commit, (0x1680 if group else 0x1700) + 1) == 0
            assert requests.pop() == ('select', group, 1)
        else:
            group = int(mid == 0x637)
            assert ap.call(get) == [2, 7][group]
            ap.call(stage, 9)
            assert ap.call(get) == 9 and not requests
            assert ap.call(commit, (0x16c0 if group else 0x1740) + 9) == 0
            assert requests.pop() == ('volume', group, 10)
    for first, count, parent in [(0x1680, 61, 0x636), (0x16c0, 10, 0x637),
                                 (0x1700, 61, 0x638), (0x1740, 10, 0x639)]:
        assert ap.call('r5_filter_row_parent', 0, first) == parent
        assert ap.call('n12_available', 0, first) == 1
        assert ap.call('n12_visible', 0, first) == 1
        assert ap.call('n12_available', 0, first+count-1) == int(count == 10)
    assert ap.string(ap.call('n12_text', 0x02ff5600)) == '电子快门自定义声音'
    assert ap.string(ap.call('n12_text', 0x02ff5700)) == '机械快门自定义声音'


def test_relocations_keep_four_sound_peers_and_plt(image):
    output, _, record = image
    original = ELFFile(io.BytesIO((output / 'upstream-ap/appFw.so').read_bytes()))
    final = ELFFile(io.BytesIO((output / 'appFw.so').read_bytes()))
    old = {r['r_offset']: r['r_addend'] for r in original.get_section_by_name('.rela.dyn').iter_relocations()}
    new = {r['r_offset']: r['r_addend'] for r in final.get_section_by_name('.rela.dyn').iter_relocations()}
    assert len(new) == len(old)-1 and new[0x5053670] != old[0x5053670]
    for target in (0x505fda0, 0x505fdb8, 0x505fdd0, 0x505fde8):
        assert new[target] == old[target]
    assert final.get_section_by_name('.rela.plt').data() == original.get_section_by_name('.rela.plt').data()
    assert final.get_section_by_name('.rela.plt')['sh_addr'] == original.get_section_by_name('.rela.plt')['sh_addr']
    assert record['unified']['inverse_exact']


def test_actual_cp_shared_crc_preserves_filter_protocol(image):
    output, support, _ = image
    cp = support.CP((output / 'cpapp-b.bin').read_bytes())
    rng = random.Random(417)
    for n in (0, 1, 27, 28, 29, 31, 32, 33, 44, 64, 256, 513):
        raw = rng.randbytes(n)
        cp.write(cp.PACKET, raw)
        expected = bytearray(raw)
        for i in range(28, min(32, n)):
            expected[i] = 0
        assert cp.call('r5_diag_crc', cp.PACKET, n) & 0xffffffff == zlib.crc32(expected)
