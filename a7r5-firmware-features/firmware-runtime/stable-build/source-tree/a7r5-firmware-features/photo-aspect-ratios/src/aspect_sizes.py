"""从本地十档整数表派生各格式共用的六档编码尺寸，防止表间漂移。"""
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
FULL_SIZES = ((9504, 6336), (6240, 4160), (4752, 3168))
RATIOS = tuple((int(p), int(q)) for p, q in re.findall(
    r'\{(\d+),\s*(\d+)\}', (HERE / 'geometry.c').read_text().split('};', 1)[0]))
if len(RATIOS) != 10:
    raise ValueError('十档比例表不完整')


def crop(id, full):
    sw, sh = full
    p, q = RATIOS[id]
    if sw * q >= sh * p:
        height = sh & ~7
        width = min(((height * p + q * 8) // (q * 16)) * 16, sw & ~15)
    else:
        width = sw & ~15
        height = min(((width * q + p * 4) // (p * 8)) * 8, sh & ~7)
    return width, height


SIZES = tuple((id, *crop(id, full)) for id in range(4, 10) for full in FULL_SIZES)
SCENES = tuple(crop(id, (1616, 1080)) for id in range(4, 10))
THUMBNAILS = tuple(crop(id, (320, 212)) for id in range(4, 10))
# 此表已通过原厂完整 JPEG 写头和 Exif getter 回放逐项核对。
NATIVE_CLASSES = ((0, 0), (0, 0), (1, 5), (0, 0), (1, 6), (1, 9))
PIXEL_LABELS = tuple(f'{(w * h + 50000) // 100000 / 10:.1f}M' for _, w, h in SIZES)


def generate(work):
    def pairs(values):
        return '{' + ','.join('{' + ','.join(map(str, row)) + '}' for row in values) + '}'
    metadata = [(w, h, *NATIVE_CLASSES[id - 4]) for id, w, h in SIZES]
    header = ('/* 根据本地十档表生成；构建时同时供 AVCAM/MPR 使用。 */\n'
              '#define R5_CUSTOM_SIZE_COUNT 18\n'
              '#define R5_CUSTOM_SIZE_PAIRS ' + pairs((w, h) for _, w, h in SIZES) + '\n'
              '#define R5_CUSTOM_METADATA_ROWS ' + pairs(metadata) + '\n'
              '#define R5_SCENE_PAIRS ' + pairs(SCENES) + '\n'
              '#define R5_THUMBNAIL_PAIRS ' + pairs(THUMBNAILS) + '\n')
    (work / 'aspect_sizes.h').write_text(header)
    (work / 'aspect_pairs.inc').write_text('\n'.join(f'.word {w}, {h}' for _, w, h in SIZES) + '\n')
    (work / 'aspect_scenes.inc').write_text('\n'.join(f'.word {w}, {h}' for w, h in SCENES) + '\n')
    (work / 'aspect_badges.inc').write_text('\n'.join(
        f'.word {w}, {h}, {0x02001ef0 + id - 4}' for id, w, h in SIZES) + '\n')
    (work / 'aspect_pixels.inc').write_text('\n'.join(
        f'.word {w}, {h}, {0x02001f00 + i}' for i, (_, w, h) in enumerate(SIZES)) + '\n')
    return header
