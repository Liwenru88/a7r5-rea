"""提取已有 ARW／目标 TIFF 的共同采样，供离线校准与复验使用。"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import rawpy
import tifffile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))

import baseline
import photo_preview
from edit_parameter_context import RuntimeColor
from exact_icc import to_srgb


def raw_samples(path, model, long_edge):
    photo_preview.raw_camera_identity(path)
    with rawpy.imread(str(path)) as raw:
        sizes = raw.sizes
        wb = np.asarray(raw.camera_whitebalance[:3], float)
        camera = raw.postprocess(output_color=rawpy.ColorSpace.raw, user_wb=[1, 1, 1, 1],
            use_camera_wb=False, use_auto_wb=False, no_auto_bright=True, no_auto_scale=True,
            gamma=(1, 1), output_bps=16, user_flip=0, demosaic_algorithm=rawpy.DemosaicAlgorithm.LINEAR)
    xs, ys = photo_preview.preview_coordinates(sizes, long_edge=long_edge)
    local = camera[ys[:, None, None], xs[None, :, None]+np.arange(-4, 5)[None, None, :]]
    del camera
    inputs = photo_preview.approximate_front(local, wb, model).reshape(-1, 9, 3)
    return inputs, sizes, xs, ys, (wb/wb[1]).tolist()


def target_samples(path, sizes, xs, ys):
    rotation = {0: 0, 3: 2, 5: 1, 6: 3}[sizes.flip]
    with tifffile.TiffFile(path) as file:
        page = max(file.pages, key=lambda p: p.imagewidth * p.imagelength)
        pixels = np.rot90(page.asarray(maxworkers=4), -rotation)
        profile = page.tags['InterColorProfile'].value
    if pixels.dtype != np.uint16 or pixels.shape != (sizes.crop_height, sizes.crop_width, 3):
        raise ValueError(f'目标图格式、尺寸或方向不匹配：{path}')
    sample = pixels[ys[:, None]-sizes.crop_top_margin, xs[None, :]-sizes.crop_left_margin]
    target, _ = to_srgb(sample.reshape(-1, 3)/65535, profile)
    return target.astype(np.float32)


def extract(data, output, filters, long_edge):
    model = RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID))
    photos = sorted(path for path in (data / '原始照片').iterdir() if path.suffix.lower() == '.arw')
    if len(photos) != 6 or len(filters) != 5:
        raise ValueError('本轮固定使用六个独立场景和五款滤镜')
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(long_edge=long_edge, filters=filters, scenes=[])
    for index, path in enumerate(photos):
        inputs, sizes, xs, ys, _ = raw_samples(path, model, long_edge)
        values = {'inputs': inputs}
        targets = []
        for number, name in enumerate(filters, 1):
            matches = [file for file in (data / '滤镜' / name / '目标照片').glob(path.stem + '*')
                       if file.suffix.lower() in ('.tif', '.tiff')]
            if len(matches) != 1:
                raise ValueError(f'目标图配对不唯一：{name} / {path.name}')
            values[f'target_{number}'] = target_samples(matches[0], sizes, xs, ys)
            targets.append(str(matches[0]))
        filename = f'{path.stem}.npz'
        np.savez(output / filename, **values)
        manifest['scenes'].append(dict(raw=str(path), cache=filename, targets=targets,
            split='calibration' if index % 2 == 0 else 'blind', width=len(xs), height=len(ys)))
        print(path.name, manifest['scenes'][-1]['split'], len(inputs), flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('previous', type=Path, help='五款原对照的 comparison.json')
    parser.add_argument('output', type=Path)
    parser.add_argument('--long-edge', type=int, default=384)
    args = parser.parse_args()
    names = [row['name'] for row in json.loads(args.previous.read_text())['cases']]
    extract(args.data, args.output, names, args.long_edge)
