#!/usr/bin/env python3
"""仅在本机检查、重建或分类固定的一号明文分区，不接入相机。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from filesystems import FatImage, SquashImage, require, sha
from trust_recipe import construct, SOURCE_P1_SHA, TARGET_SHA, PUBLIC_SHA
from sector_plan import make_plan, classify


def safe_path(value):
    path = Path(value).absolute()
    require(not path.is_relative_to('/dev'), '禁止设备路径')
    require(not any(p.is_symlink() for p in (path, *path.parents)), '拒绝符号链接路径')
    return path


def read_regular(value):
    path = safe_path(value)
    require(stat.S_ISREG(path.stat().st_mode), '只接受普通本机文件')
    return path, path.read_bytes()


def fixed_source(value):
    path, raw = read_regular(value)
    require(len(raw) == 25100288 and sha(raw) == SOURCE_P1_SHA, '源镜像不是指定原始前像')
    return path, raw


def write_new(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(sha(path.read_bytes()) == sha(raw), '输出文件回读不符')


def build(source, public_key, output):
    source_path, before = fixed_source(source)
    key_path, public = read_regular(public_key)
    require(len(public) == 451 and sha(public) == PUBLIC_SHA, '不是本次研究配对公钥')
    destination = safe_path(output)
    require(not destination.exists() and destination.parent.is_dir(), '输出必须是父目录已存在的全新目录')
    after, initrd, checksums, facts = construct(before, None, public)
    require(sha(after) == TARGET_SHA, '重建未达到封存目标，拒绝生成材料')
    plan = make_plan(before, after)
    require((plan['changed_bytes'], plan['changed_sectors'], plan['logical_write_bytes']) ==
            (128469, 258, 132096), '差异范围不符')
    inverse = bytearray(after)
    for row in plan['rows']:
        offset = row['offset']
        inverse[offset:offset+512] = before[offset:offset+512]
    require(bytes(inverse) == before, '按旧扇区反向重建失败')
    report = dict(status='OFFLINE_EXACT_CANDIDATE_REBUILT', source_sha256=sha(before),
        target_sha256=sha(after), bytes=len(after), public_key_sha256=sha(public),
        initrd_bytes=len(initrd), initrd_sha256=sha(initrd), p1chksum_ascii=checksums.decode('ascii'),
        filesystems=facts, inverse_reconstruction=True, camera_IO=False, SD_IO=False,
        device_writer_included=False, current_device_state_verified=False,
        full_boot_verified=False, physical_persistence_proven=False,
        inputs=dict(source=str(source_path), public_key=str(key_path)))
    # 生成目标前已经完成全部前像、布局和目标摘要检查；不覆盖已有目录。
    destination.mkdir(mode=0o700)
    try:
        write_new(destination/'candidate.logical.img', after)
        write_new(destination/'VerificationKey.pem', public)
        write_new(destination/'before.sectors.bin', b''.join(before[r['offset']:r['offset']+512] for r in plan['rows']))
        write_new(destination/'after.sectors.bin', b''.join(after[r['offset']:r['offset']+512] for r in plan['rows']))
        write_new(destination/'write-plan.json', (json.dumps(plan, ensure_ascii=False, indent=2)+'\n').encode())
        write_new(destination/'rebuild.json', (json.dumps(report, ensure_ascii=False, indent=2)+'\n').encode())
    except OSError:
        # 保留失败输出供检查，不删除或自动重新生成；此目录不得用于部署。
        print('本机输出中断；保留目录，不得据此部署：'+str(destination), file=sys.stderr)
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    rebuild = commands.add_parser('build', help='从精确原件和既有公钥重建本机候选')
    rebuild.add_argument('--source', required=True)
    rebuild.add_argument('--public-key', required=True)
    rebuild.add_argument('--output', required=True)
    inspect = commands.add_parser('inspect', help='只检查已知原像或候选的容器')
    inspect.add_argument('--image', required=True)
    recovery = commands.add_parser('classify', help='只读分类本机现场镜像，不修复')
    recovery.add_argument('--source', required=True)
    recovery.add_argument('--candidate', required=True)
    recovery.add_argument('--observed', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == 'build':
            result = build(args.source, args.public_key, args.output)
        elif args.command == 'inspect':
            path, raw = read_regular(args.image)
            require(len(raw)==25100288 and sha(raw) in (SOURCE_P1_SHA,TARGET_SHA), '不是封存原像或候选')
            fat=FatImage(raw); sq=SquashImage(fat.read('/boot/initrd.img'))
            result=dict(image=str(path), bytes=len(raw), sha256=sha(raw), FAT_entries=len(fat.entries),
                SquashFS_nodes=len(sq.nodes), key_sha256=sha(sq.read('/etc/VerificationKey.pem')),
                p1chksum_ascii=fat.read('/p1chksum').decode('ascii'), camera_IO=False)
        else:
            _, before=fixed_source(args.source); _, after=read_regular(args.candidate)
            require(sha(after)==TARGET_SHA and len(after)==len(before), '候选不匹配')
            _, observed=read_regular(args.observed)
            result=classify(observed,before,after,make_plan(before,after)['rows'])
            result.update(camera_IO=False,write_performed=False)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except (OSError, ValueError, KeyError) as error:
        print('停止；本轮未接入相机：'+str(error),file=sys.stderr); return 2


if __name__ == '__main__':
    raise SystemExit(main())
