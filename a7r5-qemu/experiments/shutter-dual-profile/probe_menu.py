"""启动真实QEMU菜单；控制仅接受固定按键和只读状态采集。"""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

from environment import LAB, MenuVM, save
from menu_live import FirmwareMonitor, key_command
from menu_bridge import capture


def source_module():
    path = LAB/'build/menu417-17-oLYPDW/probe_menu.py'
    spec = importlib.util.spec_from_file_location('sound_probe_base', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--scenario', default='valid', choices=('valid',))
    parser.add_argument('--unlock', action='store_true')
    parser.add_argument('--menu-isolation', action='store_true')
    parser.add_argument('--restore', type=Path, default=os.environ.get('R5_SOUND_QEMU_RESTORE'))
    parser.add_argument('--no-card', action='store_true', default=os.environ.get('R5_SOUND_QEMU_NO_CARD')=='1')
    args = parser.parse_args()
    base = source_module()
    vm = MenuVM(args.manifest)
    vm.menu_isolation = args.menu_isolation
    result = {'camera_io': False, 'status': 'STARTING', 'audio_backend': 'fixture', 'actions': []}
    monitor = FirmwareMonitor(vm.console)
    error = None
    print('RUN_DIRECTORY '+str(vm.out), flush=True)
    try:
        vm.start()
        print('KERNEL_READY', flush=True)
        for index, command in enumerate(base.setup_commands()):
            if command == 'insmod /usr/kmod/upm.ko':
                command += ' && /simulation/hold-frequency'
            if 'LD_PRELOAD=' in command:
                vm.command('mkdir -p /usr/data/lut && mknod /dev/nflasha30 b 1 2 && '
                           'dd if=/simulation/native12-lut.fat of=/dev/nflasha30 bs=4096 && '
                           'mount -t vfat /dev/nflasha30 /usr/data/lut', timeout=30)
                if args.restore:
                    restored = json.loads(Path(args.restore).read_text())
                    import hashlib
                    manifest=json.loads(args.manifest.read_text())
                    if manifest.get('restore_files')!={n:hashlib.sha256(base64.b64decode(v,validate=True)).hexdigest() for n,v in restored.items()}:
                        raise ValueError('恢复文件与固定客体清单不符')
                    for name, encoded in restored.items():
                        if not (name in ('R5SOUND.PRO', 'R5SOUND.IDX') or (name.startswith('R5SN_') and name.endswith('.R5S') and len(name)==73)):
                            raise ValueError('恢复文件名称越界')
                        data = base64.b64decode(encoded, validate=True)
                        if len(data)>500000:
                            raise ValueError('恢复文件过大')
                        vm.command('cp /simulation/restore-'+name+' /usr/data/lut/'+name, timeout=20)
                flags = ' A7R5_N12_PENDING_NOTIFY=1 A7R5_N12_E4_SERVICES=1'
                if args.no_card:
                    flags += ' R5_SOUND_NO_CARD=1'
                command = 'export A7R5_N12_LOADING=1 A7R5_INITIAL_PRIVACY_NOTICE=1 A7R5_INPUT_COMPLETIONS=1'+flags+'; '+command
            monitor.check()
            reply = vm.command(command, timeout=45)
            (vm.out/f'setup-{index:02d}.log').write_bytes(reply)
            print('SETUP_COMPLETED '+str(index), flush=True)
        # 保留真实工作线程的时间预算；轮询期间仅驱动已声明的CP传输边界。
        deadline = time.monotonic()+90
        while time.monotonic()<deadline:
            monitor.check()
            vm.pump_loading()
            if b'R5_SOUND_LOG PROFILES_LOAD ' in vm.console.read_bytes():
                break
            time.sleep(.02)
        else:
            raise RuntimeError('声音工作线程未在90秒内完成库读取')
        vm.prime_native_menu()
        _, previous = capture(vm, 'sound-baseline')
        state = vm.loading_state('sound-baseline')
        result['baseline'] = state
        vm.set_native_paused(True)
        print('NATIVE410_REPLY '+json.dumps({'action': 'ready', 'run': str(vm.out), 'frame': previous,
                                            'screen': vm.last_native_screen(), 'sound': state['sound']}, ensure_ascii=False), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            if not isinstance(request, dict) or set(request) != {'action'}:
                raise ValueError('只接受固定action')
            action = request['action']
            monitor.check()
            if action == 'STOP':
                print('NATIVE410_REPLY '+json.dumps({'action': 'STOP', 'stopping': True}), flush=True)
                result['status'] = 'PASS'
                break
            if action in ('UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'MENU', 'C4', 'MODE_M', 'DISP'):
                offset = vm.console.stat().st_size
                vm.command(key_command(action), timeout=30)
                after = max(previous['sequence'], base.completed_with_cp(vm, action, offset))
            elif action == 'SNAPSHOT':
                after = None
            elif action == 'PRIVACY':
                vm.command('touch /tmp/a7r5-request-initial-privacy', timeout=30)
                vm.wait_native_screen(0x1e3)
                after = previous['sequence']
            elif action == 'EXPORT_STORE':
                data = vm.command('/simulation/sound-store-export', timeout=30)
                (vm.out/'storage-export.log').write_bytes(data)
                import re
                exported = {}
                for name, encoded in re.findall(rb'\r?\nR5_SOUND_FILE_BEGIN:([^\r\n]+)\r?\n(.*?)\r?\nR5_SOUND_FILE_END',data,re.S):
                    raw = bytes.fromhex(b''.join(encoded.split()).decode('ascii'))
                    exported[name.decode('ascii')] = base64.b64encode(raw).decode('ascii')
                if len(exported)!=4 or 'R5SOUND.PRO' not in exported or len(base64.b64decode(exported['R5SOUND.PRO']))!=96:
                    raise RuntimeError('虚拟存储导出不完整')
                (vm.out/'exported-files.json').write_text(json.dumps(exported,indent=2)+'\n')
                after = None
            else:
                raise ValueError('未知固定操作 '+str(action))
            vm.command('sleep 0.15', timeout=10)
            name = f'sound-{len(result["actions"]):03d}-{action}'
            _, previous = capture(vm, name, after=after)
            state = vm.loading_state(name)
            row = {'action': action, 'frame': previous, 'screen': vm.last_native_screen(),
                   'png': str(vm.out/(name+'.png')), 'sound': state['sound'], 'mid': state['mid']}
            result['actions'].append(row)
            (vm.out/'sound-actions.json').write_text(json.dumps(result['actions'],ensure_ascii=False,indent=2)+'\n')
            print('NATIVE410_REPLY '+json.dumps(row,ensure_ascii=False), flush=True)
        else:
            raise RuntimeError('控制端关闭前未发送STOP')
    except BaseException as exc:
        error = exc
        result.update(status='FAIL', error=str(exc))
        if vm.process and vm.process.poll() is None:
            try:
                monitor.check()
                evidence = vm.command("/bin/busybox grep 'R5_SOUND' /tmp/menu-load.log; ls -la /usr/data/lut", timeout=15)
                (vm.out/'sound-failure-diagnostic.log').write_bytes(evidence)
            except Exception as diagnostic:
                result['diagnostic_error'] = str(diagnostic)
    finally:
        result['close'] = vm.close()
        result['run'] = str(vm.out)
        save(vm.out/'sound-validation.json', result)
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    if error or result['close'].get('exit_code') != 0:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
