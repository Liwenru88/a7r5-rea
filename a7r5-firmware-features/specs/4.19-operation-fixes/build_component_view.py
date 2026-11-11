"""合并现有 NTSC／构图标记形成离线测试组件；不封 DAT、不签名、不连接相机。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'a7r5-firmware-features'))
from core.plan import make_plan, read_json, require
from core.package import apply_rows, local_path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native24', 'capture', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    output = local_path(args.output)
    require(not output.exists(), '拒绝覆盖既有组件现场')
    native = read_json(args.native24 / 'build.json')
    capture = read_json(args.capture / 'build.json')
    require(capture['AP']['source_sha256'] == native['AP_sha256'] and
            capture['CP_aspect']['source_sha256'] == native['CP_sha256'], '拍摄组件来源不符')
    before = (args.capture / 'appFw.so').read_bytes()
    cp = (args.capture / 'cpapp-b.bin').read_bytes()
    require(digest(before) == capture['AP']['target_sha256'] and
            digest(cp) == capture['CP_sha256'], '组件摘要不符')
    plan = make_plan(read_json(ROOT / 'a7r5-firmware-features/presets/full-4.19.json'))
    after = bytes(apply_rows(before, plan['component_patches']['usr/lib/appFw.so'],
                             'usr/lib/appFw.so', factory_six=True))
    patches, start = [], None
    for i, (old, new) in enumerate(zip(before, after, strict=True)):
        if old != new and start is None: start = i
        if start is not None and (old == new or i == len(after) - 1):
            end = i if old == new else i + 1
            patches.append(dict(offset=start, before=before[start:end].hex(), after=after[start:end].hex()))
            start = None
    output.mkdir()
    (output / 'appFw.so').write_bytes(after)
    (output / 'cpapp-b.bin').write_bytes(cp)
    shutil.copyfile(args.capture / 'build.json', output / 'capture-build.json')
    (output / 'upstream-ap').mkdir()
    shutil.copyfile(args.native24 / 'upstream-ap/appFw.so', output / 'upstream-ap/appFw.so')
    (output / 'components/usr/lib').mkdir(parents=True)
    os.link(output / 'appFw.so', output / 'components/usr/lib/appFw.so')
    os.link(output / 'cpapp-b.bin', output / 'components/cpapp-b.bin')
    result = dict(schema='r5-operation-fixes-components/1', installable=False, camera_io=False,
                  native24_build_sha256=digest((args.native24 / 'build.json').read_bytes()),
                  capture_build_sha256=digest((output / 'capture-build.json').read_bytes()),
                  AP=dict(source_sha256=digest(before), target_sha256=digest(after), patches=patches),
                  CP_sha256=digest(cp))
    (output / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('schema', 'installable', 'CP_sha256')}))


if __name__ == '__main__':
    main()
