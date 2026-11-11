"""对同一组 ARW 采样，比较新旧 BIN 与已提供 TIFF 的离线照片色差。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'web'), str(ROOT / 'scripts')]

import numpy as np
import rawpy
import tifffile

import baseline
import core
import photo_preview
from compute_backend import render_native
from edit_parameter_context import ParameterContext, RuntimeColor
from exact_icc import to_srgb
from fit_bin_joint import grid_from
from gpu_runtime import cpu_reference
from measured_response import get
from patch_sampling import center_mean
from perceptual import de2000, to_lab


def metrics(predicted, target):
    p, t = [np.floor(np.clip(value, 0, 1) * 255 + .5) for value in (predicted, target)]
    delta = de2000(to_lab(p), to_lab(t))
    return dict(rgb_rmse=float(np.sqrt(np.mean((p - t)**2))),
                delta_e00_mean=float(delta.mean()), delta_e00_p95=float(np.percentile(delta, 95)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('benchmark', type=Path)
    parser.add_argument('--long-edge', type=int, default=384)
    parser.add_argument('--include-current', action='store_true', help='同时复算冻结的current.BIN对照')
    args = parser.parse_args()
    if not 64 <= args.long_edge <= 3840:
        parser.error('采样长边需要在64～3840之间')
    photo_preview.PREVIEW_LONG_EDGE = args.long_edge
    context = ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)))
    report = dict(scope='same approximate RAW front; BIN readback; not camera capture acceptance',
                  source=str(args.data), sampling_long_edge=args.long_edge,
                  photo_used_for_training=False, photo_used_for_selection=False, cases=[])
    cases = []
    for folder in sorted(args.benchmark.glob('[0-9][0-9]')):
        comparison = folder / 'comparison.json'
        if not comparison.is_file():
            continue
        value = json.loads(comparison.read_text())
        models = {}
        arms = [('legacy', 'legacy.BIN'), ('selected', 'R5NATIVE.BIN')]
        if args.include_current:
            arms.append(('current','current.BIN'))
        for arm, filename in arms:
            entry, = core.compiler.unpack((folder / filename).read_bytes())['entries']
            models[arm] = (context.build(**core.slot_native_parameters(context, entry)), grid_from(entry))
        cases.append((folder, value, models, get(json.loads((folder / 'response.json').read_text()))))
    if len(cases) != 5:
        parser.error('需要完成五款滤镜的 BIN 对照后再验证照片')
    for raw_file in sorted((args.data / '原始照片').glob('*')):
        if raw_file.suffix.lower() != '.arw':
            continue
        photo_preview.raw_camera_identity(raw_file)
        with rawpy.imread(str(raw_file)) as raw:
            sizes = raw.sizes
            wb = np.array(raw.camera_whitebalance[:3], dtype=float)
            camera = raw.postprocess(output_color=rawpy.ColorSpace.raw, user_wb=[1, 1, 1, 1],
                use_camera_wb=False, use_auto_wb=False, no_auto_bright=True, no_auto_scale=True,
                gamma=(1, 1), output_bps=16, user_flip=0,
                demosaic_algorithm=rawpy.DemosaicAlgorithm.LINEAR)
        xs, ys = photo_preview.preview_coordinates(sizes)
        neighborhoods = camera[ys[:, None, None], xs[None, :, None] + np.arange(-4, 5)[None, None, :]]
        del camera
        inputs = photo_preview.approximate_front(neighborhoods, wb, context.base).reshape(-1, 9, 3)
        del neighborhoods
        for folder, value, models, response in cases:
            targets = list((args.data / '滤镜' / value['name'] / '目标照片').glob(raw_file.stem + '*.tif'))
            if len(targets) != 1:
                raise ValueError('照片配对不唯一：' + raw_file.stem)
            with tifffile.TiffFile(targets[0]) as file:
                page = max(file.pages, key=lambda p: p.imagewidth * p.imagelength)
                image = page.asarray(maxworkers=4)
                profile = page.tags['InterColorProfile'].value
            # TIFF 已按拍摄方向转正，先还原到相同传感器坐标后抽取对应像素。
            rotation = {0: 0, 3: 2, 5: 1, 6: 3}[sizes.flip]
            image = np.rot90(image, -rotation)
            if image.shape[:2] != (sizes.crop_height, sizes.crop_width):
                raise ValueError('目标照片存在裁切或缩放：' + str(targets[0]))
            target = image[ys[:, None] - sizes.crop_top_margin, xs[None, :] - sizes.crop_left_margin].reshape(-1, 3) / 65535
            del image
            target, _ = to_srgb(target, profile)
            scores = {}
            for arm, (model, grid) in models.items():
                with cpu_reference():
                    base = center_mean(render_native(model, inputs)) / 16383
                scores[arm] = metrics(response.predict_cpu(base, grid), target)
            report['cases'].append(dict(filter=value['name'], raw=raw_file.name,
                target=str(targets[0]), samples=len(target), camera_white_balance=wb.tolist(), **scores))
            print(raw_file.stem, value['name'], scores['legacy']['rgb_rmse'],
                  scores['selected']['rgb_rmse'], flush=True)
        (args.benchmark / 'photo_comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
