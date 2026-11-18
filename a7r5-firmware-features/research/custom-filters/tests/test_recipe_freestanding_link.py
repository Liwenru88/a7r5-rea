"""紧凑Thumb接收核心必须自行链接，不依赖原映像未提供的编译器helper。"""
from pathlib import Path
import subprocess
import ctypes as c
import hashlib


NATIVE = Path(__file__).resolve().parents[1] / 'native'


def test_compact_thumb_receiver_links_without_unproven_runtime_helpers(tmp_path):
    objects = []
    for source in [*[NATIVE / n for n in ('af_recipe_transport.c', 'af_joint_asset.c',
        'af_sha256.c', 'af_joint.c', 'af_slots.c')], NATIVE.parent / 'tests/native_memory.c']:
        target = tmp_path / (source.name + '.o')
        run = subprocess.run(['clang', '--target=armv7a-none-eabi', '-mthumb', '-march=armv7-a',
            '-mfpu=none', '-mfloat-abi=soft', '-Oz', '-ffreestanding', '-fno-builtin',
            '-fno-stack-protector', '-ffunction-sections', '-fdata-sections',
            '-c', str(source), '-o', str(target)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        objects.append(target)
    linker = tmp_path / 'research.ld'
    linker.write_text('SECTIONS { . = 0x92000000; .text : { *(.text*) *(.rodata*) } '
        '.data : { *(.data*) } .bss : { *(.bss*) } /DISCARD/ : { *(.ARM.exidx*) } }')
    run = subprocess.run(['/opt/homebrew/opt/lld/bin/ld.lld', '--gc-sections',
        *['--undefined=' + n for n in ('af_recipe_rx_frame', 'af_recipe_rx_validate',
        'af_recipe_rx_finish', 'af_recipe_tx_ack')], '-T', str(linker),
        *map(str, objects), '-o', str(tmp_path / 'NOT-INSTALLABLE.elf')],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


def test_sha_padding_boundaries_preserve_independent_digest(tmp_path):
    library = tmp_path / 'sha.so'
    run = subprocess.run(['clang', '-shared', '-fPIC', '-O2', str(NATIVE / 'af_sha256.c'),
        '-o', str(library)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    api = c.CDLL(str(library))
    api.af_sha256.argtypes = [c.c_void_p, c.c_size_t, c.c_void_p]
    for count in (0, 1, 55, 56, 63, 64, 65, 119, 120, 127, 128, 129, 1943, 65537):
        data = bytes((i * 17 + 3) % 256 for i in range(count))
        output = (c.c_uint8 * 32)()
        assert api.af_sha256(data, count, output) == 0
        assert bytes(output) == hashlib.sha256(data).digest()
