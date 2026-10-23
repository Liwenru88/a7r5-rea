"""本次A7R5转存的普通镜像验收入口；没有原始卡读取或相机操作入口。"""
from pathlib import Path
import argparse
import hashlib
import json
import uuid

from system_dump.core import validate_inventory
from system_dump.images import _dump, extract_run, read_ext2_superblock, regular_file

ROOT = Path(__file__).resolve().parents[1]
RUN = '48b8aa793b7e411e926fadd4b275737e'
LIVE = ROOT / 'mac/system_dump/evidence/live-path-gate-dump-20261018-01'
METADATA = ('parts', 'mounts', 'devices', 'topology', 'sources')
FIELDS = ('schema', 'model', 'firmware_expected', 'views', 'partitions', 'total_bytes')


def sha(path):
    return hashlib.sha256(regular_file(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def project(inventory):
    validate_inventory(inventory)
    return {key: inventory[key] for key in FIELDS}


def binding():
    """只从已封存的实机证据和卡收据构造预期，不从待验卡内清单推导。"""
    hashes = json.loads(regular_file(LIVE / 'evidence-hashes.json').read_bytes())['files']
    files = ['final-verification.json', 'executed-bundle.json',
             'raw-session/run-mmcb-dump/inventory-expected.json',
             *['raw-session/run-mmcb-dump/' + name + '.txt' for name in METADATA]]
    for name in files:
        if sha(LIVE / name) != hashes[name]:
            raise ValueError('本次实机证据摘要变化：' + name)
    final = json.loads((LIVE / 'final-verification.json').read_bytes())
    bundle = json.loads((LIVE / 'executed-bundle.json').read_bytes())
    inventory = project(json.loads((LIVE / files[2]).read_bytes()))
    if (final['run_id'] != RUN or bundle['run_id'] != RUN or final['worker_phase'] != 'DONE'
            or final['worker_code'] != 0 or final['screen_report'] != 'normal'
            or final['full_attempt_and_recovery_checklist_complete'] is not True
            or len(inventory['partitions']) != 37 or inventory['total_bytes'] != 5691539456):
        raise ValueError('本次完成、恢复或37项盘点证据不符')
    receipt_file = ROOT / 'mac/system_dump/evidence/card-format-20261018-01/card-ready.json'
    if sha(receipt_file) != bundle['prepared_card_receipt_sha256']:
        raise ValueError('卡收据与已执行包不符')
    receipt = json.loads(receipt_file.read_bytes())
    if (receipt['ext2_uuid'] != bundle['card_uuid'] or receipt['card_marker'] != bundle['card_marker']
            or receipt['partitions'][1]['bytes'] != bundle['card_partition_bytes']):
        raise ValueError('卡几何或标记与已执行包不符')
    return {'schema': 'a7r5-readback-binding-1', 'run_id': RUN, 'inventory': inventory,
            'expected_complete': f'A7R5-DUMP-1 {RUN} 37 5691539456\n',
            'capacity_bytes': receipt['capacity_bytes'], 'sector_bytes': 512,
            'partition_bytes': receipt['partitions'][1]['bytes'],
            'partition_offset': receipt['partitions'][1]['start_lba'] * 512,
            'card_uuid': receipt['ext2_uuid'], 'card_marker': receipt['card_marker'] + '\n',
            'card_identity': receipt['card_identity'], 'mbr_entries': receipt['partitions'],
            'exfat_uuid': receipt['exfat_volume_uuid'],
            'metadata_sha256': {name: hashes['raw-session/run-mmcb-dump/' + name + '.txt'] for name in METADATA},
            'expected_md5_values_known': False, 'raw_card_access_authorized': False,
            'blank_seed_image_sha256_is_not_expected_dump_sha256': True}


def fresh_directory(path):
    path = Path(path).absolute()
    if path.resolve().is_relative_to('/dev') or path.is_symlink():
        raise ValueError('输出必须为新的普通目录')
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    return path


def prepare(destination):
    value = binding()
    output = fresh_directory(destination)
    save(output / 'binding.json', value)
    (output / 'EXPECTED_COMPLETE.bin').write_bytes(value['expected_complete'].encode())
    (output / 'expected-images.tsv').write_text('image\texpected_bytes\tview\tactual_md5\n' + ''.join(
        f"{p['image']}\t{p['bytes']}\t{p['view']}\tUNREAD\n" for p in value['inventory']['partitions']))
    save(output / 'expected-inventory.json', value['inventory'])
    return value


def check_superblock(image, expected):
    read_ext2_superblock(image)
    with regular_file(image).open('rb') as handle:
        handle.seek(1024)
        block = handle.read(1024)
    exponent = int.from_bytes(block[24:28], 'little')
    features = tuple(int.from_bytes(block[off:off+4], 'little') for off in (92, 96, 100))
    if exponent != 2 or features != (0, 2, 3) or int.from_bytes(block[88:90], 'little') != 128:
        raise ValueError('ext2块大小、特性或inode大小与已执行载荷的识卡条件不符')
    block_size = 1024 << exponent
    size = block_size * int.from_bytes(block[4:8], 'little')
    if (regular_file(image).stat().st_size != expected['partition_bytes'] or size != expected['partition_bytes']
            or block[104:120] != uuid.UUID(expected['card_uuid']).bytes
            or int.from_bytes(block[58:60], 'little') != 1):
        raise ValueError('分区镜像长度、UUID、容量或干净卸载标志不符；不自动修复')
    return {'uuid': expected['card_uuid'], 'block_bytes': block_size, 'bytes': size, 'clean': True}


def verify_capture_receipt(path, expected):
    value = json.loads(regular_file(path).read_bytes())
    if (value.get('schema') != 'a7r5-readonly-capture-1' or value.get('run_id') != RUN
            or value.get('status') != 'captured' or value.get('source_open_mode') != 'O_RDONLY'
            or value.get('source_write_attempted') is not False or value.get('read_only_media_verified') is not True
            or value.get('serial') != expected['card_identity']['spcardreader_card_serialnumber']
            or value.get('partition_bytes') != expected['partition_bytes']
            or value.get('partition_offset') != expected['partition_offset']
            or value.get('card_uuid') != expected['card_uuid']
            or value.get('bytes_copied') != expected['partition_bytes']):
        raise ValueError('采集收据的身份、会话、长度或只读条件不符')
    digest = value.get('stream_sha256')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('采集流SHA-256无效')
    return value


def verify_image(image, destination, capture_receipt=None):
    expected = binding()
    image = regular_file(image)
    capture = verify_capture_receipt(capture_receipt, expected) if capture_receipt is not None else None
    # 先验证普通镜像身份，设备节点和错误镜像不创建验收输出。
    superblock = check_superblock(image, expected)
    identity = image.stat()
    output = fresh_directory(destination)
    audit = output / 'audit'
    audit.mkdir(mode=0o700)
    try:
        folder = '/a7r5-' + RUN
        requests = [('A7R5_CARD_ID', '/A7R5_CARD_ID', 256),
                    ('inventory.json', folder + '/inventory.json', 1 << 20),
                    ('COMPLETE', folder + '/COMPLETE', 256),
                    ('checksums.md5', folder + '/checksums.md5', 65536),
                    *[(name + '.txt', folder + '/' + name + '.txt', 65536) for name in METADATA]]
        for name, remote, maximum in requests:
            target = audit / name
            _dump(image, remote, target, maximum)
            if target.stat().st_size > maximum:
                raise ValueError('元数据实际长度超过上限：' + name)
        if (audit / 'A7R5_CARD_ID').read_bytes() != expected['card_marker'].encode():
            raise ValueError('卡标记不符')
        actual = json.loads((audit / 'inventory.json').read_bytes())
        # JSON规范化比较区分false和0，且不让卡内清单扩大允许的镜像集合。
        if (set(actual) != set(FIELDS) or json.dumps(project(actual), sort_keys=True)
                != json.dumps(expected['inventory'], sort_keys=True)):
            raise ValueError('卡内清单与本次保存的源盘点不符')
        if (audit / 'COMPLETE').read_bytes() != expected['expected_complete'].encode():
            raise ValueError('COMPLETE与本次会话、数量或总长度不符')
        for name in METADATA:
            if sha(audit / (name + '.txt')) != expected['metadata_sha256'][name]:
                raise ValueError('卡内盘点与本次保存证据不符：' + name)
        # 复用已有长度、MD5、重复/多余摘要及partial保留逻辑，仅接收普通镜像。
        transfer = extract_run(image, output / 'images', RUN)
        if capture is not None and transfer['source_sha256'] != capture['stream_sha256']:
            raise ValueError('本机分区镜像SHA-256与采集流收据不符')
        after = image.stat()
        if (identity.st_dev, identity.st_ino, identity.st_size, identity.st_mtime_ns, identity.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('验收期间本机镜像发生变化')
        result = {'schema': 'a7r5-bound-readback-1', 'run_id': RUN, 'status': 'verified',
                  'inventory_count': len(expected['inventory']['partitions']),
                  'inventory_total_bytes': expected['inventory']['total_bytes'], 'source_image': str(image),
                  'source_sha256': transfer['source_sha256'], 'superblock': superblock,
                  'complete_verified': True, 'saved_inventory_match': True, 'metadata_match': True,
                  'all_image_lengths_and_md5_verified': True, 'images': transfer['images'],
                  'capture_receipt_checked': capture is not None,
                  'capture_receipt_sha256': sha(capture_receipt) if capture is not None else None,
                  'source_card_hardware_identity_checked_by_this_tool': False,
                  'whole_camera_completeness_verified': False, 'raw_card_accessed': False,
                  'limitations': ['MD5一致证明与卡上记录一致，不证明相机读取时的快照一致性或隐藏区域覆盖。',
                                  '此入口不采集原始卡，硬件身份及采集过程须另有收据。']}
        save(output / 'verification.json', result)
        return result
    except Exception as exc:
        save(output / 'failure.json', {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}',
                                      'bound_verification_completed': False, 'raw_card_accessed': False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare', help='仅从保存证据导出本次预期清单')
    p.add_argument('--output', required=True, type=Path)
    p = sub.add_parser('verify-image', help='只验收普通ext2镜像，拒绝设备节点')
    p.add_argument('--image', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--capture-receipt', type=Path, help='核对未来独立只读采集入口生成的收据')
    args = parser.parse_args()
    result = prepare(args.output) if args.action == 'prepare' else verify_image(args.image, args.output, args.capture_receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
