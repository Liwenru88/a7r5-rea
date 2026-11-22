"""Batch-render lightweight JPG sample previews for all filters in sony-r5-colorlab/filters."""
from __future__ import annotations

import sys
import time
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1] / 'web'
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import numpy as np
from PIL import Image
from rawpy import _rawpy as rawpy

import core
import filter_library
import photo_backend
import photo_preview as pp
from baseline import V45_ID, resolve
from compute_backend import render_native
from edit_parameter_context import ParameterContext, RuntimeColor
from grid_models import default_response

SOURCES = [
    Path('/Users/wenruli/Desktop/验证数据/原始照片/3660894239.arw'),
    Path('/Users/wenruli/Desktop/验证数据/原始照片/3864086486.arw'),
]
LONG_EDGE = 720
CHUNK_PIXELS = 65536


def decode_arws(base_model):
    decoded = []
    for src in SOURCES:
        t0 = time.time()
        raw = rawpy.RawPy()
        raw.open_file(str(src))
        raw.unpack()
        sizes = raw.sizes
        wb = np.array(raw.camera_whitebalance[:3], dtype=float)
        camera = raw.postprocess(
            output_color=rawpy.ColorSpace.raw,
            user_wb=[1, 1, 1, 1],
            use_camera_wb=False,
            use_auto_wb=False,
            no_auto_bright=True,
            no_auto_scale=True,
            gamma=(1, 1),
            output_bps=16,
            user_flip=0,
            demosaic_algorithm=rawpy.DemosaicAlgorithm.LINEAR,
        )
        raw.close()
        xs, ys = pp.preview_coordinates(sizes, long_edge=LONG_EDGE)
        rotation = {3: 2, 5: 1, 6: 3}.get(sizes.flip, 0)
        rows = []
        for y in ys:
            neighborhoods = camera[y, xs[:, None] + np.arange(-4, 5)[None, :]]
            rows.append(pp.approximate_front(neighborhoods, wb, base_model))
        front_flat = np.concatenate(rows, axis=0)  # (H*W, 9, 3)
        decoded.append((src.stem, len(ys), len(xs), rotation, front_flat))
        print(f'Decoded {src.name} -> {len(ys)}x{len(xs)} in {time.time() - t0:.2f}s', flush=True)
    return decoded


def render_flat(model, front_flat):
    total = len(front_flat)
    out = np.empty((total, 3), dtype=np.float32)
    for start in range(0, total, CHUNK_PIXELS):
        end = min(start + CHUNK_PIXELS, total)
        rendered = render_native(model, front_flat[start:end])
        out[start:end] = rendered[:, 4] / 16383.0
    return out


def main():
    t_start = time.time()
    cat = filter_library.catalog()
    filters_root = Path(cat['filters_dir'])
    samples_root = filters_root / '_samples'
    samples_root.mkdir(parents=True, exist_ok=True)

    context = ParameterContext(RuntimeColor.from_capture(*resolve(V45_ID)))
    response = default_response()
    photo_backend.enable(response)

    pending = []
    for item in cat['filters']:
        out_dir = samples_root / item['category']
        out_dir.mkdir(parents=True, exist_ok=True)
        p1 = out_dir / f"{item['stem']}_1.jpg"
        p2 = out_dir / f"{item['stem']}_2.jpg"
        if not (p1.is_file() and p2.is_file()):
            pending.append((item, p1, p2))

    print(f'Total filters: {len(cat["filters"])}, pending: {len(pending)}', flush=True)
    if not pending:
        return

    decoded = decode_arws(context.base)

    for idx, (item, p1, p2) in enumerate(pending, start=1):
        t0 = time.time()
        bin_path = filters_root / f"{item['key']}.bin"
        entry = core.compiler.unpack(bin_path.read_bytes())['entries'][0]
        model = context.build(**core.slot_native_parameters(context, entry))
        grid = np.asarray(entry['grid_5x9x9']['coefficients']).reshape(3, 405).T

        for (stem, h, w, rot, front_flat), out_path in zip(decoded, (p1, p2)):
            rgb_flat = render_flat(model, front_flat)
            rgb_grid = pp.photo_grid_rows(rgb_flat.reshape(h, w, 3), grid, response)
            img = Image.fromarray(pp.quantize(np.rot90(rgb_grid, rot)))
            img.save(out_path, format='JPEG', quality=86, optimize=True, icc_profile=pp.SRGB_ICC)

        if idx % 10 == 0 or idx == len(pending):
            print(f'[{idx}/{len(pending)}] {item["key"]} ({time.time() - t0:.2f}s)', flush=True)

    print(f'Done in {time.time() - t_start:.1f}s', flush=True)


if __name__ == '__main__':
    main()
