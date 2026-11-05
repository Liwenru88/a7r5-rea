"""从固定整合版 CP 原入口启动，定位调度与通知链的实际边界。"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time

from app_paths import open_vm_lock
from cp_boot_state import export_boot_state
from cp_native_probe import prepare_tomco, qmp_command, research_binary
from media_candidate import extract
from native_vm import NativeVM, sandbox_profile
from runtime_manifest import verified_libraries

import environment as env


def clock_fixture(cp, mode):
    """从固定 CP 配置表读取实验档位，禁止将其视为上电值。"""
    if mode not in range(4):
        raise ValueError('时钟实验档位必须为 0 到 3')
    # 原 0x1a05fa 以表 0xcd3930 为配置来源；成对档位的字节相同。
    row = (4, 0, 6, 2)[mode]
    source, divisor, flag = struct.unpack_from('<3I', cp, 0xcd3930 - 0x108000 + row * 12)
    if source != mode or divisor > 0x3fffff or flag not in (0, 1):
        raise ValueError('CP 时钟档位字段不符')
    return dict(table='0xcd3930', row=row, source=source,
                config=divisor | (flag << 31), silicon_reset_value_verified=False)


def observe(manifest, board, milliseconds, dump_task_ram=False, clock_mode=None):
    if not 50 <= milliseconds <= 5000:
        raise ValueError('观察窗口必须为 50 到 5000 毫秒')
    inputs = type('Candidate', (), {'manifest_path': manifest})()
    files = env.MenuVM.runtime_inputs(inputs)
    binary, model = research_binary(board)
    seed = extract(files['initrd'], ['cp/cpapp-b.bin', 'cp/tomco.txt', 'seed-backup.bin'])
    cp = seed['cp/cpapp-b.bin']
    backup = seed['seed-backup.bin']
    if hashlib.sha256(cp).hexdigest() != env.CP_SHA:
        raise ValueError('整合版 CP 固定身份不符')
    fixture = clock_fixture(cp, clock_mode) if clock_mode is not None else None
    if hashlib.sha256(backup).hexdigest() != 'f0281f9513fd247d1b32f2c7b6c6e6122788b097db41cad0bb61ed6b05495f37':
        raise ValueError('整合版模拟备份身份不符')
    offset = (sum(struct.unpack_from('<2I', backup, 0x18)) + 0xfff) & ~0xfff
    if backup[12:16] != b'BK4\0' or backup[offset+12:offset+16] != b'BK4\0':
        raise ValueError('整合版模拟备份双表布局不符')
    tomco = prepare_tomco(seed['cp/tomco.txt'], without_watchdog=True)
    vm = NativeVM('native24-cp-boot')
    result = dict(status='observing', CP_sha256=env.CP_SHA,
                  model_sha256=model['binary_sha256'], manifest_sha256=env.digest(manifest),
                  model_sources=model['model_sources'], board_sha256=model['board_sha256'],
                  observer_sha256=env.digest(Path(__file__)),
                  tomco_sha256=hashlib.sha256(tomco).hexdigest(), virtual_watchdog_disabled=True,
                  clock_fixture=fixture, AP_connected=False, camera_io=False)
    print(vm.out, flush=True)
    try:
        vm.lock = open_vm_lock()
        fcntl.flock(vm.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        vm.control = Path(tempfile.mkdtemp(prefix='a7r5-cp24-', dir='/private/tmp'))
        payloads = [('cpapp-b.bin', cp, 0x108000), ('tomco.txt', tomco, 0x100000),
                    ('backup.bin', backup, 0x4000000)]
        for name, raw, _ in payloads:
            (vm.out/name).write_bytes(raw)
        profile = vm.out/'native.sb'
        profile.write_text(sandbox_profile(binary, *(vm.out/name for name, _, _ in payloads),
                                          vm.out, vm.control, libraries=verified_libraries()))
        trace = vm.out/'instruction-trace.log'
        command = ['/usr/bin/sandbox-exec', '-f', str(profile), str(binary),
                   '-machine', 'a7r5-cp-boot', '-cpu', 'cortex-a35,aarch64=off,has_el2=off,has_el3=off',
                   '-smp', '4', '-accel', 'tcg', '-m', '128M', '-nodefaults',
                   '-display', 'none', '-monitor', 'none', '-serial', 'stdio', '-nic', 'none',
                   '-no-reboot', '-S', '-qmp', f'unix:{vm.control}/qmp.sock,server=on,wait=off',
                   '-d', 'in_asm,int,guest_errors,unimp', '-dfilter', '0x108000+0x1100000',
                   '-D', str(trace)]
        for name, _, address in payloads:
            command += ['-device', f'loader,file={vm.out/name},addr={address:#x},force-raw=on']
        if fixture is not None:
            for address, key in ((0xf54101b8, 'source'), (0xf54101bc, 'config')):
                command += ['-device', f'loader,addr={address:#x},data={fixture[key]:#x},data-len=4']
        for index in range(4):
            command += ['-device', f'loader,addr=0x108000,cpu-num={index}']
        env.save(vm.out/'native-command.json', command)
        vm.log = vm.console.open('wb')
        vm.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=vm.log,
                                      stderr=subprocess.STDOUT, start_new_session=True,
                                      env=dict(PATH='/usr/bin:/bin', HOME=str(vm.control),
                                               TMPDIR=str(vm.control), LC_ALL='C'))
        deadline = time.monotonic()+5
        while not (vm.control/'qmp.sock').exists():
            if vm.process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('QMP 未就绪')
            time.sleep(.01)
        qmp_command(vm, {'execute':'cont'})
        deadline = time.monotonic()+milliseconds/1000
        reason = 'observation_window'
        while time.monotonic() < deadline:
            if vm.process.poll() is not None:
                raise RuntimeError('CP QEMU 提前退出')
            size = trace.stat().st_size
            if size > 16*1024*1024:
                reason = 'trace_budget'
                break
            with trace.open('rb') as stream:
                stream.seek(max(0, size-65536))
                if b'[Data Abort]' in stream.read():
                    reason = 'data_abort'
                    break
            time.sleep(.005)
        qmp_command(vm, {'execute':'stop'})
        export_boot_state(vm, qmp_command, 4)
        if dump_task_ram:
            result['task_ram'] = []
            # 日志与调度监控区来自固定 TOMCO 的 klog/tmon 配置。
            for address, size, name in ((0xe0000, 0x20000, 'cp-klog-ram.bin'),
                                        (0x1c00000, 0x1400000, 'cp-task-ram.bin'),
                                        (0x3400000, 0x200000, 'cp-tmon-ram.bin')):
                path = vm.out/name
                qmp_command(vm, {'execute':'pmemsave', 'arguments':{
                    'val':address, 'size':size, 'filename':str(path)}})
                if path.is_symlink() or path.stat().st_size != size:
                    raise ValueError('CP 任务内存快照不完整')
                result['task_ram'].append(dict(address=address, bytes=size, file=name, sha256=env.digest(path)))
        log = trace.read_text(errors='replace')
        fault = re.search(r'with DFSR (0x[0-9a-f]+) DFAR (0x[0-9a-f]+)', log)
        runtime = (vm.out/'cp-runtime-01500000.bin').read_bytes()
        read_word = lambda address: struct.unpack_from('<I', runtime, address-0x1500000)[0]
        result['native_state'] = dict(
            configuration_group=read_word(0x195e9dc),
            per_core_contexts=[read_word(0x19e391c+4*n) for n in range(4)],
            cross_domain_callback=read_word(0x193eb08), ap_peer_ready=read_word(0x193ec10),
            image_parameter_root=read_word(0x165d758),
            receiver_entry_translated='0x00496018:' in log,
            imaging_receiver_entry_translated='0x0044104c:' in log,
            notification_producer_entry_translated='0x0033cd7c:' in log,
            IRQ_entries=log.count('Taking exception 5 [IRQ]'))
        result.update(status='boot_observation_only', stop_reason=reason,
                      first_data_abort=dict(DFSR=fault[1], DFAR=fault[2]) if fault else None,
                      trace_sha256=env.digest(trace))
    except Exception as error:
        result.update(status='observation_failed', error=str(error))
        raise
    finally:
        result['exit'] = vm.close()
        env.save(vm.out/'result.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--cp-qemu', type=Path, required=True)
    parser.add_argument('--observe-ms', type=int, default=2000)
    parser.add_argument('--dump-task-ram', action='store_true', help='另保存固定低地址的 CP 任务内存，只读')
    parser.add_argument('--clock-mode', type=int, choices=range(4), help='使用原厂运行时表的实验档位')
    args = parser.parse_args()
    print(json.dumps(observe(args.manifest.resolve(), args.cp_qemu, args.observe_ms,
                             args.dump_task_ram, args.clock_mode), indent=2))
