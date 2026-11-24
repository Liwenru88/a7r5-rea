"""从锁定的原厂工作区和源码构建结果准备三个单功能分区。"""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
FEATURES = HERE.parents[2]
NATIVE = FEATURES / 'firmware-runtime'
sys.path.insert(0, str(NATIVE / 'release417'))

from container_package import AppendImagePatch, ImageBinding, digest, prepare_cp, prepare_usr, prepare_wbi, reader, require

PARTS = Path('archive/0700_part_image/dev')
USR_FILES = ('/lib/appFw.so', '/share/app/image_00_23_IPSX.uxc', '/share/app/image_00_32_IPSX.uxc')


def prepare(stock, runtime, output):
    lock = json.loads((HERE / 'components.json').read_text())
    base = json.loads((stock / 'manifest.json').read_text())
    result = json.loads((runtime / 'build.json').read_text())
    require(base['source']['sha256'] == lock['stock_DAT_sha256'] == result['base_DAT_sha256']
            and result['profile'] == 'native24-stock' and result['components'] == lock['components'],
            '原厂基线或源码构建身份不符')
    for name, pin in lock['stock_partitions'].items():
        require(digest(stock / PARTS / name) == pin, '分区前像不符 ' + name)
    for name, pin in lock['components'].items():
        path = runtime / name
        require(path.stat().st_size == pin['bytes'] and digest(path) == pin['sha256'], '组件身份不符 ' + name)

    source_usr = stock / PARTS / 'nflasha15'
    fs = reader(source_usr.read_bytes())
    bindings = {}
    for path in USR_FILES:
        inode = fs.walk(path)
        original = fs.read_inode(inode)
        pin = lock['components'][Path(path).name]
        bindings[path] = ImageBinding(inode, len(original), pin['bytes'],
                                      lock['stock_USR_files'][path], pin['sha256'])
    del fs, original
    patch_type = type('Native24StockPatch', (AppendImagePatch,), {'_bindings': bindings})

    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    prepare_usr(source_usr, output / 'nflasha15', output, runtime, patch_type,
                source_sha=lock['stock_partitions']['nflasha15'])
    prepare_cp(stock / PARTS / 'nflasha8', output / 'nflasha8', output, runtime / 'cpapp-b.bin',
               lock['components']['cpapp-b.bin']['sha256'], before_sha=lock['stock_CP_sha256'])
    source_wbi = stock / PARTS / 'nflasha5'
    target_wbi = output / 'nflasha5'
    prepare_wbi(source_wbi, target_wbi, invalidate=True, magic=b'WBI2')
    with source_wbi.open('rb') as before, target_wbi.open('rb') as after:
        before.seek(512)
        require(after.read(512) == bytes(512), 'WBI 首扇区非零')
        for block in iter(lambda: before.read(1 << 20), b''):
            require(after.read(len(block)) == block, 'WBI 首扇区外内容变化')
        require(not after.read(1), 'WBI 镜像长度变化')
    print(json.dumps({name: digest(output / name) for name in lock['stock_partitions']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-workspace', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.stock_workspace, args.runtime, args.output)


if __name__ == '__main__':
    main()
