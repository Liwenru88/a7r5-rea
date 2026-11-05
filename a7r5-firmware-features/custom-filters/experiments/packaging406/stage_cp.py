"""从严格内存计划生成全新CP/FAT候选；不签名、不修改源工作区或创建DAT。"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import stat
import struct
import sys
import zlib

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'a7r5-dat-tool/a7r5dat').is_dir())
sys.path.insert(0, str(ROOT/'a7r5-dat-tool'))
from a7r5dat.fat import FatImage

CP_SHA = '18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
IMAGE_SHA = '69a1466ee3bdedaa84ec1ebafcd94004841cef8c8ba0d344f5e182548b74a8b2'
SUM_SHA = 'b141f3b045dfb2d73486b27842778b558ddedfe82b03b7b45879633be72f06cb'
CP_BYTES = 17617008
IMAGE_BYTES = 24531968
MEMORY = Path(__file__).resolve().parent/'cp_carve406/memory_plan.py'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path):
    p = Path(path).absolute()
    require('..' not in p.parts and not p.is_relative_to('/dev'), '输入路径不安全')
    require(all(not a.is_symlink() for a in (p, *p.parents)), '拒绝符号链接路径')
    require(stat.S_ISREG(p.stat().st_mode), '输入必须是普通文件')
    return p


def snapshot(path):
    p = regular(path)
    before = p.stat()
    raw = p.read_bytes()
    after = p.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after), '读取期间源文件变化')
    return p, raw, identity(after)


def unchanged(saved):
    p, raw, identity = saved
    current = snapshot(p)
    require(current[2] == identity and current[1] == raw, '封装期间源文件变化')


def independent_cp(image):
    """独立按BPB、短目录项和FAT12链提取，不使用写入器的entry/extents。"""
    require(len(image) >= 512 and image[510:512] == b'\x55\xaa' and
            image[54:62] == b'FAT12   ', '独立读取：FAT12头错误')
    sector = struct.unpack_from('<H', image, 11)[0]
    unit = image[13]*sector
    reserved = struct.unpack_from('<H', image, 14)[0]
    copies = image[16]
    roots = struct.unpack_from('<H', image, 17)[0]
    fat_size = struct.unpack_from('<H', image, 22)[0]*sector
    require(sector == 512 and unit > 0 and copies == 2, '独立读取：不支持的BPB')
    fat_at = reserved*sector
    fat = image[fat_at:fat_at+fat_size]
    require(len(fat) == fat_size and fat == image[fat_at+fat_size:fat_at+2*fat_size], '两份FAT不一致')
    root_at = fat_at + copies*fat_size
    data_at = root_at + ((roots*32+sector-1)//sector)*sector
    rows = [image[i:i+32] for i in range(root_at, root_at+roots*32, 32)]
    entries = [e for e in rows if len(e) == 32 and e[:11] == b'CPAPP-B BIN' and e[11] == 0x20]
    require(len(entries) == 1, '独立读取：CP短目录项不唯一')
    e = entries[0]
    size = struct.unpack_from('<I', e, 28)[0]
    cluster = struct.unpack_from('<H', e, 26)[0]
    result = bytearray()
    extents, seen = [], set()
    while 2 <= cluster < 0xff8:
        require(cluster not in seen, '独立读取：簇链循环')
        seen.add(cluster)
        at = data_at+(cluster-2)*unit
        require(at >= data_at and at+unit <= len(image), '独立读取：簇越界')
        take = min(unit, max(0, size-len(result)))
        require(take > 0, '独立读取：文件尾后多余簇')
        extents.append((at, take))
        result.extend(image[at:at+take])
        i = cluster*3//2
        require(i+2 <= len(fat), '独立读取：FAT越界')
        pair = int.from_bytes(fat[i:i+2], 'little')
        cluster = (pair >> 4) if cluster & 1 else pair & 0xfff
    require(cluster >= 0xff8 and len(result) == size, '独立读取：链长或结束符错误')
    return bytes(result), extents


def patch_image(original, candidate):
    require(len(original) == IMAGE_BYTES and sha(original) == IMAGE_SHA, 'CP分区不是修改版4.06原像')
    before, extents = independent_cp(original)
    require(len(before) == CP_BYTES and sha(before) == CP_SHA, 'CP文件原像不符')
    require(len(candidate) == len(before), 'CP必须定长')
    fs = FatImage(original)
    out = bytearray(original)
    used = fs.patch(out, '/cpapp-b.bin', candidate)
    require(used == extents, '独立簇映射与写入器不一致')
    at = 0
    for start, length in sorted(extents):
        require(start >= at and original[at:start] == out[at:start], '无关分区字节变化')
        at = start+length
    require(original[at:] == out[at:], '分区尾变化')
    result = bytes(out)
    require(independent_cp(result)[0] == candidate, '独立CP提取回读失败')
    after = FatImage(result)
    require(after.entries == fs.entries, 'FAT目录、分配或元数据变化')
    for name in fs.entries:
        if name != '/cpapp-b.bin' and not fs.entries[name]['is_directory']:
            require(fs.read(name) == after.read(name), '无关CP文件变化：'+name)
    reverse = bytearray(result)
    FatImage(result).patch(reverse, '/cpapp-b.bin', before)
    require(bytes(reverse) == original, '完整FAT逆还原失败')
    return result, len(fs.entries), extents


def update_sum(original, image):
    require(sha(original) == SUM_SHA, '原分区校验清单不符')
    rows = original.splitlines(keepends=True)
    found = 0
    for i, line in enumerate(rows):
        fields = line.rstrip(b'\n').split(b',')
        if len(fields) >= 11 and fields[10] == b'dev/nflasha8':
            require(fields[0] == b'0' and fields[1] == b'90d1ab75' and fields[2] == b'01765400', '原CP校验记录错误')
            fields[1] = f'{zlib.crc32(image):08x}'.encode('ascii')
            rows[i] = b','.join(fields)+(b'\n' if line.endswith(b'\n') else b'')
            found += 1
    require(found == 1, 'CP校验记录不唯一')
    result = b''.join(rows)
    require(len(result) == len(original), '校验清单长度变化')
    return result


def memory_api():
    spec = importlib.util.spec_from_file_location('stage_cp_strict_memory', MEMORY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stage(source_image, source_sum, build, output):
    # 先核原像、实际ELF及当前源码，不接受传入的任意补丁计划。
    source = snapshot(source_image)
    sums = snapshot(source_sum)
    require(len(source[1]) == IMAGE_BYTES and sha(source[1]) == IMAGE_SHA, 'CP分区不是修改版4.06原像')
    require(sha(sums[1]) == SUM_SHA, '原分区校验清单不符')
    cp, _ = independent_cp(source[1])
    api = memory_api()
    plan = api.create_plan(cp, Path(build).resolve())
    require(plan['native_integration'] is True and plan['capacity_layout_version'] == 'capture-color-22-v1'
            and len(plan['patches']) == 69 and len(plan['native_hooks']) == 51
            and plan['native_contract_bytes'] == 1280, '不是当前完整Capture接入合同')
    candidate = api.transform(cp, plan)
    require(api.transform(candidate, plan, reverse=True) == cp, 'CP内存逆还原失败')
    image, count, extents = patch_image(source[1], candidate)
    new_sum = update_sum(sums[1], image)
    output = Path(output).absolute()
    require('..' not in output.parts and output.is_relative_to(ROOT/'.local') and
            not output.exists() and all(not p.is_symlink() for p in (output, *output.parents)),
            '输出必须是.local下全新非链接目录')
    output.mkdir(parents=True)
    files = {'cpapp-b.bin': candidate, 'nflasha8': image, 'part_image.sum': new_sum}
    for name, raw in files.items():
        with (output/name).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        require((output/name).read_bytes() == raw, '落盘回读失败：'+name)
    # 从已落盘分区重新独立提取，并通过严格计划逆回原CP和全分区。
    require(independent_cp((output/'nflasha8').read_bytes())[0] == (output/'cpapp-b.bin').read_bytes(), '落盘分区回读不符')
    require(api.transform((output/'cpapp-b.bin').read_bytes(), plan, reverse=True) == cp, '落盘CP逆变换失败')
    require(api.create_plan(cp, Path(build).resolve()) == plan, '封装期间构建或源码变化')
    unchanged(source)
    unchanged(sums)
    receipt = dict(schema='a7r5-406-cp-staging/1', status='CP_FAT_STAGED_REVERSED_NOT_INSTALLABLE',
        source_image=str(source[0]), source_image_sha256=IMAGE_SHA, source_cp_sha256=CP_SHA,
        source_sum=str(sums[0]), source_sum_sha256=SUM_SHA,
        target_member='0700_part_image/dev/nflasha8', checksum_member='0701_part_image_sum/part_image.sum',
        cp_path='/cpapp-b.bin', cp_encoding='raw-uncompressed-no-extra-wrapper',
        build=str(Path(build).resolve()), build_receipt_sha256=plan['build_receipt_sha256'],
        memory_plan_sha256=sha(json.dumps(plan, sort_keys=True).encode()),
        files={n:dict(path=str(output/n), bytes=len(r), sha256=sha(r), crc32=f'{zlib.crc32(r):08x}') for n,r in files.items()},
        patch_windows=69, native_hooks=51, native_contract_bytes=1280,
        fat_entries=count, cp_extents=len(extents), independent_cp_readback=True,
        whole_partition_reverse_equal=True, cp_reverse_equal=True, unrelated_files_and_metadata_preserved=True,
        sources_unchanged=True, source_freshness_checked=True, installable_firmware=False,
        DAT_created=False, signed=False, private_key_accessed=False, camera_io=False,
        hardware_simulation=False, target_executed=False, pixel_acceptance=False)
    with (output/'memory-plan.json').open('x') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    with (output/'verification.json').open('x') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('source-image', 'source-sum', 'build', 'output'):
        p.add_argument('--'+arg, type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(stage(args.source_image, args.source_sum, args.build, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
