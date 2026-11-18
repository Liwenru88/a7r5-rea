import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import wave

import pytest


MODULE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('prepare_sound', MODULE / 'host/prepare_sound.py')
sound = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sound)


@pytest.fixture
def compiler():
    executable = shutil.which('cc')
    if not executable:
        pytest.skip('需要宿主 C 编译器')
    return executable


def test_pinned_upstream_files():
    manifest = json.loads((MODULE / 'upstream.json').read_text())
    for name, record in manifest['files'].items():
        assert hashlib.sha256((MODULE / name).read_bytes()).hexdigest() == record['sha256']


def test_convert_inspect_and_replay_catalog(tmp_path, compiler):
    wav = tmp_path / '测试.WAV'
    out = tmp_path / '测试.R5S'
    with wave.open(str(wav), 'wb') as stream:
        stream.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
        stereo = (value for i in range(3841) for value in ((i % 121) * 320 - 19200, 4200))
        stream.writeframes(struct.pack('<7682h', *stereo))
    original = wav.read_bytes()
    converted = sound.convert_file(wav, out, compiler=compiler)
    package = out.read_bytes()
    readback = sound.inspect_file(out)
    assert readback['sha256'] == converted['sha256']
    assert readback['source_wav_sha256'] == hashlib.sha256(original).hexdigest()
    assert readback['sample_rate'] == 24000
    assert [p['percent'] for p in readback['payloads']] == list(range(10, 101, 10))
    assert len({p['sha256'] for p in readback['payloads']}) == 10

    with pytest.raises(sound.SoundError, match='already exists'):
        sound.convert_file(wav, out, compiler=compiler)
    assert out.read_bytes() == package and wav.read_bytes() == original

    bad_header = bytearray(package)
    bad_header[40] ^= 1
    bad_payload = bytearray(package)
    bad_payload[-5] ^= 1
    for damaged, error in [(bad_header, 'CRC32'), (bad_payload, 'SHA256'), (package[:-1], 'size mismatch')]:
        with pytest.raises(sound.SoundError, match=error):
            sound.inspect_bytes(damaged)

    runtime = MODULE / 'runtime'
    replay = tmp_path / 'catalog-replay'
    subprocess.run([compiler, '-std=c11', '-O2', '-I', str(runtime), '-o', str(replay),
                    str(MODULE / 'tests/catalog_replay.c'), str(runtime / 'r5sound_package.c'),
                    str(runtime / 'r5sound_catalog.c'), str(runtime / 'r5sound_integrity.c')], check=True, timeout=30)
    subprocess.run([str(replay), str(out)], check=True, timeout=5)


def test_reject_invalid_wav_before_publishing(tmp_path, compiler):
    source = tmp_path / 'bad.wav'
    output = tmp_path / 'bad.R5S'
    source.write_bytes(b'RIFF\xff\xff\xff\xffWAVEbroken')
    with pytest.raises(sound.SoundError):
        sound.convert_file(source, output, compiler=compiler)
    assert not output.exists()


def test_playback_scheduler_replay(tmp_path, compiler):
    exe = tmp_path / 'replay'
    runtime = MODULE / 'runtime'
    subprocess.run([compiler, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I', str(runtime), '-o', str(exe),
                    str(MODULE / 'tests/replay.c'), str(runtime / 'r5_shutter_scheduler.c')],
                   check=True, timeout=30)
    subprocess.run([str(exe)], check=True, timeout=5)


def test_independent_shutter_profiles(tmp_path, compiler):
    exe = tmp_path / 'profiles-replay'
    runtime = MODULE / 'runtime'
    subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I', str(runtime), '-o', str(exe),
                    str(MODULE / 'tests/profiles_replay.c'), str(runtime / 'r5sound_profiles.c'),
                    str(runtime / 'r5sound_catalog.c'), str(runtime / 'r5sound_package.c'),
                    str(runtime / 'r5sound_integrity.c')], check=True, timeout=30)
    subprocess.run([str(exe)], check=True, timeout=10)


def test_bound_runtime_profiles(tmp_path, compiler):
    work = os.environ.get('R5_SOUND_WORKSPACE')
    if not work:
        pytest.skip('设置 R5_SOUND_WORKSPACE 指向 --custom-sound 构建工作区，回放实际派生服务')
    source = Path(work) / 'import'
    assert (source / 'r5sound_runtime.c').is_file()
    exe = tmp_path / 'runtime-replay'
    objects = ['r5sound_profiles.c', 'r5sound_catalog.c', 'r5sound_package.c',
               'r5sound_integrity.c', 'r5_shutter_ap.c', 'r5_shutter_scheduler.c', 'r5sound_scan.c']
    linker = '-Wl,-dead_strip' if sys.platform == 'darwin' else '-Wl,--gc-sections'
    subprocess.run([compiler, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-ffunction-sections', '-fdata-sections', linker,
                    '-I', str(source), '-o', str(exe), str(MODULE / 'tests/runtime_profiles_replay.c'),
                    *map(str, (source / name for name in objects))], check=True, timeout=30)
    subprocess.run([str(exe)], check=True, timeout=10)
