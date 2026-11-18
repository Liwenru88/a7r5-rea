#!/usr/bin/env python3
"""从 Sony A7R5 原厂 4.00 官方升级包 (BODYDATA.DAT) 端到端一键构建 4.28 稳定版本。"""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

EXPECTED_STOCK_400_SHA256 = '51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2'
EXPECTED_428_DAT_SHA256 = 'ed98e87af9e32fec7538a4579986528c1af694e4e55c855b3f7cebfb0eea4408'
EXPECTED_428_BIN_SHA256 = '19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6'


def sha256_file(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def extra_site_packages() -> list[Path]:
    return sorted((ROOT / 'a7r5-dat-tool/.venv/lib').glob('python*/site-packages'))


def preflight_check() -> None:
    """构建前检查 Python 依赖、宿主机工具链与密钥文件。"""
    for site in extra_site_packages():
        if str(site) not in sys.path:
            sys.path.insert(0, str(site))

    missing_mods = [
        pkg
        for mod, pkg in (
            ('elftools', 'pyelftools'),
            ('Cryptodome', 'pycryptodomex'),
            ('cryptography', 'cryptography'),
            ('pytest', 'pytest'),
        )
        if importlib.util.find_spec(mod) is None
    ]
    if missing_mods:
        raise RuntimeError(
            '缺少 Python 依赖包：'
            + ', '.join(missing_mods)
            + '。请使用仓库 .venv 或安装上述依赖后重试。'
        )

    required_bins = (
        ('/opt/homebrew/opt/llvm/bin/clang', 'brew install llvm'),
        ('/opt/homebrew/opt/lld/bin/ld.lld', 'brew install lld'),
        ('/opt/homebrew/opt/e2fsprogs/sbin/e2fsck', 'brew install e2fsprogs'),
        ('/usr/bin/openssl', 'macOS 系统 OpenSSL'),
    )
    missing_bins = [
        f'{path}（安装建议：{hint}）'
        for path, hint in required_bins
        if not os.access(path, os.X_OK)
    ]
    if shutil.which('clang') is None:
        missing_bins.append('clang（请安装 Xcode Command Line Tools: xcode-select --install）')
    if missing_bins:
        raise RuntimeError('缺少宿主机构建工具：\n  - ' + '\n  - '.join(missing_bins))

    for rel in (
        'a7r5-dat-tool/keys/sony-original-public.pem',
        'a7r5-dat-tool/keys/research-public.pem',
        'a7r5-dat-tool/keys/research-signing-private.pem',
    ):
        if not (ROOT / rel).is_file():
            raise FileNotFoundError(f'缺少签名/验签密钥文件：{ROOT / rel}')


def run_step(label: str, cmd: list[str]) -> None:
    print(f'\n==> {label}', flush=True)
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    dat_site = extra_site_packages()
    if dat_site:
        existing = env.get('PYTHONPATH', '')
        extra = os.pathsep.join(str(p) for p in dat_site)
        env['PYTHONPATH'] = f'{extra}{os.pathsep}{existing}' if existing else extra
    result = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if result.returncode != 0:
        raise RuntimeError(f'{label} 失败（退出码 {result.returncode}）')


def resolve_original_path(pos_path: Path | None, opt_path: Path | None) -> Path:
    if pos_path is not None and opt_path is not None:
        if pos_path.resolve() != opt_path.resolve():
            raise ValueError('不可同时传入不同的位置参数与 --original 路径')
        chosen = opt_path
    elif opt_path is not None:
        chosen = opt_path
    elif pos_path is not None:
        chosen = pos_path
    else:
        chosen = ROOT / 'a7r5-firmware-images/官方升级包/BODYDATA.DAT'
        if not chosen.is_file():
            raise FileNotFoundError(
                '未找到默认原厂 4.00 升级包。\n'
                '请显式传入原厂 4.00 BODYDATA.DAT 路径，例如：\n'
                '  ./scripts/build_428_from_400.sh /path/to/4.00/BODYDATA.DAT\n'
                f'预期原厂 4.00 SHA256：{EXPECTED_STOCK_400_SHA256}'
            )

    original = chosen.expanduser().resolve()
    if not original.is_file():
        raise FileNotFoundError(f'找不到原厂 4.00 升级包：{original}')
    actual_sha = sha256_file(original)
    if actual_sha != EXPECTED_STOCK_400_SHA256:
        raise ValueError(
            f'原厂 4.00 BODYDATA.DAT 摘要不匹配：{original}\n'
            f'  实际 SHA256：{actual_sha}\n'
            f'  预期 SHA256：{EXPECTED_STOCK_400_SHA256}'
        )
    return original


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            '示例：\n'
            '  ./scripts/build_428_from_400.sh /path/to/4.00/BODYDATA.DAT\n'
            '  ./scripts/build_428_from_400.sh -i /path/to/4.00/BODYDATA.DAT -o ~/Desktop/a7r5-4.28'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'original_pos',
        nargs='?',
        type=Path,
        default=None,
        help='原厂 4.00 BODYDATA.DAT 路径（也可使用 -i/--original）',
    )
    parser.add_argument(
        '-i',
        '--original',
        dest='original_opt',
        type=Path,
        default=None,
        help='原厂 4.00 BODYDATA.DAT 路径',
    )
    parser.add_argument(
        '-o',
        '--output',
        type=Path,
        default=None,
        help='输出目录（若位于 .local/ 或 a7r5-firmware-features/builds/ 外，将仅导出最终交付目录）',
    )
    parser.add_argument(
        '--keep-work',
        action='store_true',
        help='导出到外部输出目录时保留 .local/ 下的中间构建目录',
    )
    args = parser.parse_args()

    preflight_check()
    original = resolve_original_path(args.original_pos, args.original_opt)

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    allowed_roots = (ROOT / '.local', ROOT / 'a7r5-firmware-features/builds')
    export_dir: Path | None = None

    if args.output is None:
        work_out = (ROOT / f'.local/build-428-{stamp}').resolve()
    else:
        requested = args.output.expanduser().resolve()
        if requested.exists():
            raise FileExistsError(f'输出目录已存在：{requested}')
        if any(requested.is_relative_to(r) for r in allowed_roots):
            work_out = requested
        else:
            export_dir = requested
            work_out = (ROOT / f'.local/build-428-work-{stamp}').resolve()

    if work_out.exists():
        raise FileExistsError(f'工作目录已存在：{work_out}')

    work_out.parent.mkdir(parents=True, exist_ok=True)
    work_out.mkdir(mode=0o700)

    python_bin = os.path.abspath(sys.executable)
    native12_build = HERE.parent / 'dependencies/native12-combined/build.py'
    archived_tree_build = HERE / 'source-tree/build-tree/a7r5-firmware-features/native24-combined/build.py'
    release428_build = HERE / 'build.py'

    baseline_dir = work_out / 'baseline'
    inputs_dir = work_out / 'inputs'
    runtime_dir = work_out / 'runtime'
    rebuild_dir = work_out / 'rebuild'
    package_dir = work_out / 'package'

    try:
        # 1. 解包原厂 4.00 并构建上游基线
        run_step(
            'Step 1/4: 解包原厂 4.00 BODYDATA.DAT 并生成基线',
            [python_bin, '-B', str(native12_build), '--phase', 'baseline', '--original', str(original), '--output', str(baseline_dir)],
        )

        # 2. 整理 4.28 编译输入（FL2/FL3 基底 + 原厂 nflasha15）
        print('\n==> Step 2/4: 准备 4.28 编译输入 (ap_baseline.so / cp_baseline.bin / nflasha15)', flush=True)
        inputs_dir.mkdir(mode=0o700)
        shutil.copyfile(baseline_dir / 'work/inputs/ap_baseline.so', inputs_dir / 'ap_baseline.so')
        shutil.copyfile(baseline_dir / 'work/inputs/cp_baseline.bin', inputs_dir / 'cp_baseline.bin')
        shutil.copyfile(baseline_dir / 'inputs/nflasha15', inputs_dir / 'nflasha15')

        # 3. 双次确定性构建 4.28 组件
        for name, target in (('runtime', runtime_dir), ('rebuild', rebuild_dir)):
            run_step(
                f'Step 3/4: 构建 4.28 组件 ({name})',
                [
                    python_bin,
                    '-B',
                    str(archived_tree_build),
                    '--baseline',
                    str(baseline_dir),
                    '--inputs',
                    str(inputs_dir),
                    '--output',
                    str(target),
                ],
            )

        # 4. 封装、RSA 签名与独立回读校验
        run_step(
            'Step 4/4: 封装 4.28 BODYDATA.DAT 并执行全量校验',
            [
                python_bin,
                '-B',
                str(release428_build),
                '--baseline',
                str(baseline_dir),
                '--runtime',
                str(runtime_dir),
                '--rebuild',
                str(rebuild_dir),
                '--output',
                str(package_dir),
            ],
        )

        delivery = package_dir / 'delivery'
        actual_dat = sha256_file(delivery / 'BODYDATA.DAT')
        actual_bin = sha256_file(delivery / 'R5NATIVE.BIN')
        if actual_dat != EXPECTED_428_DAT_SHA256:
            raise ValueError(f'4.28 BODYDATA.DAT 摘要不一致：{actual_dat} != {EXPECTED_428_DAT_SHA256}')
        if actual_bin != EXPECTED_428_BIN_SHA256:
            raise ValueError(f'4.28 R5NATIVE.BIN 摘要不一致：{actual_bin} != {EXPECTED_428_BIN_SHA256}')

        final_delivery = delivery
        if export_dir is not None:
            export_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(delivery, export_dir)
            final_delivery = export_dir

        print(
            '\n'
            + json.dumps(
                {
                    'status': 'PASS',
                    'version': '4.28',
                    'original_400_dat': str(original),
                    'delivery_dir': str(final_delivery),
                    'BODYDATA_DAT_sha256': actual_dat,
                    'R5NATIVE_BIN_sha256': actual_bin,
                    'exact_match_428_release': True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
    finally:
        if export_dir is not None and not args.keep_work and work_out.exists():
            shutil.rmtree(work_out, ignore_errors=True)


if __name__ == '__main__':
    main()
