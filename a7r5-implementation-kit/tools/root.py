"""新的一次性root脚本适配；底层部署与认证复用已实机验证的引擎。"""
import json
from pathlib import Path
import plistlib
import re
import subprocess
import time
import uuid

from .common import BASE, fresh, regular, save, seal, sha

SOURCE = BASE / 'payload/root_once.c'
LIMIT = 32768


def config(run, script, seconds, root='/tmp/jiritsu', preload='/etc/ld.so.preload', gate='/proc/self/cmdline'):
    if not re.fullmatch('[0-9a-f]{32}', run) or not 1 <= seconds <= 300:
        raise ValueError('会话或超时范围无效')
    prefix = root + '/a7r5-' + run
    strings = {'RUN_ID': run, 'STATE_PATH': prefix + '.state', 'OUTPUT_PATH': prefix + '.output',
        'ARM_BYTES': prefix + '.so\n', 'PRELOAD_PATH': preload, 'GATE_PATH': gate, 'TASK_SCRIPT': script}
    return '\n'.join('#define ' + key + ' ' + json.dumps(value, ensure_ascii=True)
        for key, value in strings.items()) + f'\n#define TASK_SECONDS {seconds}U\n#define OUTPUT_LIMIT {LIMIT}U\n'


def prepare_root(destination, script_file, seconds=60):
    from system_dump.bundle import CLANG, LINKER, LIBC
    from system_dump.environment import static_payload_check
    raw = regular(script_file).read_bytes()
    if not 1 <= len(raw) <= 8192 or b'\0' in raw or b'\r' in raw:
        raise ValueError('脚本须为1至8192字节、无NUL或CR的UTF-8文本')
    script = raw.decode('utf-8', errors='strict')
    if not 1 <= seconds <= 300:
        raise ValueError('任务超时须在1至300秒')
    syntax = subprocess.run(['/bin/sh', '-n'], input=raw, capture_output=True, timeout=10)
    if syntax.returncode:
        raise ValueError('shell语法检查失败：' + syntax.stderr.decode(errors='replace'))
    directory = fresh(destination)
    run = uuid.uuid4().hex
    (directory / 'task.sh').write_bytes(raw)
    (directory / 'root_config.h').write_text(config(run, script, seconds))
    (directory / 'root_once.c').write_bytes(SOURCE.read_bytes())
    payload = directory / 'a7r5_root.arm64.so'
    commands = [[str(CLANG), '--target=aarch64-linux-gnu', '-ffreestanding', '-fPIC', '-fno-builtin',
        '-fno-stack-protector', '-fvisibility=hidden', '-O2', '-Wall', '-Wextra', '-Werror',
        '-I', str(directory), '-c', str(SOURCE), '-o', str(directory / 'root.o')],
        [str(LINKER), '-shared', '-z', 'now', '-z', 'max-page-size=65536', '--no-undefined',
         '--build-id=sha1', str(directory / 'root.o'), str(LIBC), '-o', str(payload)]]
    records = []
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        records.append({'argv': command, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            save(directory / 'build-failure.json', records)
            raise ValueError('载荷构建失败，停止，见build-failure.json')
    save(directory / 'build-log.json', records)
    checked = static_payload_check(payload, sha(payload))
    save(directory / 'payload-check.json', checked)
    (directory / 'preload-arm.bin').write_bytes(f'/tmp/jiritsu/a7r5-{run}.so\n'.encode())
    (directory / 'preload-neutral.bin').write_bytes(b'\n' * 512)
    return seal(directory, {'kind': 'root', 'run_id': run, 'task_seconds': seconds, 'output_limit': LIMIT,
        'task_sha256': sha(directory / 'task.sh'), 'payload_sha256': sha(payload),
        'risk_statement': '认证/START、固定载荷及预加载写入、一次DEBUG，以root执行本次封存脚本；脚本可修改相机。只接受精确512换行基线；中和不等于原样恢复，不自动清理研究文件；异常不重试、不能保证终止内核阻塞或逃逸后台任务。'})


def snapshot():
    result = subprocess.run(['/usr/sbin/ioreg', '-a', '-l', '-r', '-c', 'IOUSBHostDevice'],
                            check=True, capture_output=True, timeout=15)
    found = {}
    def visit(node):
        if node.get('IOObjectClass') == 'IOUSBHostDevice' and node.get('idVendor') == 0x054c:
            found[node.get('IORegistryEntryID', id(node))] = node
        for child in node.get('IORegistryEntryChildren', []):
            visit(child)
    for node in plistlib.loads(result.stdout):
        visit(node)
    devices = []
    for node in found.values():
        classes, media = set(), []
        def collect(item):
            name = item.get('IOObjectClass', '')
            if 'MassStorage' in name:
                classes.add(name)
            if 'BSD Name' in item:
                media.append({'whole': bool(item.get('Whole')), 'bytes': item.get('Size'),
                              'device': item['BSD Name']})
            for child in item.get('IORegistryEntryChildren', []):
                collect(child)
        collect(node)
        devices.append({'vid': node['idVendor'], 'pid': node.get('idProduct'),
            'location_id': node.get('locationID'), 'model': node.get('USB Product Name'),
            'driver_classes': sorted(classes), 'media': media})
    return devices


def normal(devices):
    if len(devices) != 1:
        raise ValueError('须唯一识别Sony相机')
    value = devices[0]
    if (value['vid'], value['pid'], value['location_id'], value['model']) != (0x054c, 0x0e0a, 0x01100000, 'ILCE-7RM5'):
        raise ValueError('不是已验证端口的A7R5普通USB身份')
    if not value['driver_classes'] or not any(m['whole'] for m in value['media']):
        raise ValueError('存储驱动或媒体尚未恢复')
    return value


class RootOperation:
    def __init__(self, operation, payload, channel_factory=None):
        self.operation, self.payload, self.channel_factory = operation, payload, channel_factory
        self.safe_to_stop = True

    def __call__(self, driver, output, log, report):
        from system_dump.restricted import Deployment, RestrictedChannel, neutral, MAX_ARTIFACT
        from system_dump.session import FileResultError
        run = self.operation['run_id']
        prefix = '/tmp/jiritsu/a7r5-' + run
        writes = {prefix + '.so': (self.payload,), '/etc/ld.so.preload': ((prefix + '.so\n').encode(), neutral)}
        reads = {prefix + '.so': MAX_ARTIFACT, '/etc/ld.so.preload': 4096, '/version.txt': 4096,
                 prefix + '.state': 512, prefix + '.output': LIMIT}
        class ExactNeutral(RestrictedChannel):
            baseline = False
            def read(self, path, limit):
                raw = super().read(path, limit)
                if path == '/etc/ld.so.preload' and not self.baseline:
                    if raw != neutral:
                        raise PermissionError('只接受精确512换行基线，不覆盖未知内容')
                    self.baseline = True
                return raw
        channel = (self.channel_factory or ExactNeutral)(driver, writes, reads, log)
        deploy = Deployment(channel, run, self.payload, output, False)
        try:
            deploy.arm()
            self.safe_to_stop = False
            deploy.trigger()
            deadline = time.monotonic() + self.operation['task_seconds'] + 20
            while time.monotonic() < deadline:
                try:
                    raw = channel.read(prefix + '.state', 512)
                except FileResultError as exc:
                    if exc.result != 0x10000006:
                        raise
                    time.sleep(0.2)
                    continue
                match = re.fullmatch(rb'A7R5-ROOT-1 ([0-9a-f]{32}) (RUNNING|DONE|FAILED|TIMEOUT) ([0-9]+) uid=([0-9]+) euid=([0-9]+) bytes=(-?[0-9]+)\n', raw)
                if not match or match[1].decode() != run or (match[4], match[5]) != (b'0', b'0'):
                    raise ValueError('旧会话、非root或不完整状态')
                log('root_state', raw_hex=raw.hex())
                (output / 'worker-last-state.txt').write_bytes(raw)
                if match[2] in (b'FAILED', b'TIMEOUT'):
                    raise RuntimeError('root任务失败或超时；不自动STOP')
                if match[2] == b'DONE':
                    size = int(match[6])
                    if not 0 <= size < LIMIT:
                        raise ValueError('输出大小超限或不完整')
                    (output / 'done-before.txt').write_bytes(raw)
                    data = channel.read(prefix + '.output', LIMIT)
                    if len(data) != size or channel.read('/etc/ld.so.preload', 4096) != neutral:
                        raise ValueError('输出长度或预加载中和不符')
                    if channel.read(prefix + '.state', 512) != raw:
                        raise ValueError('读取输出期间状态变化')
                    (output / 'done-after.txt').write_bytes(raw)
                    (output / 'shell-output.bin').write_bytes(data)
                    report.update(root_uid=0, root_euid=0, shell_exit_code=int(match[3]),
                        root_task_done=True, preload_neutral_verified=True,
                        shell_output_bytes=size, shell_output_sha256=sha(output / 'shell-output.bin'))
                    self.safe_to_stop = True
                    break
                time.sleep(0.2)
            else:
                raise TimeoutError('root任务未返回完整终态，不自动STOP')
        finally:
            if not deploy.state['debug_attempted'] and not deploy.safe_to_stop and channel.usable:
                try:
                    deploy.disarm_before_debug()
                except Exception as exc:
                    log('pre_debug_disarm_failed', message=str(exc))
            if not deploy.state['debug_attempted']:
                self.safe_to_stop = deploy.safe_to_stop
            report.update(camera_file_write_commands_sent=bool(deploy.state.get('payload_write_attempted')),
                preload_written=bool(deploy.state.get('arm_write_attempted')),
                debug_commands_sent=deploy.state['debug_attempted'], deployment_state=deploy.state,
                automatic_service_exit_permitted=self.safe_to_stop)


def execute_root(directory, operation):
    from system_dump.session import run_session
    before = normal(snapshot())
    output = directory / 'result'
    task = RootOperation(operation, regular(directory / 'a7r5_root.arm64.so').read_bytes())
    # 固定端口在主机检查和实际部署前分别核对。
    class Bound:
        @property
        def safe_to_stop(self):
            return task.safe_to_stop
        def __call__(self, driver, *args):
            ports = tuple(driver.device.port_numbers or ())
            location = (driver.device.bus << 24) | sum(p << (20 - 4*i) for i, p in enumerate(ports))
            if not ports or location != 0x01100000:
                raise ValueError('实际服务设备物理端口变化')
            return task(driver, *args)
    report = run_session(output, 'libusb', _operation=Bound())
    try:
        after = normal(snapshot())
        shape = lambda item: sorted((m['whole'], m['bytes']) for m in item['media'])
        recovered = shape(before) == shape(after)
        save(output / 'host-recovery.json', {'before': before, 'after': after, 'media_matches': recovered})
    except Exception as exc:
        recovered = False
        save(output / 'host-recovery.json', {'error': f'{type(exc).__name__}: {exc}'})
    report['execution_succeeded'] = bool(report.get('root_task_done') and report.get('shell_exit_code') == 0
        and report.get('preload_neutral_verified') and report.get('ordinary_identity_restored')
        and recovered and not report.get('failure'))
    report['screen_confirmation_pending'] = True
    report['research_residue_cleaned'] = False
    save(output / 'kit-result.json', report)
    return report
