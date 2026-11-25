"""/tmp/jiritsu kit 扫描/清理载荷编译器与运行包构建器。"""
import json
from pathlib import Path
import re
import subprocess
import sys

from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
TRUST_DIR = PROJECT / 'scripts/trust_update'
if str(TRUST_DIR) not in sys.path:
    sys.path.insert(0, str(TRUST_DIR))

import builder as trust_builder
import device_profile

TRUST_SOURCES = PROJECT / 'a7r5-desktop/sources/trust'
CLANG = trust_builder.CLANG
LLD = trust_builder.LLD
MAX_PAYLOAD_BYTES = 1048576
EXTRA_NAME_PATTERN = re.compile(r'^[A-Za-z0-9._-]+$')


def validate_extra_names(extra_names):
    """严格校验用户额外指定的单级普通文件名，禁止路径穿越或特殊控制字符。"""
    cleaned = []
    seen = set()
    for raw in extra_names or ():
        if not raw or raw in ('.', '..') or '/' in raw or '\\' in raw:
            raise ValueError(f'非法的单级文件名：{raw!r}')
        if len(raw) >= 256 or not EXTRA_NAME_PATTERN.fullmatch(raw):
            raise ValueError(f'文件名包含不支持字符或超长：{raw!r}')
        if raw not in seen:
            seen.add(raw)
            cleaned.append(raw)
    return cleaned


def _compile_clean_so(build_dir, run_id, *, apply, restore_preload, extra_names=(), target_dir='/tmp/jiritsu', require_fat=True):
    if not CLANG.exists() or not LLD.exists():
        raise FileNotFoundError('缺少 clang/lld 交叉编译工具链')
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    control = f'/tmp_wbshd/a7r5-cleanctrl-{run_id}'
    kit_so = f'/tmp_wbshd/a7r5-clean-{run_id}.so'
    defs = {
        'RUN_ID': run_id,
        'CAPTURE_CONTROL_PARENT': '/tmp_wbshd',
        'CAPTURE_CONTROL_DIR': control,
        'STATE_PATH': control + '/task.state',
        'STATE_NEW': control + '/task.state.new',
        'OUTPUT_PATH': control + '/task.output',
        'PRELOAD_PATH': '/etc/ld.so.preload',
        'GATE_PATH': '/proc/self/cmdline',
        'KIT_SO_PATH': kit_so,
        'ARM_BYTES': kit_so + '\n',
        'RESTORE_PRELOAD': restore_preload,
        'CLEAN_TARGET_DIR': target_dir,
        'CLEAN_BEGIN': f'A7R5_CLEAN_BEGIN_{run_id}\n',
        'CLEAN_END': f'A7R5_CLEAN_END_{run_id}\n',
    }
    header_lines = [f'#define {k} {json.dumps(v)}\n' for k, v in defs.items()]
    header_lines.append(f'#define CLEAN_APPLY {1 if apply else 0}\n')
    header_lines.append(f'#define REQUIRE_FAT_FS {1 if require_fat else 0}\n')
    extra_c = '"' + ''.join(n + '\\0' for n in extra_names) + '"'
    header_lines.append(f'#define EXTRA_NAMES_BLOB {extra_c}\n')
    header_lines.append(f'#define EXTRA_NAMES_LEN {sum(len(n) + 1 for n in extra_names)}\n')
    (build_dir / 'jit_config.h').write_text(''.join(header_lines))

    out_so = build_dir / f'kit-clean-{run_id}.so'
    cmd = [
        str(CLANG),
        '--target=aarch64-linux-gnu',
        '--ld-path=' + str(LLD),
        '-nostdlib',
        '-ffreestanding',
        '-fno-builtin',
        '-fno-stack-protector',
        '-fPIC',
        '-shared',
        '-fvisibility=hidden',
        '-O2',
        '-Wall',
        '-Wextra',
        '-Werror',
        '-Wl,--no-undefined',
        '-Wl,-z,max-page-size=65536',
        '-Wl,-init,_init',
        '-I',
        str(build_dir),
        '-I',
        str(TRUST_SOURCES),
        str(HERE / 'kit-clean.c'),
        '-o',
        str(out_so),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f'编译清理载荷失败：\n{proc.stderr}')

    raw = out_so.read_bytes()
    if len(raw) >= MAX_PAYLOAD_BYTES:
        raise ValueError(f'清理载荷超出通道上限 ({len(raw)} >= {MAX_PAYLOAD_BYTES})')
    with out_so.open('rb') as handle:
        elf = ELFFile(handle)
        if elf['e_machine'] != 'EM_AARCH64' or elf['e_type'] != 'ET_DYN':
            raise ValueError('载荷 ELF 架构或类型错误')
        tags = list(elf.get_section_by_name('.dynamic').iter_tags())
        needed = [t.needed for t in tags if t.entry.d_tag == 'DT_NEEDED']
        undefined = [
            s.name
            for s in elf.get_section_by_name('.dynsym').iter_symbols()
            if s.name and s['st_shndx'] == 'SHN_UNDEF'
        ]
        if needed or undefined or not any(t.entry.d_tag == 'DT_INIT' for t in tags):
            raise ValueError(f'载荷动态符号或入口不合要求：needed={needed}, undef={undefined}')
    return raw


def build_clean_package(package_dir, run_id, baseline_host, *, apply=True, extra_names=(), target_dir='/tmp/jiritsu', require_fat=True):
    """构建完整 kit 清理运行包（预编两种 preload 基线）。"""
    extra = validate_extra_names(extra_names)
    package_dir = Path(package_dir)
    mat_dir = package_dir / 'materials'
    mat_dir.mkdir(parents=True, exist_ok=True)

    profile = device_profile.load_profile()
    bus, ports = baseline_host['bus'], baseline_host['ports']
    for row in profile['interfaces'].values():
        row['bus'] = bus
        row['ports'] = ports

    for name, hex_bytes in profile['preload_baselines']:
        preload_text = bytes.fromhex(hex_bytes).decode('ascii')
        raw = _compile_clean_so(
            package_dir / f'build-{name}',
            run_id,
            apply=apply,
            restore_preload=preload_text,
            extra_names=extra,
            target_dir=target_dir,
            require_fat=require_fat,
        )
        (mat_dir / f'kit-{name}.so').write_bytes(raw)

    cfg = {
        'run_id': run_id,
        'mode': 'apply' if apply else 'scan',
        'target_dir': target_dir,
        'extra_names': extra,
        'interfaces': profile['interfaces'],
        'host_baseline': baseline_host,
        'version_sha256': profile['version_sha256'],
        'loader_sha256': profile['loader_sha256'],
        'loader_bytes': profile['loader_bytes'],
        'preload_baselines': profile['preload_baselines'],
        'control_prefix': f'/tmp_wbshd/a7r5-cleanctrl-{run_id}/task',
        'kit_so_path': f'/tmp_wbshd/a7r5-clean-{run_id}.so',
        'expected_output_begin': f'A7R5_CLEAN_BEGIN_{run_id}\n',
        'expected_output_end': f'A7R5_CLEAN_END_{run_id}\n',
        'observe_seconds': 60,
    }
    (package_dir / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
    return cfg
