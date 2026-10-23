"""稳定只读描述符上的按文件ext2提取；不生成、复制或校验整张SD分区镜像。"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from .common import fresh, regular, save, sha

METADATA = ('parts', 'mounts', 'devices', 'topology', 'sources')


def dumps(fd, remote, destination, maximum, log):
    from system_dump.images import E2FS
    if not re.fullmatch(r'/(?:A7R5_CARD_ID|a7r5-[0-9a-f]{32}/[A-Za-z0-9_.]+)', remote):
        raise ValueError('拒绝固定会话目录之外的路径')
    if any(c in str(destination) for c in '\n\r"\\') or destination.exists() or destination.is_symlink():
        raise ValueError('debugfs输出路径不安全或已存在')
    source = '/dev/fd/' + str(fd)
    info = subprocess.run([str(E2FS / 'debugfs'), '-R', 'stat ' + remote, source],
                          pass_fds=(fd,), capture_output=True, text=True, timeout=60)
    size = re.search(r'\bSize:\s*(\d+)', info.stdout)
    log('debugfs_stat', remote=remote, exit_code=info.returncode, stdout=info.stdout, stderr=info.stderr)
    if info.returncode or 'Type: regular' not in info.stdout or not size or int(size[1]) > maximum:
        raise ValueError('ext2文件缺失、类型或长度超限：' + remote)
    expected = int(size[1])
    # 不传-w；只继承已核对、以O_RDONLY打开的固定源描述符，不根据disk名字重新选盘。
    result = subprocess.run([str(E2FS / 'debugfs'), '-R', f'dump {remote} "{destination}"', source],
                            pass_fds=(fd,), capture_output=True, text=True, timeout=3600)
    log('debugfs_dump', remote=remote, exit_code=result.returncode, stderr=result.stderr)
    if result.returncode or regular(destination).stat().st_size != expected:
        raise ValueError('debugfs读取失败或实际产物长度不符：' + remote)
    return expected


def hash_both(path):
    md5, sha256 = hashlib.md5(), hashlib.sha256()
    with regular(path).open('rb') as handle:
        while block := handle.read(8 << 20):
            md5.update(block)
            sha256.update(block)
    return md5.hexdigest(), sha256.hexdigest()


def extract(fd, expected, output, log=lambda *a, **k: None, recheck=lambda: None):
    from system_dump.core import validate_inventory
    from verify_current_dump import project
    output = fresh(output)
    audit, images = output / 'audit', output / 'images'
    audit.mkdir(mode=0o700)
    images.mkdir(mode=0o700)
    folder = '/a7r5-' + expected['run_id']
    requests = [('A7R5_CARD_ID', '/A7R5_CARD_ID', 256),
                ('inventory.json', folder + '/inventory.json', 1 << 20),
                ('COMPLETE', folder + '/COMPLETE', 256),
                ('checksums.md5', folder + '/checksums.md5', 65536),
                *[(name + '.txt', folder + '/' + name + '.txt', 65536) for name in METADATA]]
    for name, remote, maximum in requests:
        recheck()
        dumps(fd, remote, audit / name, maximum, log)
    if (audit / 'A7R5_CARD_ID').read_bytes() != expected['card_marker'].encode():
        raise ValueError('卡标记不符')
    if (audit / 'COMPLETE').read_bytes() != expected['expected_complete'].encode():
        raise ValueError('COMPLETE与本次独立主机会话不符')
    inventory = validate_inventory(json.loads((audit / 'inventory.json').read_bytes()))
    if project(inventory) != project(expected['inventory']):
        raise ValueError('卡内inventory与主机独立盘点不同')
    for name in METADATA:
        if sha(audit / (name + '.txt')) != expected['metadata_sha256'][name]:
            raise ValueError('盘点资料与主机会话不同：' + name)
    hashes = {}
    for row in (audit / 'checksums.md5').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{32})\s+\*?([A-Za-z0-9_.]+)', row)
        if not match or match[2] in hashes:
            raise ValueError('卡内MD5清单无效或重复')
        hashes[match[2]] = match[1]
    if set(hashes) != {p['image'] for p in inventory['partitions']}:
        raise ValueError('MD5与本次所选模式的独立盘点集合不一致')
    results = []
    for item in inventory['partitions']:
        recheck()
        temporary = images / (item['image'] + '.partial')
        dumps(fd, folder + '/' + item['image'], temporary, item['bytes'], log)
        if temporary.stat().st_size != item['bytes']:
            raise ValueError('镜像长度与独立盘点不符：' + item['image'])
        md5, digest = hash_both(temporary)
        if md5 != hashes[item['image']]:
            raise ValueError('镜像MD5不符：' + item['image'])
        # 不覆盖任何旧镜像；只删除本入口新建的同字节临时名字。
        os.link(temporary, images / item['image'], follow_symlinks=False)
        temporary.unlink()
        results.append({**item, 'md5': md5, 'sha256': digest})
        log('image_verified', image=item['image'], bytes=item['bytes'], md5=md5, sha256=digest)
    recheck()
    result = {'schema': 'a7r5-selective-files-1', 'run_id': expected['run_id'], 'images': results,
              'dump_profile': expected.get('dump_profile'),
              'image_count': len(results), 'image_bytes': sum(p['bytes'] for p in results),
              'length_md5_sha256_verified': True, 'complete_verified': True,
              'whole_partition_copied': False, 'whole_partition_sha256_calculated': False,
              'whole_camera_completeness_verified': False, 'ejection_verified': False}
    save(output / 'manifest.json', result)
    return result


def capture(directory, operation, host_factory=None):
    from capture_current_dump import Host, validate_mbr, validate_superblock
    expected = json.loads(regular(directory / 'binding.json').read_bytes())
    if expected['run_id'] != operation['run_id']:
        raise ValueError('读取绑定会话不符')
    output = fresh(operation['output'])
    host = (host_factory or Host)(output, expected)
    state = {'kind': 'collect', 'run_id': expected['run_id'], 'execution_succeeded': False,
             'camera_accessed': False, 'source_write_attempted': False,
             'whole_partition_copied': False, 'whole_partition_sha256_calculated': False}
    def log(event, **fields):
        with (output / 'events.jsonl').open('a') as handle:
            handle.write(json.dumps({'event': event, **fields}, ensure_ascii=False) + '\n')
        if event == 'image_verified':
            print(json.dumps({'event': event, **fields}), flush=True)
    try:
        host.output_space(output, expected['inventory']['total_bytes'] + (1 << 30))
        disk = host.identify()
        host.unmount(disk)
        if host.identify() != disk:
            raise ValueError('卸载后卡身份变化')
        host.partitions(disk)
        whole = host.raw(disk, expected['capacity_bytes'])
        try:
            raw = os.pread(whole[0], 512, 0)
            validate_mbr(raw, expected['mbr_entries'])
            (output / 'source-mbr.bin').write_bytes(raw)
            host.recheck(whole, expected['capacity_bytes'])
        finally:
            os.close(whole[0])
        opened = host.raw(disk + 's2', expected['partition_bytes'])
        try:
            sb = os.pread(opened[0], 1024, 1024)
            validate_superblock(sb, expected)
            (output / 'source-superblock.bin').write_bytes(sb)
            result = extract(opened[0], expected, output / 'verified', log,
                             lambda: host.recheck(opened, expected['partition_bytes']))
            host.recheck(opened, expected['partition_bytes'])
            if os.pread(opened[0], 1024, 1024) != sb or host.identify() != disk:
                raise ValueError('读取过程中超级块或卡身份变化')
            host.partitions(disk)
        finally:
            os.close(opened[0])
        host.eject(disk)
        state.update(execution_succeeded=True, card_ejected=True,
            dump_profile=expected.get('dump_profile'),
            image_count=result['image_count'], image_bytes=result['image_bytes'],
            length_md5_sha256_verified=True, complete_verified=True,
            read_only_media_verified=True, source_open_mode='O_RDONLY',
            source_descriptor_fixed_for_all_file_reads=True,
            hardware_write_blocker_proven=False, os_automount_writes_excluded=False)
        save(output / 'ACCEPTED.json', state)
        return state
    except BaseException as exc:
        state['error'] = f'{type(exc).__name__}: {exc}'
        save(output / 'failure.json', state)
        raise
