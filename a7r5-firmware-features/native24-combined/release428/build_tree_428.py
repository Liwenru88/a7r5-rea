"""从 4.27 构建树与 lens-af-compat 材料生成自包含的 4.28 编译输入树，并同步主仓库 runtime。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FEATURES = HERE.parent.parent
sys.path.insert(0, str(HERE))
import patch_428


def copy_item(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def build_tree(base_427_tree: Path, output_tree: Path, receipt_path: Path, *, sync_repo_runtime: bool = True) -> dict:
    if output_tree.exists():
        raise FileExistsError(f'目标构建树已存在：{output_tree}')
    shutil.copytree(base_427_tree, output_tree, symlinks=False, ignore=shutil.ignore_patterns('.DS_Store', '__pycache__'))

    for rel in (
        'a7r5-firmware-features/lens-af-compat/src/lens_af.py',
        'a7r5-firmware-features/lens-af-compat/src/lens_af.S',
    ):
        copy_item(ROOT / rel, output_tree / rel)

    n24 = output_tree / 'a7r5-firmware-features/native24-combined'
    targets = {
        'runtime/unified-look.c': patch_428.patch_unified_look_428,
        'build.py': patch_428.patch_runtime_builder_428,
    }
    patched_records = {}
    for rel, fn in targets.items():
        path = n24 / rel
        before = path.read_text()
        after = fn(before)
        path.write_text(after)
        patched_records[rel] = {
            'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
            'after_sha256': hashlib.sha256(after.encode()).hexdigest(),
        }

    if sync_repo_runtime:
        repo_runtime = FEATURES / 'native24-combined/runtime'
        tree_runtime = n24 / 'runtime'
        for item in sorted(tree_runtime.iterdir()):
            if item.is_file() and item.suffix in ('.c', '.h'):
                shutil.copyfile(item, repo_runtime / item.name)

    receipt = {
        'schema': 'native24-428-af-debounce-patch/1',
        'version': '4.28',
        'base': '4.27',
        'enhancements': [
            'lens-af-compat: 镜头自动对焦能力过滤适配 (CP .text 安全区)',
            'unified-look.c: 轻量队列防抖与快速微调合并保护（无阻塞、不引入 4.23 状态机）',
        ],
        'patched_files': patched_records,
        'camera_io': False,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--base-tree',
        type=Path,
        default=FEATURES / 'builds/4.27-424-planA-20261116/build-tree',
    )
    parser.add_argument(
        '--output-tree',
        type=Path,
        default=FEATURES / 'builds/4.28-427-af-debounce-20261117/build-tree',
    )
    parser.add_argument(
        '--receipt',
        type=Path,
        default=FEATURES / 'builds/4.28-427-af-debounce-20261117/patch-428.json',
    )
    args = parser.parse_args()
    print(json.dumps(build_tree(args.base_tree.resolve(), args.output_tree.resolve(), args.receipt.resolve()), ensure_ascii=False))
