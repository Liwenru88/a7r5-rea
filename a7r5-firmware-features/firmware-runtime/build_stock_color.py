"""通过原有共享选择器构建原厂 FL2／FL3 与 C1–C6，不含 24 槽运行时。"""
import argparse
import importlib.util
from hashlib import sha256
from pathlib import Path
import sys

from stock400 import AP_SHA, CP_SHA

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'a7r5-desktop/scripts'))
import feature_builder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fl23', action='store_true')
    parser.add_argument('--factory-six', action='store_true')
    args = parser.parse_args()
    if not (args.fl23 or args.factory_six):
        parser.error('需要至少一个色彩模块')
    ap = (args.stock / feature_builder.AP).read_bytes()
    cp = (args.stock / feature_builder.CP).read_bytes()
    if (sha256(ap).hexdigest(), sha256(cp).hexdigest()) != (AP_SHA, CP_SHA):
        raise ValueError('原厂色彩组件前像不符')
    options = dict(fl23=args.fl23, looks=args.factory_six, ntsc=False, sound=False)
    args.output.mkdir(mode=0o700)
    (args.output / 'appFw.so').write_bytes(feature_builder.build_ap(ap, options))
    result = feature_builder.build_cp(cp, options)
    if args.fl23:
        source = HERE.parent / 'look-fl2-fl3/raw/native.py'
        spec = importlib.util.spec_from_file_location('stock_raw_looks', source)
        raw_looks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(raw_looks)
        result, _ = raw_looks.apply(result, args.output / 'raw-alternatives',
                                    source_sha256=sha256(result).hexdigest())
    (args.output / 'cpapp-b.bin').write_bytes(result)


if __name__ == '__main__':
    main()
