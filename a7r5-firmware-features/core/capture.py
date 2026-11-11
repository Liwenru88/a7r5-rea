"""绑定阶段四拍摄模块及 AVCAM 分区的前像和独立回读。"""
from pathlib import Path
import importlib.util
import json
import subprocess

from .plan import AVCAM_IMAGE, FEATURES, ROOT, digest, read_json, require, sha

NATIVE = FEATURES / 'native24-combined'
ASPECT = FEATURES / 'photo-aspect-ratios'
PINS = ASPECT / 'resources.json'
AVCAM = 'AV-CAM.BIN'
MPR_PATH = '/lib/libmpr.so'
MPR = 'usr' + MPR_PATH


def resources(plan):
    paths = [NATIVE / name for name in ('build_capture.py', 'stock400.py',
                                        'stability.py', 'icon_codec.py', 'release417/container_package.py')]
    paths += [FEATURES / 'lens-af-compat/src' / name for name in ('lens_af.py', 'lens_af.S')]
    paths += [NATIVE / 'dependencies/native12-combined' / name for name in ('patches.py', 'unified_icons.py')]
    paths.append(FEATURES / 'independent/profiles/native24-stock/components.json')
    if plan['capture_modules']['aspect']:
        paths += [NATIVE / 'dependencies/native12-combined/upstream/firmware/r5/src/lib/strict_ap_link.py']
        paths += [ASPECT / 'upstream-reference.json', *sorted((ASPECT / 'licenses').glob('*.txt'))]
        paths += [PINS, *(path for path in sorted((ASPECT / 'src').iterdir())
                          if path.suffix in ('.c', '.h', '.S', '.ld', '.py') and not path.name.startswith('test_'))]
    return paths


def build(work, plan, output, runtime):
    capture = plan['capture_modules']
    command = [str(ROOT / '.venv/bin/python'), '-B', str(NATIVE / 'build_capture.py'),
               '--stock', str(work), '--output', str(output)]
    if runtime:
        command += ['--runtime', str(runtime)]
    for key in ('aspect', 'lens_af'):
        if capture[key]:
            command.append('--' + key.replace('_', '-'))
    result = subprocess.run(command, capture_output=True, text=True)
    require(result.returncode == 0, '拍摄组件构建失败\n' + result.stderr)
    receipt = read_json(output / 'build.json')
    require(all(receipt[k] == capture[k] for k in ('aspect', 'lens_af')) and not receipt['camera_io']
            and receipt.get('color_modules') == plan.get('color_modules'),
            '拍摄组件构建回执身份不符')
    require(digest(output / 'cpapp-b.bin') == receipt['CP_sha256'], '拍摄 CP 组件摘要不符')
    if capture['aspect']:
        for name, pin in receipt['resources'].items():
            require(Path(name).name == name and digest(output / name) == pin, '比例资源摘要不符 ' + name)
        for name, key in (('appFw.so', 'AP'), (AVCAM, 'AVCAM')):
            require(digest(output / name) == receipt[key]['target_sha256'], '比例组件摘要不符 ' + name)
        mpr = output / Path(MPR_PATH).name
        mpr_pin = read_json(PINS)['mpr']
        require(mpr_pin['path'] == MPR_PATH and mpr.stat().st_size == receipt['MPR']['target_bytes']
                and receipt['MPR']['source_bytes'] == mpr_pin['bytes']
                and receipt['MPR']['source_sha256'] == mpr_pin['sha256']
                and digest(mpr) == receipt['MPR']['target_sha256'], '比例 libmpr 组件身份不符')
    return receipt


def apply_avcam(work, output, scratch, prepare_fat):
    pin = read_json(PINS)['avcam']
    image = work / 'archive' / AVCAM_IMAGE
    require(pin['image'] == AVCAM_IMAGE and pin['path'] == '/' + AVCAM and digest(image) == pin['image_sha256'],
            'AVCAM FAT 分区前像不符')
    component = output / AVCAM
    expected = dict(image=AVCAM_IMAGE, path=pin['path'], bytes=component.stat().st_size, sha256=digest(component))
    staged = scratch / 'avcam.bin'
    from a7r5dat.fat import FatImage
    original = image.read_bytes()
    require(sha(FatImage(original).read(pin['path'])) == pin['sha256'], 'AVCAM FAT 文件前像不符')
    spec = importlib.util.spec_from_file_location('aspect_fat_avcam', ASPECT / 'src/fat_avcam.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    result, receipt = helper.replace(original, component.read_bytes())
    with staged.open('xb') as stream:
        stream.write(result)
    (scratch / 'AVCAM.json').write_text(json.dumps(receipt, indent=2) + '\n')
    staged.replace(image)
    return expected


def verify_avcam(work, expected):
    from a7r5dat.fat import FatImage

    raw = FatImage((work / 'archive' / AVCAM_IMAGE).read_bytes()).read('/' + AVCAM)
    require(expected == dict(image=AVCAM_IMAGE, path='/' + AVCAM, bytes=len(raw), sha256=sha(raw)),
            '独立解包的 AVCAM FAT 组件不符')


def verify_mpr(work, expected):
    from a7r5dat.ext2read import Ext2

    image = '0700_part_image/dev/nflasha15'
    usr = Ext2(work / 'archive' / image)
    try:
        raw = usr.read_inode(usr.walk(MPR_PATH))
    finally:
        usr.mm.close()
        usr.f.close()
    require(expected == dict(image=image, path=MPR_PATH, bytes=len(raw), sha256=sha(raw)),
            '独立解包的 libmpr 组件不符')
