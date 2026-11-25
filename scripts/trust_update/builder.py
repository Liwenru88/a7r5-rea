"""实时编译 libjit 与 kit 信任更新原生载荷（AArch64 无依赖共享库，32MiB + 9 块强制策略）。"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from elftools.elf.elffile import ELFFile

import device_profile

PROJECT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TRUST_SOURCES = PROJECT / 'a7r5-desktop/sources/trust'
PREPARED_ENGINE = PROJECT / 'a7r5-desktop/prepared/engine'
UPDATER_TRUST_SRC = PROJECT / 'a7r5-updater-trust/src'
DEFAULT_PUBLIC_KEY = PROJECT / 'a7r5-updater-trust/public-key.pem'


def resolve_tool(env_var, candidates):
    """按环境变量与常见 Homebrew 安装位置解析本机工具路径。"""
    configured = os.environ.get(env_var)
    if configured:
        return Path(configured)
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


CLANG = resolve_tool(
    'A7R5_CLANG',
    (
        Path('/opt/homebrew/opt/llvm/bin/clang'),
        Path('/usr/local/opt/llvm/bin/clang'),
    ),
)
LLD = resolve_tool(
    'A7R5_LLD',
    (
        Path('/opt/homebrew/opt/lld/bin/ld.lld'),
        Path('/usr/local/opt/lld/bin/ld.lld'),
    ),
)

PARTITION_BYTES = 25100288
PATCH_COUNT = 258
MAX_PAYLOAD_BYTES = 1048576


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def load_profile():
    """加载内嵌的 4.00 设备基线配置。"""
    return device_profile.load_profile()


def _pack_trust_materials(plan, sectors):
    """校验写入计划与扇区材料并组装统一结构。"""
    profile = load_profile()
    rows = sectors['rows']
    if not rows or [r['offset'] for r in rows] != [r['offset'] for r in plan['rows']]:
        raise ValueError('写入计划与扇区清单不一致')

    before_parts = []
    after_parts = []
    for row in rows:
        if row['offset'] % 512 or not 0 <= row['offset'] <= PARTITION_BYTES - 512:
            raise ValueError(f'扇区偏移越界或未对齐：{row["offset"]}')
        b = base64.b64decode(row['before'], validate=True)
        a = base64.b64decode(row['after'], validate=True)
        if len(b) != 512 or len(a) != 512:
            raise ValueError('扇区材料长度不是 512 字节')
        before_parts.append(b)
        after_parts.append(a)

    return {
        'plan': plan,
        'sectors': sectors,
        'profile': profile,
        'before_bytes': b''.join(before_parts),
        'after_bytes': b''.join(after_parts),
    }


def build_trust_materials_from_image(preimage_path, *, mode='replace-key', public_key_path=None):
    """纯离线：从指定 cnflasha1 前像现场计算当前机身专属写入计划与扇区材料。"""
    if mode not in ('replace-key', 'skip-key'):
        raise ValueError(f'不支持的信任补丁模式：{mode}')
    raw = Path(preimage_path).read_bytes()
    if len(raw) != PARTITION_BYTES:
        raise ValueError(f'cnflasha1 镜像长度应为 {PARTITION_BYTES} 字节，实际为 {len(raw)}')

    src_dir = str(UPDATER_TRUST_SRC)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    import sector_plan
    import trust_recipe

    actual_sha = sha256_bytes(raw)
    replace_key = mode == 'replace-key'
    pub_path = Path(public_key_path) if public_key_path is not None else DEFAULT_PUBLIC_KEY
    public_key = pub_path.read_bytes() if replace_key else None
    result, _patched, _new_sums, _record = trust_recipe.construct(
        raw,
        None,
        public_key,
        source_sha=actual_sha,
        replace_key=replace_key,
    )
    target_sha = sha256_bytes(result)
    plan = sector_plan.make_plan(raw, result, source_sha=actual_sha, target_sha=target_sha)
    sectors = {
        'source_sha256': actual_sha,
        'target_sha256': target_sha,
        'bytes': len(raw),
        'rows': [
            {
                'offset': row['offset'],
                'before': base64.b64encode(raw[row['offset'] : row['offset'] + 512]).decode('ascii'),
                'after': base64.b64encode(result[row['offset'] : row['offset'] + 512]).decode('ascii'),
            }
            for row in plan['rows']
        ],
    }
    return _pack_trust_materials(plan, sectors)


def load_trust_materials(preimage_path=None, *, mode='replace-key', public_key_path=None):
    """加载信任写入材料：传入前像时纯离线现算，否则回退读取 prepared/engine/。"""
    if preimage_path is not None:
        return build_trust_materials_from_image(preimage_path, mode=mode, public_key_path=public_key_path)

    plan_path = PREPARED_ENGINE / 'write-plan.json'
    sectors_path = PREPARED_ENGINE / 'trust-sectors.json'
    if not plan_path.is_file() or not sectors_path.is_file():
        raise FileNotFoundError(
            '未找到 a7r5-desktop/prepared/engine/{write-plan.json,trust-sectors.json}；'
            '请传入 --preimage /path/to/cnflasha1.img 按当前机身镜像离线现算计划'
        )

    plan = json.loads(plan_path.read_text())
    sectors = json.loads(sectors_path.read_text())
    return _pack_trust_materials(plan, sectors)


def verify_toolchain():
    """检查本地交叉编译器与链接器是否可用。"""
    for tool in (CLANG, LLD):
        if not tool.exists():
            raise FileNotFoundError(f'缺少交叉编译工具：{tool}')


def _write_headers(build_dir, engine, run_id, materials, *, restore_preload=None, fixture_target=None):
    control = '/tmp_wbshd/a7r5-control-' + run_id
    ram_dir = '/tmp_wbshd/a7r5-trust-' + run_id
    jit_defs = {
        'RUN_ID': run_id,
        'STATE_PATH': control + '/task.state',
        'STATE_NEW': control + '/task.state.new',
        'OUTPUT_PATH': control + '/task.output',
        'CLAIM_PATH': control + '/task.claim',
        'TICKET_PATH': control + '.ticket',
        'TICKET_BYTES': 'A7R5_LIBJIT ' + run_id + '\n',
        'LIBJIT_PATH': '/tmp/jiritsu/libJit.so',
        'CAPTURE_CONTROL_PARENT': '/tmp_wbshd',
        'CAPTURE_CONTROL_DIR': control,
        'TRUST_USER_CHECK_DIAGNOSTICS': 1,
        'TRUST_RESOURCE_CHECK_DIAGNOSTICS': 1,
    }
    if engine == 'kit':
        if restore_preload is None:
            raise ValueError('kit 载荷编译需要指定还原用 preload 基线')
        kit_so = f'/tmp_wbshd/a7r5-trust-{run_id}.so'
        jit_defs.update(
            {
                'PRELOAD_PATH': '/etc/ld.so.preload',
                'GATE_PATH': '/proc/self/cmdline',
                'KIT_SO_PATH': kit_so,
                'ARM_BYTES': kit_so + '\n',
                'RESTORE_PRELOAD': restore_preload,
            }
        )

    jit_header = ''.join(f'#define {k} {json.dumps(v)}\n' for k, v in jit_defs.items())
    if fixture_target is not None:
        jit_header += '#define TRUST_FIXTURE 1\n'
    (build_dir / 'jit_config.h').write_text(jit_header)

    plan = materials['plan']
    sectors = materials['sectors']
    profile = materials['profile']
    old = materials['before_bytes']
    new = materials['after_bytes']

    trust_defs = {
        'ORIGINAL_SHA': sectors['source_sha256'],
        'CANDIDATE_SHA': sectors['target_sha256'],
        'TRUST_FORCE_MODE': 1,
        'TRUST_FORCE_SECTOR_READBACK': 1,
        'TRUST_PLANNED_RESOURCE_BUDGET': 1,
        'BEFORE_PATCH_SHA': sha256_bytes(old),
        'AFTER_PATCH_SHA': sha256_bytes(new),
        'RAM_DIR': ram_dir,
        'JOURNAL_PATH': ram_dir + '/journal',
        'READBACK_PATH': ram_dir + '/partition.logical',
        'EXPECTED_PRELOAD': bytes.fromhex(profile['preload_baselines'][0][1]).decode('ascii'),
        'OUTPUT_BEGIN': f'A7R5_TRUST_BEGIN_{run_id}\n',
        'OUTPUT_END': f'A7R5_TRUST_END_{run_id}\n',
        'TARGET_PATH': fixture_target or '/dev/cnflasha1',
        'FORCE_PRELOAD_A': bytes.fromhex(profile['preload_baselines'][0][1]).decode('ascii'),
        'FORCE_PRELOAD_B': bytes.fromhex(profile['preload_baselines'][1][1]).decode('ascii'),
    }
    patch_count = len(plan['rows'])
    lines = [f'#define {k} {json.dumps(v)}\n' for k, v in trust_defs.items()]
    lines.append(f'#define PARTITION_BYTES {PARTITION_BYTES}UL\n#define PATCH_COUNT {patch_count}U\n')
    lines.append(
        'static const unsigned long PATCH_OFFSETS[]={'
        + ','.join(f'{r["offset"]}UL' for r in plan['rows'])
        + '};\n'
    )
    lines.append(
        'static const unsigned char PATCH_CHECKSUM[]={'
        + ','.join(str(int(r['phase'] == 'checksum')) for r in plan['rows'])
        + '};\n'
    )
    for name, raw in (('BEFORE_SECTORS', old), ('AFTER_SECTORS', new)):
        lines.append(f'static const unsigned char {name}[]={{' + ','.join(str(b) for b in raw) + '};\n')
    (build_dir / 'trust_config.h').write_text(''.join(lines))


def _verify_elf(so_path):
    raw = so_path.read_bytes()
    if len(raw) >= MAX_PAYLOAD_BYTES:
        raise ValueError(f'编译产物超出通道上限 ({len(raw)} >= {MAX_PAYLOAD_BYTES})')
    with so_path.open('rb') as handle:
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
        if needed or undefined:
            raise ValueError(f'载荷存在未预期依赖或未定义符号：needed={needed}, undef={undefined}')
        if not any(t.entry.d_tag == 'DT_INIT' for t in tags):
            raise ValueError('载荷缺少 DT_INIT 入口')
    return raw


def compile_trust_so(build_dir, engine, run_id, materials, *, restore_preload=None, fixture_target=None):
    """编译单个 AArch64 原生信任更新共享库并校验 ELF 属性。"""
    verify_toolchain()
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    _write_headers(
        build_dir,
        engine,
        run_id,
        materials,
        restore_preload=restore_preload,
        fixture_target=fixture_target,
    )
    source = (TRUST_SOURCES / 'libjit-trust.c') if engine == 'libjit' else (HERE / 'kit-trust.c')
    out_so = build_dir / ('libJit.so' if engine == 'libjit' else f'kit-{run_id}.so')
    command = [
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
        str(source),
        '-o',
        str(out_so),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f'编译 {engine} 载荷失败：\n{proc.stderr}')
    return _verify_elf(out_so)


def build_package(package_dir, engine, run_id, baseline_host, materials, *, fixture_target=None):
    """构建完整会话运行包：config.json、write-plan/sectors 与按引擎预编载荷。"""
    if engine not in ('libjit', 'kit'):
        raise ValueError(f'不支持的引擎类型：{engine}')
    package_dir = Path(package_dir)
    mat_dir = package_dir / 'materials'
    mat_dir.mkdir(parents=True, exist_ok=True)

    profile = json.loads(json.dumps(materials['profile']))
    bus, ports = baseline_host['bus'], baseline_host['ports']
    for row in profile['interfaces'].values():
        row['bus'] = bus
        row['ports'] = ports

    ram_dir = '/tmp_wbshd/a7r5-trust-' + run_id
    cfg = {
        'run_id': run_id,
        'engine': engine,
        'interfaces': profile['interfaces'],
        'host_baseline': baseline_host,
        'version_sha256': profile['version_sha256'],
        'loader_sha256': profile['loader_sha256'],
        'loader_bytes': profile['loader_bytes'],
        'preload_baselines': profile['preload_baselines'],
        'force_install': True,
        'trust_control_layout': 'ram-v2',
        'trust_readback_format': 'planned-sectors-v2',
        'trust_resource_policy': 'planned-sectors-32m-v1',
        'ram_dir': ram_dir,
        'journal_path': ram_dir + '/journal',
        'readback_path': ram_dir + '/partition.logical',
        'partition_bytes': PARTITION_BYTES,
        'task_seconds': 60,
        'observe_seconds': 60,
        'expected_output_begin': f'A7R5_TRUST_BEGIN_{run_id}\n',
        'expected_output_end': f'A7R5_TRUST_END_{run_id}\n',
    }
    (package_dir / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
    (mat_dir / 'write-plan.json').write_text(json.dumps(materials['plan'], ensure_ascii=False, indent=2) + '\n')
    (mat_dir / 'trust-sectors.json').write_text(json.dumps(materials['sectors'], ensure_ascii=False, indent=2) + '\n')

    if engine == 'libjit':
        raw = compile_trust_so(
            package_dir / 'build-libjit',
            'libjit',
            run_id,
            materials,
            fixture_target=fixture_target,
        )
        (mat_dir / 'libJit.so').write_bytes(raw)
        (mat_dir / 'ticket.bin').write_bytes(f'A7R5_LIBJIT {run_id}\n'.encode('ascii'))
    else:
        # 预先针对两种已知 /etc/ld.so.preload 基线各编一份，USB 会话中零延迟直选。
        for name, hex_bytes in profile['preload_baselines']:
            preload_text = bytes.fromhex(hex_bytes).decode('ascii')
            raw = compile_trust_so(
                package_dir / f'build-kit-{name}',
                'kit',
                run_id,
                materials,
                restore_preload=preload_text,
                fixture_target=fixture_target,
            )
            (mat_dir / f'kit-{name}.so').write_bytes(raw)

    return cfg
