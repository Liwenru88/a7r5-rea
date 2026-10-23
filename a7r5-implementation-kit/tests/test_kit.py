"""普通文件/本机进程验证；不连接相机或原始卡。"""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from tools import common, root, selective, workflows


def fixture_image(tmp_path, fault=None, profile='extended'):
    from tools.profiles import inventory
    expected = inventory(profile)
    for index, item in enumerate(expected['partitions']):
        item['bytes'] = (index + 1) * 512
    expected['total_bytes'] = sum(p['bytes'] for p in expected['partitions'])
    run = '1234abcd' * 4
    marker = '1' * 32 + '\n'
    folder = tmp_path / 'seed' / ('a7r5-' + run)
    folder.mkdir(parents=True)
    md5 = []
    for index, item in enumerate(expected['partitions']):
        data = bytes([index + 1]) * item['bytes']
        md5.append(hashlib.md5(data).hexdigest() + '  ' + item['image'] + '\n')
        if fault == 'md5' and index == 0:
            data = b'Z' * len(data)
        if fault == 'length' and index == 0:
            data = data[:-1]
        (folder / item['image']).write_bytes(data)
    if fault == 'duplicate_hash':
        md5.append(md5[0])
    inventory = copy.deepcopy(expected)
    if fault == 'inventory':
        inventory['partitions'] = inventory['partitions'][1:]
        inventory['total_bytes'] = sum(p['bytes'] for p in inventory['partitions'])
    (folder / 'inventory.json').write_text(json.dumps(inventory))
    (folder / 'checksums.md5').write_text(''.join(md5))
    complete = f"A7R5-DUMP-1 {run} {len(expected['partitions'])} {expected['total_bytes']}\n"
    if fault != 'missing_complete':
        (folder / 'COMPLETE').write_text(complete.replace(run, 'abcd' * 8) if fault == 'old_run' else complete)
    (folder.parent / 'A7R5_CARD_ID').write_text('wrong\n' if fault == 'marker' else marker)
    metadata = {}
    for name in selective.METADATA:
        data = ('synthetic-' + name + '\n').encode()
        metadata[name] = hashlib.sha256(data).hexdigest()
        (folder / (name + '.txt')).write_bytes(b'wrong' if fault == 'metadata' and name == 'sources' else data)
    image = tmp_path / 'ordinary-ext2.img'
    with image.open('xb') as handle:
        handle.truncate(16 << 20)
    from system_dump.images import E2FS
    result = subprocess.run([str(E2FS / 'mke2fs'), '-q', '-F', '-t', 'ext2', '-b', '4096', '-I', '128',
        '-O', 'none,filetype,sparse_super,large_file', '-U', '3319ad38-134e-4944-ac8a-05863becf15c',
        '-d', str(folder.parent), str(image)], capture_output=True)
    assert result.returncode == 0, result.stderr
    binding = {'run_id': run, 'inventory': expected, 'card_marker': marker, 'dump_profile': profile,
        'metadata_sha256': metadata, 'expected_complete': complete}
    return image, binding


@pytest.mark.parametrize('profile,count', [('standard',19),('extended',37)])
def test_selective_extract_selected_files_without_partition_copy_and_source_unchanged(tmp_path, profile, count):
    image, expected = fixture_image(tmp_path, profile=profile)
    before = common.sha(image)
    fd = os.open(image, os.O_RDONLY)
    try:
        result = selective.extract(fd, expected, tmp_path / 'verified')
    finally:
        os.close(fd)
    assert result['image_count'] == count
    assert result['image_bytes'] == expected['inventory']['total_bytes']
    assert result['whole_partition_copied'] is False
    assert result['whole_partition_sha256_calculated'] is False
    assert before == common.sha(image)
    assert not list(tmp_path.rglob('card.ext2.img*'))
    for item in result['images']:
        data = (tmp_path / 'verified/images' / item['image']).read_bytes()
        assert len(data) == item['bytes']
        assert hashlib.md5(data).hexdigest() == item['md5']
        assert hashlib.sha256(data).hexdigest() == item['sha256']


@pytest.mark.parametrize('fault', ['md5', 'length', 'inventory', 'duplicate_hash', 'missing_complete', 'old_run', 'marker', 'metadata'])
def test_selective_refuses_bad_evidence_and_never_accepts_partial(tmp_path, fault):
    image, expected = fixture_image(tmp_path, fault)
    before = common.sha(image)
    fd = os.open(image, os.O_RDONLY)
    try:
        with pytest.raises((ValueError, FileNotFoundError)):
            selective.extract(fd, expected, tmp_path / 'rejected')
    finally:
        os.close(fd)
    assert not (tmp_path / 'rejected/manifest.json').exists()
    assert not list(tmp_path.rglob('ACCEPTED.json'))
    assert common.sha(image) == before


def test_selective_does_not_switch_source_when_regular_path_is_replaced(tmp_path):
    image, expected = fixture_image(tmp_path)
    fd = os.open(image, os.O_RDONLY)
    image.rename(tmp_path / 'original.img')
    image.write_bytes(b'invalid replacement')
    try:
        result = selective.extract(fd, expected, tmp_path / 'fixed-fd')
        assert result['image_count'] == 37
    finally:
        os.close(fd)


@pytest.mark.parametrize('fault', ['gate', 'preload', None, 'nonzero', 'timeout', 'overflow'])
def test_same_root_c_native_gate_execution_exit_timeout_and_output_limit(tmp_path, fault):
    run = '1234abcd' * 4
    script = {'nonzero': 'echo output; echo error >&2; exit 42',
              'timeout': '/bin/sleep 20',
              'overflow': 'while :; do echo abcdefghijklmnopqrstuvwxyz; done'}.get(fault, 'echo output; echo error >&2')
    (tmp_path / 'root_config.h').write_text(root.config(run, script, 1,
        root=str(tmp_path), preload=str(tmp_path / 'preload'), gate=str(tmp_path / 'gate')))
    (tmp_path / 'preload').write_text('foreign' if fault == 'preload' else f'{tmp_path}/a7r5-{run}.so\n')
    (tmp_path / 'gate').write_bytes(b'other\0' if fault == 'gate' else b'/bin/sh\0-c\0/bin/date -s 070421422017.26\0')
    exe = tmp_path / 'root-test'
    result = subprocess.run(['/usr/bin/clang', '-DA7R5_HOST_TEST', '-O1', '-Wall', '-Wextra', '-Werror',
                             '-I', str(tmp_path), str(root.SOURCE), '-o', str(exe)], capture_output=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(exe)], capture_output=True, timeout=5)
    statefile = tmp_path / f'a7r5-{run}.state'
    if fault == 'gate':
        assert result.returncode == 100 and not statefile.exists()
        assert (tmp_path / 'preload').read_text().endswith('.so\n')
        return
    deadline = time.monotonic() + 8
    text = ''
    while time.monotonic() < deadline:
        text = statefile.read_text() if statefile.exists() else ''
        if any((' ' + phase + ' ') in text for phase in ('DONE', 'FAILED', 'TIMEOUT')):
            break
        time.sleep(.03)
    if fault == 'preload':
        assert ' FAILED 92 ' in text
        assert (tmp_path / 'preload').read_text() == 'foreign'
        return
    assert (tmp_path / 'preload').read_bytes() == b'\n' * 512
    if fault == 'timeout':
        assert ' TIMEOUT 85 ' in text
    elif fault == 'overflow':
        assert ' FAILED 83 ' in text
    else:
        assert (' DONE 42 ' if fault == 'nonzero' else ' DONE 0 ') in text
        assert (tmp_path / f'a7r5-{run}.output').read_bytes() == b'output\nerror\n'


def test_real_cross_build_dump_and_root_without_approval(tmp_path):
    dump = workflows.prepare_dump(tmp_path / 'dump')
    value = root.prepare_root(tmp_path / 'root', BASE / 'examples/root-info.sh', 10)
    assert dump['kind'] == 'dump' and value['kind'] == 'root'
    from mmcb_dump_once import load
    assert load(tmp_path / 'dump/bundle')[0]['expected_card_device'] == '/dev/mmcb2'
    for name in ('dump', 'root'):
        operation = tmp_path / name
        assert common.load(operation)['kind'] == name
        with pytest.raises(PermissionError):
            common.execute(operation)
        assert not (operation / 'ATTEMPT_LOCK').exists()
        assert not (operation / 'approval.json').exists()


@pytest.mark.parametrize('fault', ['nul', 'crlf', 'too_large', 'syntax', 'timeout'])
def test_root_prepare_rejects_invalid_tasks_without_building_or_approval(tmp_path, fault):
    raw = {'nul': b'echo \0', 'crlf': b'echo hello\r\n', 'too_large': b'#' * 8193,
           'syntax': b'if then\n', 'timeout': b'echo ok\n'}[fault]
    path = tmp_path / 'task.sh'
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        root.prepare_root(tmp_path / 'never', path, 0 if fault == 'timeout' else 10)
    assert not (tmp_path / 'never').exists()


def test_bound_approval_tampering_and_no_retry(tmp_path):
    op = tmp_path / 'root'
    root.prepare_root(op, BASE / 'examples/root-info.sh', 10)
    with pytest.raises(PermissionError):
        common.approve(op, 'wrong')
    common.approve(op, common.consent_phrase(op))
    assert common.checked_approval(op)['kind'] == 'root'
    (op / 'task.sh').write_text('changed')
    with pytest.raises(ValueError, match='变化'):
        common.checked_approval(op)


def test_attempt_lock_blocks_new_approval_and_execution(tmp_path):
    op = tmp_path / 'root'
    root.prepare_root(op, BASE / 'examples/root-info.sh', 10)
    common.approve(op, common.consent_phrase(op))
    (op / 'ATTEMPT_LOCK').mkdir()
    with pytest.raises(FileExistsError):
        common.checked_approval(op)
    with pytest.raises(FileExistsError):
        common.approve(op, common.consent_phrase(op))


@pytest.mark.parametrize('fault', [None, 'writable', 'eject'])
def test_selective_capture_host_gates_and_only_final_accept_after_ejection(tmp_path, fault):
    from capture_current_dump import validate_whole, READER
    image, expected = fixture_image(tmp_path)
    receipt = json.loads((BASE / 'profiles/prepared-card.json').read_bytes())
    expected.update(capacity_bytes=18 << 20, partition_bytes=16 << 20,
        card_uuid=receipt['ext2_uuid'], exfat_uuid=receipt['exfat_volume_uuid'],
        mbr_entries=[{'type': '0x7', 'start_lba': 2048, 'sectors': 2048, 'bytes': 1 << 20},
                     {'type': '0x83', 'start_lba': 4096, 'sectors': 32768, 'bytes': 16 << 20}])
    mbr = bytearray(512)
    mbr[510:] = b'\x55\xaa'
    for i, entry in enumerate(expected['mbr_entries']):
        struct.pack_into('<B3sB3sII', mbr, 446 + 16*i, 0, b'\0'*3, int(entry['type'], 16),
                         b'\0'*3, entry['start_lba'], entry['sectors'])
    whole = tmp_path / 'ordinary-whole-metadata.bin'
    whole.write_bytes(mbr)
    operation = tmp_path / 'operation'
    operation.mkdir()
    common.save(operation / 'binding.json', expected)
    calls = []
    class Host:
        def __init__(self, output, binding):
            pass
        def output_space(self, output, required):
            assert required == expected['inventory']['total_bytes'] + (1 << 30)
        def identify(self):
            validate_whole({'WholeDisk': True, 'VirtualOrPhysical': 'Physical', 'BusProtocol': 'Secure Digital',
                'Removable': True, 'WritableMedia': fault == 'writable', 'DeviceBlockSize': 512,
                'Size': expected['capacity_bytes'], 'DeviceTreePath': READER}, expected)
            return 'disk4'
        def unmount(self, disk):
            calls.append('unmount')
        def partitions(self, disk):
            pass
        def raw(self, disk, length):
            calls.append('raw')
            return os.open(image if disk.endswith('s2') else whole, os.O_RDONLY), None, None
        def recheck(self, opened, length):
            assert stat.S_ISREG(os.fstat(opened[0]).st_mode)
        def eject(self, disk):
            if fault == 'eject':
                raise RuntimeError('synthetic eject failure')
            calls.append('eject')
    import stat
    operation_value = {'run_id': expected['run_id'], 'output': str(operation / 'result')}
    if fault:
        with pytest.raises((ValueError, RuntimeError)):
            selective.capture(operation, operation_value, Host)
        assert not (operation / 'result/ACCEPTED.json').exists()
        if fault == 'writable':
            assert not calls
    else:
        result = selective.capture(operation, operation_value, Host)
        assert result['execution_succeeded'] is True
        assert result['card_ejected'] is True and 'eject' in calls
        assert not list(operation.rglob('card.ext2.img*'))


def test_collect_binding_requires_separate_screen_and_host_confirmation(tmp_path, monkeypatch):
    operation = tmp_path / 'dump'
    dump = workflows.prepare_dump(operation)
    output = operation / 'result'
    output.mkdir()
    common.save(output / 'summary.json', {'worker_done_receipt': True, 'card_unmounted_verified': True,
                                        'preload_neutral_verified': True})
    with pytest.raises(FileNotFoundError):
        workflows.binding_from_dump(operation)
    common.save(output / 'host-confirmation.json', {'run_id': dump['run_id'],
        'normal_usb_and_media': True, 'screen_report': 'normal'})
    # 成功转存的真实主机盘点作为输入；不把卡内可伪造清单当作唯一预期。
    for name in ('parts', 'mounts', 'devices', 'topology', 'sources'):
        (output / (name + '.txt')).write_bytes((BASE / 'historical' / (name + '.txt')).read_bytes())
    from tools.profiles import inventory
    selected = inventory('standard')
    common.save(output / 'inventory-expected.json', selected)
    (output / 'sources.txt').write_text(''.join(f"{p['device']} {p['major']} {p['minor']} {p['bytes']}\n"
                                              for p in selected['partitions']))
    binding = workflows.binding_from_dump(operation)
    assert len(binding['inventory']['partitions']) == 19 and binding['inventory']['total_bytes'] == 1872691200
    with pytest.raises(PermissionError):
        workflows.prepare_collect(operation, tmp_path / 'not-safe', 'wrong')
    result = workflows.prepare_collect(operation, tmp_path / 'collect', 'CAMERA-OFF-CARD-LOCKED-MEDIA-EJECTED')
    assert result['kind'] == 'collect'
    with pytest.raises(PermissionError):
        common.execute(tmp_path / 'collect')


@pytest.mark.parametrize('fault', ['preload', 'output', 'state', 'debug', 'uid', None, 'exit'])
def test_root_protocol_real_header_channel_once_debug_and_stop_gate(tmp_path, fault, monkeypatch):
    from system_dump.usb_adapter import HEADER
    from system_dump.preflight import wire_path
    run = '1234abcd' * 4
    prefix = '/tmp/jiritsu/a7r5-' + run
    content = b'root-output\n'
    state = f'A7R5-ROOT-1 {run} DONE {42 if fault == "exit" else 0} uid={1 if fault == "uid" else 0} euid=0 bytes={len(content)}\n'.encode()
    # 使用真实已保存的版本对照，生产RestrictedChannel解析所有请求和响应。
    version = (BASE / 'profiles/version.bin').read_bytes()
    files = {wire_path('/version.txt'): version,
        wire_path('/etc/ld.so.preload'): b'' if fault == 'preload' else b'\n' * 512,
        wire_path(prefix + '.state'): state, wire_path(prefix + '.output'): content[:-1] if fault == 'output' else content}
    class Driver:
        def __init__(self):
            self.queue, self.debugs, self.states = [], 0, 0
        def write(self, raw):
            size, function, sequence, *_ = HEADER.unpack_from(raw)
            body = raw[HEADER.size:]
            assert size == len(body)
            group, command = struct.unpack_from('<HH', body)
            assert group == 0x1001
            data = b''
            if command == 15:
                self.selected = body[5:-1]
            elif command == 16:
                files[self.selected] = body[7:]
            elif command == 17:
                data = files[self.selected]
                if self.selected == wire_path(prefix + '.state'):
                    self.states += 1
                    if fault == 'state' and self.states > 1:
                        data = data.replace(run.encode(), b'a' * 32)
            elif command == 5:
                self.debugs += 1
                files[wire_path('/etc/ld.so.preload')] = b'\n' * 512
                if fault == 'debug':
                    raise OSError('simulated transfer failure')
            else:
                raise AssertionError(command)
            data = b'\0' * 4 + data
            self.queue += [HEADER.pack(len(data), function, sequence, 3, 0, 0, 0), data]
        def read(self, n):
            raw = self.queue[0][:n]
            self.queue[0] = self.queue[0][n:]
            if not self.queue[0]:
                self.queue.pop(0)
            return raw
    driver = Driver()
    operation = root.RootOperation({'run_id': run, 'task_seconds': 1}, b'payload')
    report = {}
    if fault in ('preload', 'output', 'state', 'debug', 'uid'):
        with pytest.raises((ValueError, PermissionError, OSError)):
            operation(driver, tmp_path, lambda *a, **k: None, report)
        assert operation.safe_to_stop is (fault == 'preload')
    else:
        operation(driver, tmp_path, lambda *a, **k: None, report)
        assert operation.safe_to_stop is True and report['root_task_done'] is True
        assert report['shell_exit_code'] == (42 if fault == 'exit' else 0)
    assert driver.debugs == (0 if fault == 'preload' else 1)
