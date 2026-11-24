"""在新输出目录核对画幅组件的真实 FAT/USR 写入和回读；不生成 DAT。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
FEATURES = HERE.parents[1]
ROOT = FEATURES.parent
sys.path[:0] = [str(ROOT / 'a7r5-dat-tool'), str(FEATURES / 'firmware-runtime/release417')]
from a7r5dat.ext2_image_append import AppendImagePatch, ImageBinding
from a7r5dat.ext2_patch import reader
from a7r5dat.ext2read import Ext2
from a7r5dat.fat import FatImage
from container_package import prepare_cp, prepare_usr
from fat_avcam import replace


def sha(raw): return hashlib.sha256(raw).hexdigest()


def verify(stock, candidate, output):
    if output.exists(): raise ValueError('离线分区输出目录必须不存在')
    manifest = json.loads((stock / 'manifest.json').read_text())
    if manifest['source']['sha256'] != '51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2':
        raise ValueError('需要原厂 4.00 已验证输入')
    proof = json.loads((candidate / 'build.json').read_text())
    pins = json.loads((HERE.parent / 'resources.json').read_text())
    if not proof['aspect'] or proof['camera_io']: raise ValueError('候选不是离线画幅组件')
    usr = stock / 'archive/0700_part_image/dev/nflasha15'
    original = usr.read_bytes()
    if sha(original) != '197fc934db37ed9b88701ae7fd2e866126f63e098f6d45e3fd767618af638fa5':
        raise ValueError('原厂 USR 前像不符')
    fs = reader(original)
    files = {'/lib/appFw.so': proof['AP']['target_sha256'], '/lib/libmpr.so': proof['MPR']['target_sha256']}
    files.update({'/share/app/' + name: digest for name, digest in proof['resources'].items()})
    bindings = {}
    for path, expected in files.items():
        new = (candidate / Path(path).name).read_bytes()
        if sha(new) != expected: raise ValueError('候选文件摘要不符 ' + path)
        inode = fs.walk(path); old = fs.read_inode(inode)
        bindings[path] = ImageBinding(inode, len(old), len(new), sha(old), sha(new))
    del fs, original
    output.mkdir(parents=True)
    patch = type('AspectRevision3USR', (AppendImagePatch,), {'_bindings': bindings})
    usr_report = prepare_usr(usr, output / 'nflasha15', output, candidate, patch,
        source_sha='197fc934db37ed9b88701ae7fd2e866126f63e098f6d45e3fd767618af638fa5')
    actual = Ext2(output / 'nflasha15')
    try:
        for path, expected in files.items():
            if sha(actual.read_inode(actual.walk(path))) != expected:
                raise ValueError('USR 独立回读不符 ' + path)
    finally:
        actual.mm.close(); actual.f.close()
    cp_image = stock / 'archive/0700_part_image/dev/nflasha8'
    if sha(cp_image.read_bytes()) != 'a625468fbbd6b0e053e1974a3a0f7e9b9151bc88aaf6261aea21813f9e1f8f46':
        raise ValueError('CP 原厂 FAT 分区前像不符')
    prepare_cp(cp_image, output / 'nflasha8', output, candidate / 'cpapp-b.bin', proof['CP_sha256'])
    avcam = stock / 'archive' / pins['avcam']['image']
    av_raw = avcam.read_bytes()
    if sha(av_raw) != pins['avcam']['image_sha256'] or sha(FatImage(av_raw).read('/av-cam.bin')) != pins['avcam']['sha256']:
        raise ValueError('AVCAM 分区或文件前像不符')
    content = (candidate / 'AV-CAM.BIN').read_bytes()
    if sha(content) != proof['AVCAM']['target_sha256']: raise ValueError('AVCAM 候选摘要不符')
    after, av_report = replace(av_raw, content)
    (output / 'nflasha3').write_bytes(after)
    if FatImage((output / 'nflasha3').read_bytes()).read('/av-cam.bin') != content:
        raise ValueError('AVCAM 磁盘回读不符')
    if FatImage((output / 'nflasha8').read_bytes()).read('/cpapp-b.bin') != (candidate / 'cpapp-b.bin').read_bytes():
        raise ValueError('CP 磁盘回读不符')
    result = dict(passed=True, status='NONINSTALLABLE_PARTITIONS_VERIFIED', camera_io=False,
        DAT_generated=False, device_tested=False, modules=dict(aspect=True, lens_af=proof['lens_af'],
            color=proof.get('color_modules')), usr=usr_report, avcam=av_report,
        readback_files=len(files) + 2, source_kind=manifest.get('input_kind', 'stock_DAT_unpack'),
        components={name: dict(bytes=(candidate / name).stat().st_size, sha256=sha((candidate / name).read_bytes()))
                    for name in ('appFw.so', 'cpapp-b.bin', 'AV-CAM.BIN', 'libmpr.so')})
    (output / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stock', 'candidate', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.stock, args.candidate, args.output)
    print(json.dumps({key: result[key] for key in ('passed', 'status', 'readback_files', 'camera_io')}))
