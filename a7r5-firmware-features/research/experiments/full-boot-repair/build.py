"""完整离线试修包构建器；无串口、USB、刷写或重启入口。"""

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DAT_SHA = 'd486853533711a282c5e0794f6e98931608c1d2c581e3b25cd70da8b48ce5503'
WBI_SHA = 'eac727efd7af2142ddd9b8ae22387614eaaaba9dc9f04ce0434bf8e7c766d693'
AVCAM_SHA = '23fb43cb2e5d79aad19414d375c9bb6df97ef3042ecb696e8424243e64ff55bc'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def update_header(raw, updater_bytes):
    if len(raw) != 512 or raw[:8] != b'UDTRFIRM' or updater_bytes <= 0 or updater_bytes % 4096:
        raise ValueError('升级头或更新器长度无效')
    result = bytearray(raw)
    result[32:34] = b'\x21\x04'
    struct.pack_into('<I', result, 48, 512 + updater_bytes)
    struct.pack_into('<I', result, 72, updater_bytes)
    struct.pack_into('<I', result, 8, zlib.crc32(result[12:]))
    return bytes(result)


def snapshot_fs(raw):
    sys.path.insert(0, str(ROOT / 'a7r5-firmware-features/native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/lib'))
    from fwtool.archive.squashfs import readSquashfs
    return {f.path: (f.mode, f.uid, f.gid, f.mtime, None if f.contents is None else f.contents.read())
            for f in readSquashfs(io.BytesIO(raw))}


def build(source, wbi_reference, output):
    sys.path.insert(0, str(ROOT / 'a7r5-dat-tool'))
    from a7r5dat import tool
    from a7r5dat.codec import decoded_chunks, header_info, verify_signature
    from a7r5dat.fat import FatImage
    from updater_fs import replace_script
    from shell_status import repair_status
    source, wbi_reference = tool.regular(source), tool.regular(wbi_reference)
    output = Path(output).absolute()
    if (not output.resolve().is_relative_to(ROOT / '.local') or output.exists()
            or any(p.is_symlink() for p in (output, *output.parents))):
        raise ValueError('输出必须是 .local 下的全新普通目录')
    source_facts = tool.file_facts(source)
    if source_facts['sha256'] != DAT_SHA:
        raise ValueError('仅支持已核实的 20261112 完整 4.19 包')
    wbi = wbi_reference.read_bytes()
    if sha(wbi) != WBI_SHA or wbi[:4] != b'WBI3':
        raise ValueError('WBI3 必须匹配已恢复启动包的完整镜像')
    output.mkdir(parents=True, mode=0o700)
    tool.save(output / 'INCOMPLETE.json', {'status': 'BUILDING_NOT_VERIFIED', 'camera_io': False})
    public = ROOT / 'a7r5-dat-tool/keys/research-public.pem'
    work = output / 'work'
    tool.unpack(source, work, public)
    original = json.loads((work / 'manifest.json').read_text())
    original_updater = (work / 'format/updater.bin').read_bytes()
    nor_script = (HERE / 'nor_loader_writer.sh').read_bytes()
    before_fs = snapshot_fs(original_updater)
    bodylib = repair_status(before_fs['/bodylib/libupdaterbody.so'][-1])
    updater = replace_script(original_updater, nor_script, bodylib)
    before_fs, after_fs = snapshot_fs(original_updater), snapshot_fs(updater)
    changed_fs = [p for p in before_fs if before_fs[p] != after_fs.get(p)]
    if set(before_fs) != set(after_fs) or set(changed_fs) != {'/bin/nor_loader_writer.sh','/bodylib/libupdaterbody.so'}:
        raise ValueError('更新器内出现非预期文件变化')
    if after_fs['/bin/nor_loader_writer.sh'][-1] != nor_script or any(before_fs[p][:-1] != after_fs[p][:-1] for p in changed_fs):
        raise ValueError('NOR 脚本内容或权限回读不符')
    (output / 'updater.modified.bin').write_bytes(updater)
    (output / 'final-nor_loader_writer.sh').write_bytes(after_fs['/bin/nor_loader_writer.sh'][-1])
    (output / 'final-libupdaterbody.so').write_bytes(after_fs['/bodylib/libupdaterbody.so'][-1])

    prefix_source = HERE.parent / 'boot-prefix-repair/repair.py'
    spec = importlib.util.spec_from_file_location('prefix_repair', prefix_source)
    prefix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prefix)
    cp_path = work / 'components/cpapp-b.bin'
    cp = prefix.repair_cp(cp_path.read_bytes())
    cp_path.write_bytes(cp)

    aspect = ROOT / 'a7r5-firmware-features/photo-aspect-ratios/src'
    sys.path.insert(0, str(aspect))
    from build_avcam import apply_avcam, compile_avcam
    from fat_avcam import replace
    capture = output / 'build-evidence/capture'
    capture.mkdir(parents=True)
    partition_path = work / 'archive/0700_part_image/dev/nflasha3'
    original_partition = partition_path.read_bytes()
    original_avcam = FatImage(original_partition).read('/av-cam.bin')
    if sha(original_avcam) != AVCAM_SHA:
        raise ValueError('AVCAM 4.19 前像不符')
    # 从恢复包中已核实的原厂 AVCAM 重建，避免直接改动未知机器码。
    stock_avcam = ROOT / 'a7r5-fastboot/private/cases/recovered-vs-419-20261114/recovered/nflasha3/av-cam.bin'
    avcam, avcam_proof = apply_avcam(stock_avcam.read_bytes(), compile_avcam(capture))
    if len(avcam) != len(original_avcam):
        raise ValueError('AVCAM 出现非预期长度变化')
    (capture / 'AV-CAM.BIN').write_bytes(avcam)
    tool.save(capture / 'build.json', {'AVCAM': avcam_proof, 'camera_io': False})
    partition, fat_proof = replace(original_partition, avcam)
    partition_path.write_bytes(partition)
    wbi_path = work / 'archive/0700_part_image/dev/nflasha5'
    if wbi_path.read_bytes()[512:] != wbi[512:]:
        raise ValueError('WBI3 替换会改变首扇区之外的快照数据')
    wbi_path.write_bytes(wbi)

    with tempfile.TemporaryDirectory(prefix='assemble-', dir=output) as folder:
        stage = Path(folder)
        files, current, components = tool.collect(work, original, stage)
        header = update_header((work / 'format/header.bin').read_bytes(), len(updater))
        total = original['decryption']['plaintext_bytes'] + len(updater) - len(original_updater)
        header_info(header, total)
        partial = output / 'UNVERIFIED.DAT'
        with tempfile.TemporaryFile(dir=stage) as clear:
            clear.write(header)
            clear.write(updater)
            for row in original['entries']:
                clear.write(tool.decode(row['prefix']))
                if row['name'] in files:
                    with files[row['name']].open('rb') as stream:
                        shutil.copyfileobj(stream, clear, 4 << 20)
            clear.write(tool.decode(original['tail']))
            if clear.tell() != total:
                raise ValueError('升级包明文大小不符')
            key = tool.signing_key(ROOT / 'a7r5-dat-tool/keys/research-signing-private.pem', public)
            tool.encrypt(clear, total, original, key, partial)
            layout, _, _ = verify_signature(partial, public.read_bytes())
            clear.seek(0)
            decoded = 0
            for chunk in decoded_chunks(partial, layout):
                if clear.read(len(chunk)) != chunk:
                    raise ValueError('最终签名包逐帧解密不符')
                decoded += len(chunk)
            if decoded != total or clear.read(1):
                raise ValueError('最终签名包明文长度不符')
    readback = output / 'readback'
    tool.unpack(partial, readback, public)
    final = json.loads((readback / 'manifest.json').read_text())
    expected_changed = {'0700_part_image/dev/nflasha3', '0700_part_image/dev/nflasha5',
                        '0700_part_image/dev/nflasha8', '0701_part_image_sum/part_image.sum'}
    changed = []
    if len(original['entries']) != len(final['entries']):
        raise ValueError('归档成员数量变化')
    for left, right in zip(original['entries'], final['entries']):
        if any(left.get(k) != right.get(k) for k in ('name','type','size','prefix','link')):
            raise ValueError('归档顺序、长度或元数据变化')
        if left != right:
            changed.append(left['name'])
    if set(changed) != expected_changed:
        raise ValueError('归档变化超出 CP、AVCAM、WBI 及校验清单')
    if (readback / 'components/cpapp-b.bin').read_bytes() != cp:
        raise ValueError('CP 最终回读不符')
    final_avcam = FatImage((readback / 'archive/0700_part_image/dev/nflasha3').read_bytes()).read('/av-cam.bin')
    if final_avcam != avcam or (readback / 'archive/0700_part_image/dev/nflasha5').read_bytes() != wbi:
        raise ValueError('AVCAM 或 WBI3 最终回读不符')
    final_updater = (readback / 'format/updater.bin').read_bytes()
    if final_updater != updater or snapshot_fs(final_updater) != after_fs:
        raise ValueError('包内更新器独立回读不符')
    if tool.file_facts(source) != source_facts or sha(wbi_reference.read_bytes()) != WBI_SHA:
        raise ValueError('输入材料在构建期间变化')
    destination = output / 'BODYDATA.DAT'
    os.link(partial, destination)
    destination.chmod(0o600)
    report = {
        'status': 'OFFLINE_PACKAGE_VERIFIED_RUNTIME_TESTS_PENDING', 'version': '4.21',
        'source': source_facts, 'candidate': tool.file_facts(destination),
        'camera_io': False, 'device_boot_verified': False, 'root_cause_proven': False,
        'WBI': {'magic': 'WBI3', 'sha256': sha(wbi), 'CRC32': f'{zlib.crc32(wbi):08x}',
                'complete_known_header_restored': True, 'after_first_512_exact_to_419': True},
        'NOR': {'failure_propagation_fixed': True, 'erase_rounding_fixed': True,
                'script_sha256': sha(nor_script), 'updater_before_bytes': len(original_updater),
                'updater_after_bytes': len(updater), 'unchanged_other_inodes': len(before_fs)-2,
                'shell_errno_masking_fixed': True, 'shell_library_sha256': sha(bodylib),
                'native_kernel_mount_tested': False, 'physical_NOR_tested': False},
        'AVCAM': {'before_sha256': AVCAM_SHA, 'after_sha256': sha(avcam),
                  'changed_bytes': sum(a != b for a, b in zip(original_avcam,avcam)),
                  'slot_argument_fixed': True, 'snapshot_layout_changed_from_419': False,
                  'fat': fat_proof},
        'CP': {'sha256': sha(cp), 'prefix_helper': '0x109200', 'original_logic_preserved': True},
        'changed_archive_members': changed, 'archive_entries': len(final['entries']),
        'signature_verified': True, 'all_frames_verified': True, 'independent_unpack_verified': True,
        'source_hashes': {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in
                          (Path(__file__), HERE/'updater_fs.py', HERE/'shell_status.py', HERE/'nor_loader_writer.sh', prefix_source,
                           aspect/'avcam_views.S', aspect/'build_avcam.py')},
        'unverified': ['机身完整冷启动与跨核缓存','物理 NOR 擦写和读回','真实 JPEG/HEIF/RAW 成片','版本与签名实机准入'],
    }
    recipe = ROOT / 'a7r5-firmware-features/releases/4.19-full-repaired-20261112/R5NATIVE.BIN'
    shutil.copy2(recipe, output / 'R5NATIVE.BIN')
    tool.save(output / 'verification.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dat', type=Path, required=True)
    parser.add_argument('--wbi-reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = build(args.source_dat, args.wbi_reference, args.output)
    print(json.dumps({k: report[k] for k in ('status','version','candidate','WBI','AVCAM')}, ensure_ascii=False, indent=2))
