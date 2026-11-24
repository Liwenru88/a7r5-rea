"""从锁定的原厂解包目录构建 AF、十档纵横比及其 24 槽变体。"""
import argparse
from pathlib import Path
import json
import shutil
import sys

from stock400 import AP_SHA, CP_SHA, DAT_SHA, USR

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / path) for path in ('photo-aspect-ratios/src', 'lens-af-compat/src')]
from lens_af import apply_lens_af
import build_ap
import build_avcam
import build_cp
from build_cp import digest
from build_mpr import build_mpr
from build_resources import build_resources
from a7r5dat.ext2read import Ext2
from a7r5dat.fat import FatImage
import patches


def read_json(path):
    return json.loads(path.read_text())


def checked(path, pin):
    raw = path.read_bytes()
    if digest(raw) != pin:
        raise ValueError('组件前像摘要不符 ' + str(path))
    return raw


def build(stock, output, *, runtime=None, lens_af=False, aspect=False):
    if read_json(stock / 'manifest.json')['source']['sha256'] != DAT_SHA or not (lens_af or aspect):
        raise ValueError('需要原厂 4.00 解包目录和有效拍摄模块选择')
    output.mkdir(mode=0o700)
    cp_path, cp_sha = stock / 'components/cpapp-b.bin', CP_SHA
    ap_path, ap_sha = stock / 'components/usr/lib/appFw.so', AP_SHA
    pins = read_json(HERE.parent / 'independent/profiles/native24-stock/components.json')
    icons = {Path(path).name: sha for path, sha in pins['stock_USR_files'].items() if path.endswith('.uxc')}
    colors, custom_sound = None, False
    if runtime:
        record = read_json(runtime / 'build.json')
        if (record['profile'], record['base_DAT_sha256']) != ('native24-stock', DAT_SHA):
            raise ValueError('拍摄模块需要原厂 4.00 的 24 槽组件回执')
        colors = record.get('color_modules')
        custom_sound = record.get('sound_layout') == 'custom-dual-full'
        if colors is not None and (not colors.get('fl23') or record['disabled_modules'] or
                                   not aspect or (not lens_af and colors.get('factory_six'))):
            raise ValueError('色彩和拍摄组合需要全开 24 槽、FL2／FL3 与已登记的拍摄组合')
        cp_path, cp_sha = runtime / 'cpapp-b.bin', record['CP_sha256']
        ap_path, ap_sha = runtime / 'appFw.so', record['AP_sha256']
        icons = {name: record['components'][name]['sha256'] for name in icons}
    cp = checked(cp_path, cp_sha)
    receipt = {'lens_af': lens_af, 'aspect': aspect, 'camera_io': False}
    if custom_sound:
        receipt['sound_layout'] = 'custom-dual-full'
    if colors is not None:
        receipt['color_modules'] = colors
    if aspect:
        ap = checked(ap_path, ap_sha)
        ap_elf = build_ap.compile_ap(output, ap, source_sha=ap_sha)
        ap, receipt['AP'] = build_ap.apply_ap(ap, ap_elf, source_sha=ap_sha)
        (output / 'appFw.so').write_bytes(ap)
        cp_elf = build_cp.compile_cp(output, stock=runtime is None, shared_color=colors is not None,
                                      custom_sound=custom_sound)
        cp, receipt['CP_aspect'] = build_cp.apply_cp(cp, cp_elf, source_sha=cp_sha,
            shared_color=colors is not None, custom_sound=custom_sound)
        cp_sha = receipt['CP_aspect']['target_sha256']

        capture_pins = read_json(HERE.parent / 'photo-aspect-ratios/resources.json')
        pin = capture_pins['avcam']
        image = checked(stock / 'archive' / pin['image'], pin['image_sha256'])
        avcam = FatImage(image).read(pin['path'])
        if len(avcam) != pin['bytes'] or digest(avcam) != pin['sha256']:
            raise ValueError('AVCAM 原厂组件身份不符')
        avcam, receipt['AVCAM'] = build_avcam.apply_avcam(avcam, build_avcam.compile_avcam(output))
        (output / 'AV-CAM.BIN').write_bytes(avcam)

        mpr_pin = capture_pins['mpr']
        app = Ext2(stock / USR)
        try:
            mpr = app.read_inode(app.walk(mpr_pin['path']))
            if len(mpr) != mpr_pin['bytes'] or digest(mpr) != mpr_pin['sha256']:
                raise ValueError('libmpr 原厂组件身份不符')
            mpr, receipt['MPR'] = build_mpr(mpr, output)
            (output / Path(mpr_pin['path']).name).write_bytes(mpr)
            images = runtime
            if not runtime:
                images = output / 'stock-images'
                images.mkdir()
                for name in icons:
                    (images / name).write_bytes(app.read_inode(app.walk('/share/app/' + name)))
        finally:
            app.mm.close()
            app.f.close()
        resources = output / 'resources'
        build_resources(stock / USR, images, resources, image_pins=icons, factory_six=colors is not None)
        receipt['resources'] = read_json(resources / 'build.json')
        for name in receipt['resources']:
            shutil.copyfile(resources / name, output / name)
    if lens_af:
        cp, receipt['CP_lens_af'] = apply_lens_af(cp, patches, output, source_sha=cp_sha)
    (output / 'cpapp-b.bin').write_bytes(cp)
    receipt['CP_sha256'] = digest(cp)
    (output / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stock', 'output', 'runtime'):
        parser.add_argument('--' + name, type=Path, required=name != 'runtime')
    parser.add_argument('--lens-af', action='store_true')
    parser.add_argument('--aspect', action='store_true')
    args = parser.parse_args()
    build(args.stock, args.output, runtime=args.runtime, lens_af=args.lens_af, aspect=args.aspect)
