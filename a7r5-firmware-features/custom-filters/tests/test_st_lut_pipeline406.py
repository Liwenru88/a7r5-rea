"""默认ST转换到保存/通信/双域组件的连续软件证据，不执行CP或ISP。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_edit_joint import SOURCES

HOME = Path(__file__).resolve().parents[1]
ROOT = HOME.parents[1]
PIPELINE_SOURCES = list(dict.fromkeys([*SOURCES,
    'af_repository.c', 'af_repository_service.c', 'af_repository_import.c',
    'af_repository_recipe.c', 'af_media.c', 'af_posix.c', 'af_labels.c', 'af_labels_store.c',
    'af_ap_manage.c', 'af_persist.c', 'af_store.c', 'af_document.c', 'af_record.c',
    'af_slots.c', 'af_ui.c', 'af_import.c', 'af_joint_fit.c', 'af_joint_basis.c',
    'af_joint_asset.c', 'af_joint_report.c', 'af_grid.c', 'af_grid_fit.c', 'af_cube.c',
    'af_reference_joint.c', 'af_reference_domain.c', 'af_reference_samples.c',
    'af_reference_assets.c', 'af_reference_grid.c', 'af_reference_import.c', 'af_reference_blob.S',
    'af_runtime_ap406.c', 'af_imaging406.c', 'af_runtime.c', 'af_handshake.c', 'af_apply_wire.c',
    'af_recipe_transport.c', 'af_cp_recipe406.c', 'af_cp_native_bank406.c',
    'af_cp_override406.c', 'af_cp_input406.c', 'af_cp_copy406.c', 'af_cp406_state.c',
    'af_cp_capture406.c', 'af_cp_capture_fields406.c', 'af_cp_capture_color406.c',
    'af_cp_components406.c']))
FLAGS = ('AF_CP_PRESET406', 'AF_FACTORY_RESTORE406', 'AF_SNAPSHOT_OVERLAY406',
         'AF_RECIPE_BRIDGE406', 'AF_JOINT_BASIS406', 'AF_REFERENCE_IMPORT406',
         'AF_CP_NATIVE406', 'AF_CP_CAPTURE406', 'AF_CP_CAPTURE_INPUT406', 'AF_CP_CAPTURE_COPIES406')


def build(folder, sanitize=False):
    binary = folder / 'st-pipeline'
    command = ['clang', '-std=c11', '-O1' if sanitize else '-O2', '-Wall', '-Wextra', '-Werror',
               '-ffp-contract=off', *['-D' + f for f in FLAGS], '-I' + str(HOME / 'native'),
               str(HOME / 'tests/st_lut_pipeline406.c'),
               *[str(HOME / 'native' / n) for n in PIPELINE_SOURCES], '-o', str(binary)]
    if sanitize:
        command[1:1] = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary, command


def cube(variant):
    rows = ['TITLE "ST software integration"', 'LUT_3D_SIZE 3']
    for b in (0, .5, 1):
        for g in (0, .5, 1):
            for r in (0, .5, 1):
                values = ((r ** 1.12 * .94 + g * .02, g ** 1.05 * .96, b ** .95 * .91)
                          if not variant else (r ** .88 * .91, g ** 1.12 * .93 + b * .02, b ** 1.07 * .98))
                rows.append(' '.join(f'{v:.7f}' for v in values))
    return ('\n'.join(rows) + '\n').encode()


def prepare(folder):
    body, media, output = [folder / n for n in ('body', 'media', 'output')]
    for p in (body, media, output):
        p.mkdir()
    for i, name in enumerate(('ST.cube', 'ST2.cube')):
        (media / name).write_bytes(cube(i))
    cp = ROOT / '.local/fixed-custom-filters/integration52-source406/components/cpapp-b.bin'
    raw = cp.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
    record = folder / 'st-original-record.bin'
    record.write_bytes(raw[0xdcca0c - 0x108000:0xdcca0c - 0x108000 + 576])
    return body, media, record, output


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    return build(tmp_path_factory.mktemp('st-lut-continuous'))[0]


@pytest.mark.parametrize('scenario', ['success', 'cancel', 'invalid', 'reject'])
def test_default_st_cube_to_saved_slot_and_native_photo_components(executable, tmp_path, scenario):
    body, media, record, output = prepare(tmp_path)
    if scenario == 'invalid':
        (media / 'ST2.cube').write_bytes(b'LUT_3D_SIZE 3\n0 0 0\n')
    run = subprocess.run([str(executable), *map(str, (body, media, record, output)), scenario],
                         cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert run.returncode == 0, run.stderr
    if scenario == 'success':
        receipt = json.loads(run.stdout)
        assert receipt['status'] == 'PASS_ST_CONTINUOUS_SOFTWARE_CHAIN'
        assert receipt['frames'] == 56 and receipt['accepted'] == 2
        assert receipt['private_gamma_calls'] > 2 and receipt['grid_calls'] > 2
        assert receipt['camera_pixels_verified'] is False
        assert not (media / 'ST.cube').exists()
        assert (body / 'A7LOOKS1/C07_A.rec').is_file()
        assert (body / 'A7LOOKS1/C07_B.rec').is_file()
        assert (output / 'C07_G0000000000000002.a7filter').is_file()
        # 这里只运行锁定CP的纯软件Gamma构表函数，不启动CP系统或任何硬件模型。
        sys.path.insert(0, str(HOME))
        from a7filters.cp_gamma406 import TABLE, setup
        from a7filters.cp_machine import WORK

        raw_cp = (ROOT / '.local/fixed-custom-filters/integration52-source406/components/cpapp-b.bin').read_bytes()
        candidates = sorted(output.glob('gamma-candidate-*-mode*.bin'))
        assert len(candidates) == receipt['private_gamma_calls']
        for path in candidates:
            mode = int(path.stem.rsplit('mode', 1)[1])
            candidate = path.read_bytes()
            assert len(candidate) == 576 and candidate[0x204:0x220] == record.read_bytes()[0x204:0x220]
            machine, route = setup(raw_cp, 0, 6)
            machine.put(WORK + 0x8000, candidate)
            machine.word(TABLE + route * 28 + 6 * 4, WORK + 0x8000)
            machine.put(WORK + 0x4000 - 16, b'\xa5' * (0x800 + 32))
            result = machine.run(0x41363c, arguments=(mode, WORK + 0x2000, WORK + 0x4000), limit=100000)
            assert result['status'] == 'RETURNED'
            assert machine.read(WORK + 0x424c, 516) == candidate[:516]
            assert machine.read(WORK + 0x4000 - 16, 16) == machine.read(WORK + 0x4800, 16) == b'\xa5' * 16
            (output / (path.stem + '-original-core.bin')).write_bytes(machine.read(WORK + 0x4000, 0x800))
            machine.cpu = None
    elif scenario == 'cancel':
        assert not list((body / 'A7LOOKS1').glob('C07_*.rec'))
    elif scenario == 'invalid':
        assert (body / 'A7LOOKS1/C07_A.rec').is_file()
        assert not (body / 'A7LOOKS1/C07_B.rec').exists()
    else:
        assert (output / 'C07_G0000000000000002.a7filter').is_file()
        assert not list(output.glob('gamma-candidate-*.bin'))
