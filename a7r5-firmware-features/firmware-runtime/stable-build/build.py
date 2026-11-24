#!/usr/bin/env python3
"""从 Sony A7R5 原厂 4.00 官方升级包构建当前稳定版。"""
from __future__ import annotations

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
SOURCE_TREE = HERE / 'source-tree'

EXPECTED_STOCK_400_SHA256 = '51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2'


def sha256_file(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def extra_site_packages() -> list[Path]:
    return sorted((ROOT / 'a7r5-dat-tool/.venv/lib').glob('python*/site-packages'))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
            '缺少 Python 依赖包：' + ', '.join(missing_mods) + '。请使用仓库 .venv 执行。'
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
                '  ./scripts/build_from_400.sh /path/to/4.00/BODYDATA.DAT\n'
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


def prepare_build_tree(tree_dir: Path) -> None:
    """复制当前稳定版源码到本次构建的工作目录。"""
    shutil.copytree(SOURCE_TREE, tree_dir, ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))


def extract_stock_nflasha3(baseline_dir: Path, inputs_dir: Path) -> Path | None:
    """从原厂 4.00 归档提取 nflasha3 及内部 AV-CAM.BIN（用于画幅 JPEG/HEIF 编码补丁）。"""
    sys.path.insert(0, str(ROOT / 'a7r5-dat-tool'))
    from a7r5dat.fat import FatImage
    import tarfile

    base_info = json.loads((baseline_dir / 'baseline.json').read_text())
    tar_path = Path(base_info['original_inputs']['original_tar'])
    nflasha3_path = inputs_dir / 'nflasha3'
    with tarfile.open(tar_path, 'r') as tf:
        member = tf.getmember('0700_part_image/dev/nflasha3')
        with tf.extractfile(member) as src, nflasha3_path.open('wb') as dst:
            shutil.copyfileobj(src, dst)
    avcam_bytes = FatImage(nflasha3_path.read_bytes()).read('/av-cam.bin')
    (inputs_dir / 'AV-CAM.BIN').write_bytes(avcam_bytes)
    return nflasha3_path


def main() -> None:
    release = json.loads((HERE / 'KNOWN-ISSUES.json').read_text(encoding='utf-8'))
    version = release['version']
    parser = argparse.ArgumentParser(
        description=f'{__doc__} 当前版本为 {version}。',
        epilog=(
            '示例：\n'
            f'  ./scripts/build_from_400.sh /path/to/4.00/BODYDATA.DAT -o ~/Desktop/a7r5-{version}'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('original_pos', nargs='?', type=Path, default=None, help='原厂 4.00 BODYDATA.DAT 路径')
    parser.add_argument('-i', '--original', dest='original_opt', type=Path, default=None, help='原厂 4.00 BODYDATA.DAT 路径')
    parser.add_argument('-o', '--output', type=Path, default=None, help='输出目录（不存在的新路径）')
    parser.add_argument('--keep-work', action='store_true', help='导出到外部目录时保留 .local/ 中间构建目录')
    args = parser.parse_args()

    preflight_check()
    original = resolve_original_path(args.original_pos, args.original_opt)
    pkg_mod = load_module(HERE / 'container_package.py', 'stable_container_package')
    filter_payload = pkg_mod.compile_default_filters()

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    allowed_roots = (ROOT / '.local', ROOT / 'a7r5-firmware-features/builds')
    export_dir: Path | None = None

    if args.output is None:
        work_out = (ROOT / f'.local/build-stable-{stamp}').resolve()
    else:
        requested = args.output.expanduser().resolve()
        if requested.exists():
            raise FileExistsError(f'输出目录已存在：{requested}')
        if any(requested.is_relative_to(r) for r in allowed_roots):
            work_out = requested
        else:
            export_dir = requested
            work_out = (ROOT / f'.local/build-stable-work-{stamp}').resolve()

    if work_out.exists():
        raise FileExistsError(f'工作目录已存在：{work_out}')

    work_out.parent.mkdir(parents=True, exist_ok=True)
    work_out.mkdir(mode=0o700)

    python_bin = os.path.abspath(sys.executable)
    native12_build = HERE.parent / 'dependencies/native12-combined/build.py'
    baseline_dir = work_out / 'baseline'
    inputs_dir = work_out / 'inputs'
    tree_dir = work_out / 'build-tree'
    runtime_dir = work_out / 'runtime'
    rebuild_dir = work_out / 'rebuild'
    package_dir = work_out / 'package'

    try:
        # 1. 解包原厂 4.00 并生成上游基线
        run_step(
            'Step 1/4: 解包原厂 4.00 BODYDATA.DAT 并生成基线',
            [python_bin, '-B', str(native12_build), '--phase', 'baseline', '--original', str(original), '--output', str(baseline_dir)],
        )

        # 2. 整理编译输入（含原厂 AV-CAM.BIN）与补丁编译树
        print(f'\n==> Step 2/4: 准备 {version} 编译输入与源码树', flush=True)
        inputs_dir.mkdir(mode=0o700)
        shutil.copyfile(baseline_dir / 'work/inputs/ap_baseline.so', inputs_dir / 'ap_baseline.so')
        shutil.copyfile(baseline_dir / 'work/inputs/cp_baseline.bin', inputs_dir / 'cp_baseline.bin')
        shutil.copyfile(baseline_dir / 'inputs/nflasha15', inputs_dir / 'nflasha15')
        stock_nflasha3 = extract_stock_nflasha3(baseline_dir, inputs_dir)
        prepare_build_tree(tree_dir)

        # 3. 双次确定性构建组件
        tree_build_py = tree_dir / 'a7r5-firmware-features/firmware-runtime/build.py'
        for name, target in (('runtime', runtime_dir), ('rebuild', rebuild_dir)):
            run_step(
                f'Step 3/4: 构建 {version} 组件 ({name})',
                [
                    python_bin,
                    '-B',
                    str(tree_build_py),
                    '--baseline',
                    str(baseline_dir),
                    '--inputs',
                    str(inputs_dir),
                    '--output',
                    str(target),
                ],
            )

        # 4. 容器封包、RSA 签名与全量回读校验
        print(f'\n==> Step 4/4: 封装 {version} BODYDATA.DAT 并执行全量校验', flush=True)
        receipt = pkg_mod.package_stable(
            package_dir,
            baseline=baseline_dir,
            runtime_dir=runtime_dir,
            rebuild_dir=rebuild_dir,
            stock_nflasha3=stock_nflasha3,
            release=release,
            filter_payload=filter_payload,
        )

        delivery = package_dir / 'delivery'
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
                    'version': version,
                    'original_400_dat': str(original),
                    'delivery_dir': str(final_delivery),
                    'BODYDATA_DAT_sha256': receipt['sha256'],
                    'R5NATIVE_BIN_sha256': receipt['filter_sha256'],
                    'components': receipt['components'],
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
