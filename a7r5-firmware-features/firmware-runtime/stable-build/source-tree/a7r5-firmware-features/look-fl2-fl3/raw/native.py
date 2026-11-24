"""离线扩展 R5 原生 RAW 外观目录；不改 RAW 感光数据或持久设置。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
FEATURES = HERE.parents[1]
BASE = 0x108000
RX = 0xada014
END = 0xada098
GUARDS = (
    # RAW 的八组 CC1／矩阵映射须已支持 FL2／FL3；不能只扩目录数量。
    (0xbef220, 284, 'b9013cd36f5c1c01087ffe9c914285b68e168fc5d9424f954c5ad06fa1a0e4f0'),
    (0xad9ff6, 18, '88bedf70cd7998b99bebb36ebdba46dac328c9fa0414244625e732272f2a8e26'),
    (0xada00e, 138, '7f99309d9387111824c8f091211ef8ac47d18cc6da40f12682672a82cacf09e1'),
    (0xadd162, 1230, '76442ad34fa0b19c42c68b45a0789a1b43465e32dcaeb7bea9e11eabfcd56d57'),
    (0xade854, 4, '4fc1d45054854e705405ef5f8476159d16297585afa69c9e603d84e92177b0a7'),
    (0xca0990, 68, '5331925af0a0fd6e7395a39e4d8057307f0122288fc150c1a52af06900e85e14'),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apply(raw, output, *, source_sha256):
    """父构建器提供已验证组件身份；每处原生代码另核完整范围。"""
    if len(raw) != 17617008 or digest(raw) != source_sha256:
        raise ValueError('RAW 备选目录 CP 前像身份不符')
    for va, size, pin in GUARDS:
        if digest(raw[va-BASE:va-BASE+size]) != pin:
            raise ValueError(f'RAW 原生接口前像不符：{va:#x}')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    compiler = '/opt/homebrew/opt/llvm/bin/clang'
    obj = output / 'raw_alternatives.o'
    command = [compiler, '--target=arm-none-eabi', '-mthumb', '-march=armv7-a',
               '-mfloat-abi=soft', '-c', str(HERE / 'raw_alternatives.S'), '-o', str(obj)]
    subprocess.run(command, check=True, capture_output=True)
    library = FEATURES / 'photo-electronic-shutter-sound/bindings/upstream/src/lib'
    operations = FEATURES / 'firmware-runtime/dependencies/native12-combined/upstream/firmware/r5/src/lib'
    sys.path[:0] = [str(library), str(operations)]
    try:
        from thumb_link import link
        from thumb_ops import branch
        code, symbols = link([obj], base=RX, externals={'r5_raw_original_construct': 0xadd163})
        if RX + len(code) > END:
            raise ValueError('RAW helper 超出已退役映射函数的原执行区')
        edits = [
            (0xada00e, branch(0xada00e, symbols['r5_raw_mapping'] & ~1, False), 'mapping-entry'),
            (RX, code, 'bounded-native-helpers'),
            (0xad9ff6, branch(0xad9ff6, symbols['r5_raw_quantity'] & ~1, False), 'quantity-entry'),
            (0xade854, branch(0xade854, symbols['r5_raw_construct'] & ~1, True), 'constructor-call'),
            (0xca09b8, struct.pack('<II', 19, 20), 'alternative-gamma'),
        ]
    finally:
        sys.path.remove(str(library))
        sys.path.remove(str(operations))
    result = bytearray(raw)
    patches = []
    for va, data, reason in edits:
        at = va - BASE
        if any(max(at, p['offset']) < min(at+len(data), p['offset']+len(bytes.fromhex(p['after']))) for p in patches):
            raise ValueError('RAW 补丁范围重叠')
        patches.append(dict(offset=at, before=raw[at:at+len(data)].hex(), after=data.hex(), reason=reason))
        result[at:at+len(data)] = data
    reverse = bytearray(result)
    for patch in reversed(patches):
        data = bytes.fromhex(patch['before'])
        reverse[patch['offset']:patch['offset']+len(data)] = data
    if reverse != raw:
        raise ValueError('RAW 补丁逆还原不符')
    report = dict(schema='r5-raw-alternative-looks/1', model='ILCE-7RM5',
                  source_sha256=source_sha256, target_sha256=digest(result), patches=patches,
                  code_bytes=len(code), code_range=[RX, RX+len(code)], symbols=symbols,
                  config_va=0x198780c, count_before=10, count_after=12, root_tags=175,
                  child_tags=114, child_stride=3110, child_region_end=0x1162+12*3110,
                  next_region=0xaf50, new_BSS_bytes=0, new_heap_bytes=0,
                  inverse_exact=True, original_constructor_preserved=True,
                  persistent_backup_modified=False, sensor_path_modified=False,
                  requires_existing_FL23_color_routes=True,
                  camera_io=False, device_acceptance_verified=False,
                  sources={p.name:digest(p.read_bytes()) for p in (Path(__file__), HERE / 'raw_alternatives.S')},
                  compiler_argv=command)
    if report['child_region_end'] > report['next_region']:
        raise ValueError('RAW 子目录超出原生预留区')
    (output / 'build.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return bytes(result), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--expected-source', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data, report = apply(args.input.read_bytes(), args.output, source_sha256=args.expected_source)
    with (args.output / 'cpapp-b.NONINSTALLABLE.bin').open('xb') as stream:
        stream.write(data)
    print(json.dumps({k:report[k] for k in ('source_sha256', 'target_sha256', 'code_bytes', 'camera_io')}))


if __name__ == '__main__':
    main()
