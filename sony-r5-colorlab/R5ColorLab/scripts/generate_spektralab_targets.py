#!/usr/bin/env python3
"""用固定 SpektraLab 配方生成 Color Lab v4.5 色卡和同源实拍目标。"""
import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rawpy
import tifffile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parents[2] / 'SpektraLab'
RESOURCES = Path('/Applications/SpektraLab.app/Contents/Resources/EngineResources')
CHART_DIR = ROOT / 'web/data/chart/sony100mp_5300k_v45'
ALLOWED_SETTINGS = {'density_curve_gamma', 'preflash_exposure', 'enlarger_illuminant', 'scene_curve',
                    'scanner_white_correction', 'scanner_black_correction'}
FIXED = dict(product_defaults=True, auto_exposure=False, input_color_space='ProPhoto RGB',
             input_cctf_decoding=False, output_color_space='sRGB', output_cctf_encoding=True,
             striped=True, grain_active=False, halation_active=False, halation_scatter_amount=0,
             glare_active=False, dir_couplers_active=False, contrast_mask_active=False,
             scene_latitude_active=False, extended_dynamic_range=False, overscan_active=False,
             date_imprint_active=False, digital_intermediate=False, lens_blur_um=0, scanner_lens_blur=0)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stock(resources, stock_id, stage):
    if not re.fullmatch(r'[a-z0-9_]+', stock_id):
        raise ValueError(f'无效的胶片或相纸 ID：{stock_id}')
    path = resources / 'profiles' / f'{stock_id}.json'
    info = json.loads(path.read_text())['info']
    if info['stage'] != stage:
        raise ValueError(f'{stock_id} 不属于 {stage}')
    return info, sha(path)


def recipe(args):
    film, film_sha = stock(args.resources, args.film, 'filming')
    scan = film['type'] == 'positive'
    if scan and (args.paper or args.print_ev or args.yellow or args.magenta):
        raise ValueError('反转片走直扫，请省略相纸和放大机调整')
    # 引擎初始化仍要加载一张相纸，直扫时不会使用它。
    paper_id = args.paper or film.get('target_print') or 'kodak_portra_endura'
    paper, paper_sha = stock(args.resources, paper_id, 'printing')
    if not scan and (film.get('channel_model') == 'bw') != (paper.get('channel_model') == 'bw'):
        raise ValueError('黑白胶片与彩色相纸不能混用')
    extra = json.loads(args.settings.read_text()) if args.settings else {}
    if not isinstance(extra, dict) or set(extra) - ALLOWED_SETTINGS:
        raise ValueError(f'附加参数只能使用 {", ".join(sorted(ALLOWED_SETTINGS))}')
    parameters = dict(FIXED, film_stock=args.film, print_stock=paper_id, scan_film=scan,
        exposure_compensation_ev=args.film_ev, print_exposure=2 ** -args.print_ev,
        y_filter_shift=args.yellow, m_filter_shift=args.magenta, filter_shift_scale=40, **extra)
    return parameters, dict(film_sha256=film_sha, paper_sha256=paper_sha,
                            output='positive-scan' if scan else 'paper-print')


def chart_source(folder, manifest):
    name = manifest['dng_file']
    original = CHART_DIR / name
    if original.is_file():
        source = original
    else:
        source = folder / name
        with gzip.open(original.with_suffix('.DNG.gz'), 'rb') as stream, source.open('wb') as out:
            shutil.copyfileobj(stream, out)
    if sha(source) != manifest['dng_sha256']:
        raise ValueError('色卡 DNG 散列与 v4.5 清单不一致')
    return source


def photo_shape(photo):
    from photo_preview import raw_camera_identity

    raw_camera_identity(photo)
    with rawpy.imread(str(photo)) as raw:
        sizes = raw.sizes
    width, height = sizes.crop_width, sizes.crop_height
    if sizes.flip not in (0, 3, 5, 6):
        raise ValueError(f'不支持的实拍 RAW 方向：{photo.name}')
    return (height, width) if sizes.flip in (5, 6) else (width, height)


def render(args, source, destination, folder, delta, icc, shape):
    buffer = folder / 'render.rgba16'
    source_sha = sha(source)
    process = subprocess.run([str(args.renderer), str(args.resources), str(source), str(delta),
        str(args.raw_ev), 'source' if args.baseline_ev is None else str(args.baseline_ev), str(buffer)],
        check=True, stdout=subprocess.PIPE, text=True)
    report = json.loads(process.stdout)
    width, height, stride = (report[key] for key in ('width', 'height', 'row_stride_px'))
    if (width, height) != shape or not width <= stride or buffer.stat().st_size != stride * height * 8:
        raise ValueError(f'{source.name} 解码尺寸 {width}×{height}，预期 {shape[0]}×{shape[1]}，请核对有效画幅')
    if sha(source) != source_sha:
        raise ValueError(f'渲染期间源文件发生变化：{source.name}')
    params = report.pop('open')['params']
    requested = json.loads(delta.read_text())
    for key, value in requested.items():
        if key != 'product_defaults' and params.get(key) != value:
            raise ValueError(f'SpektraLab 参数回读与配方不符：{key}')
    pixels = np.memmap(buffer, mode='r', dtype='<u2', shape=(height, stride, 4))
    tifffile.imwrite(destination, np.ascontiguousarray(pixels[:, :width, :3]),
        photometric='rgb', metadata=None, iccprofile=icc)
    del pixels
    buffer.unlink()
    return dict(source_sha256=source_sha, output_sha256=sha(destination), output=destination.name,
                decode=report, resolved_parameters=params)


def run(args):
    sys.path.insert(0, str(ROOT / 'web'))
    photos = [photo.resolve(strict=True) for photo in args.photo]
    if any(not p.is_file() or p.suffix.lower() != '.arw' for p in photos):
        raise ValueError('实拍验证图需要 A7R V 的原始 ARW 文件')
    if len({p.stem.casefold() for p in photos}) != len(photos):
        raise ValueError('实拍 ARW 的文件名不能重复')
    if args.no_chart and not photos:
        raise ValueError('跳过色卡时至少提供一张实拍 ARW')
    if args.output.exists():
        raise ValueError(f'输出目录已存在：{args.output}')
    parameters, identities = recipe(args)
    icc = (args.resources / 'io/sRGB.icc').read_bytes()
    commit = (args.renderer.parent / 'SOURCE-COMMIT').read_text().strip()
    chart = json.loads((CHART_DIR / 'manifest.json').read_text())
    report = dict(schema='r5-spektralab-targets/1', spektralab_source_commit=commit,
        renderer_sha256=sha(args.renderer), engine_sha256=sha(args.renderer.parent/'libspektralab_engine.dylib'),
        resource_sha256={name:sha(args.resources/name) for name in ('spektralab.metallib',
            'spektralab_constants.bin', 'neutral_print_filters.json', 'io/sRGB.icc')},
        format='RGB TIFF 16-bit sRGB', white_balance='as-shot', recipe=parameters,
        raw_ev=args.raw_ev, baseline_ev=args.baseline_ev, **identities, photos=[])

    with tempfile.TemporaryDirectory(prefix='.spektralab-', dir=args.output.parent) as directory:
        folder = Path(directory)
        delta = folder / 'recipe.json'
        delta.write_text(json.dumps(parameters, allow_nan=False, indent=2) + '\n')
        staged = folder / 'targets'
        staged.mkdir()
        if not args.no_chart:
            source = chart_source(folder, chart)
            target = staged / 'ColorLab-v4.5-target.tif'
            print('正在渲染完整 v4.5 色卡', flush=True)
            row = render(args, source, target, folder, delta, icc, (chart['width'], chart['height']))
            if row['decode']['raw_orientation'] != 1:
                raise ValueError('色卡 RAW 的方向与训练布局不符')
            from chart_target import decode
            samples, audit = decode(target.read_bytes(), chart['dataset_id'])
            if samples.shape != (chart['samples'], 3) or not np.isfinite(samples).all():
                raise ValueError('Color Lab 无法读回全部色块')
            report['chart'] = dict(row, source=chart['dng_file'], samples=len(samples),
                dataset_id=chart['dataset_id'], icc=audit['icc_policy'])
        for photo in photos:
            print(f'正在渲染实拍 {photo.name}', flush=True)
            target = staged / f'{photo.stem}_SpektraLab.tif'
            row = render(args, photo, target, folder, delta, icc, photo_shape(photo))
            report['photos'].append(dict(row, source=str(photo), role='validation'))
        (staged / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + '\n')
        args.output.mkdir(exist_ok=False)
        for path in sorted(staged.iterdir(), key=lambda value: value.name == 'manifest.json'):
            path.rename(args.output / path.name)


def bounded(value, low, high):
    number = float(value)
    if not low <= number <= high:
        raise argparse.ArgumentTypeError(f'请输入 {low} 至 {high} 之间的数值')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='尚不存在的输出目录')
    parser.add_argument('--film', default='kodak_ektar_100', help='SpektraLab 胶片 ID')
    parser.add_argument('--paper', help='相纸 ID，留空使用胶片默认相纸')
    parser.add_argument('--photo', type=Path, action='append', default=[], help='实拍 ARW，可重复指定')
    parser.add_argument('--no-chart', action='store_true', help='仅生成实拍验证图')
    parser.add_argument('--raw-ev', type=lambda v: bounded(v, -8, 8), default=0.)
    parser.add_argument('--baseline-ev', type=lambda v: bounded(v, -8, 8), help='显式统一 RAW 解码基准，默认保留各文件基准')
    parser.add_argument('--film-ev', type=lambda v: bounded(v, -8, 8), default=0.)
    parser.add_argument('--print-ev', type=lambda v: bounded(v, -3, 3), default=0., help='印相亮度，正值提亮')
    parser.add_argument('--yellow', type=lambda v: bounded(v, -1, 1), default=0.)
    parser.add_argument('--magenta', type=lambda v: bounded(v, -1, 1), default=0.)
    parser.add_argument('--settings', type=Path, help='附加全局渲染参数 JSON')
    parser.add_argument('--renderer', type=Path, default=SOURCE/'engine/build/colorlab/spektralab-render-raw')
    parser.add_argument('--resources', type=Path, default=RESOURCES)
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'生成失败：{error}\n')
    print(args.output / 'manifest.json')


if __name__ == '__main__':
    main()
