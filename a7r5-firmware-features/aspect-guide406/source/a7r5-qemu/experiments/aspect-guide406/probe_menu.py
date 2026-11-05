"""完整应用启动探测；失败保留现场，不用合成画面作为菜单结果。"""
import argparse
import json
from pathlib import Path
import sys
import re

from environment import LAB, AspectVM
sys.path.insert(0, str(LAB/'tools'))
from menu_live import FirmwareMonitor
from menu_bridge import capture
from menu_live import key_command
from input_completion import wait_input_completion


def research_loop(vm, initial, result):
    previous = initial
    result['actions'] = []
    def reply(value):
        print('ASPECT406_REPLY '+json.dumps(value, ensure_ascii=False), flush=True)
    reply({'action': 'ready', 'run': str(vm.out), 'frame': previous, 'screen': vm.last_native_screen()})
    for line in sys.stdin:
        request = json.loads(line)
        if not isinstance(request, dict) or set(request) != {'action'}:
            raise ValueError('研究请求只能包含固定 action')
        action = request['action']
        FirmwareMonitor(vm.console).check()
        if action == 'STOP':
            reply({'action': 'STOP', 'stopping': True})
            return
        if action == 'PRIVACY':
            vm.command('touch /tmp/a7r5-request-initial-privacy', timeout=30)
            vm.wait_native_screen(0x1e3)
            after = previous['sequence']
        elif action in ('UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'MENU', 'C4', 'MODE_M', 'DISP'):
            offset = vm.console.stat().st_size
            before = vm.last_native_screen()
            vm.command(key_command(action), timeout=30)
            if action == 'MENU' and before == 0x355:
                vm.wait_native_screen(0x2d6)
                after = previous['sequence']
            else:
                after = max(previous['sequence'], wait_input_completion(vm, action, offset))
        elif action == 'SNAPSHOT':
            after = None
        else:
            raise ValueError('未知研究操作')
        name = 'research-%03d-%s' % (len(result['actions']), action)
        _, previous = capture(vm, name, after=after)
        values = re.findall(rb'OBS A7R5_ASPECT406_STATE ([^\r\n]+)', vm.console.read_bytes())
        row = {'action': action, 'frame': previous, 'screen': vm.last_native_screen(),
               'png': str(vm.out/(name+'.png')), 'model': values[-1].decode() if values else None}
        result['actions'].append(row)
        (vm.out/'research-actions.json').write_text(json.dumps(result['actions'], indent=2)+'\n')
        reply(row)
    raise RuntimeError('研究控制端提前关闭')


def setup_commands():
    return [
        'mount -t tmpfs tmpfs /tmp; mount -t tmpfs tmpfs /setting; mount -t tmpfs tmpfs /tmp_wbshd',
        'mkdir -p /dev/cgroup; mount -t cgroup -o cpuset nodev /dev/cgroup; '
        'for group in cpu0 cpu1 cpu2 cpu3rt cpu0_1 cpu0_1_2 cpu0_1_2_3rt; do '
        'mkdir -p /dev/cgroup/$group; echo 0 > /dev/cgroup/$group/cpuset.mems; echo 0 > /dev/cgroup/$group/cpuset.cpus; done',
        'insmod /kmod/devno.ko',
        'insmod /usr/kmod/osal_utm.ko',
        'insmod /usr/kmod/osal_uipc.ko',
        'insmod /usr/kmod/utimer.ko',
        'cp /seed-backup.bin /setting/Backup.bin; insmod /usr/kmod/backup.ko Backup_load=1 Backup_save=0',
        'insmod /usr/kmod/stream.ko',
        'insmod /usr/kmod/stream2.ko',
        'cp -a /seed-setting/. /setting/; insmod /usr/kmod/osal_ulogio.ko ulogio_initfile=/setting/ulogio.bin',
        'insmod /usr/kmod/dmm.ko DmmConfig=/setting/DmmCfg.bin',
        'insmod /usr/kmod/grm_ma.ko',
        '/simulation/seed-power-on 1',
        'insmod /usr/kmod/upm.ko',
        'insmod /usr/kmod/udate.ko && /simulation/inspect-date-clock && /simulation/seed-date-clock406',
        'insmod /usr/kmod/kikilog.ko',
        'mkdir -p /setting/updater /mnt; cp /simulation/firmware-version.dat4 /setting/updater/dat4; '
        '([ -b /dev/ram1 ] || mknod /dev/ram1 b 1 1) && ln -s /dev/ram1 /dev/nflasha1 && '
        'dd if=/simulation/firmware-identity.fat of=/dev/ram1 bs=4096',
        'cp /simulation/libIMDB-menu-qemu.so /usr/lib/libIMDB.so; export LD_LIBRARY_PATH=/usr/lib:/lib; '
        'export QEMU_NO_CP_UPDATER=1 A7R5_APPLY_MENU=1 A7R5_GUI_TRACE=1 MENU_HEADLESS_OSD=1 MENU_OSD_OBSERVE=1 '
        'QEMU_SOFTWARE_LZ77=1 A7R5_MODEL_TRACE=1 A7R5_SKIP_BT_WRAPPER=1 QEMU_SOFTWARE_GPE=1 QEMU_GPE_RGBA4444=1 '
        'QEMU_CAPID_SERVICE=1 QEMU_SA_ADDRESS_SERVICE=1 QEMU_HDMI_FORMAT_SERVICE=1 QEMU_HDMI_PHOTO_SERVICE=1 '
        'QEMU_DISPLAY_INFO_SERVICE=1 QEMU_DMM_SERVICE=1; '
        "LD_PRELOAD=/simulation/menu-observe-a7r5-baseline.so /usr/bin/bootin.elf 'target=qemu ' dmode=3 > /dev/ttyAMA0 2>&1 & echo A7R5_IM_PID=$!",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--unlock', action='store_true')
    parser.add_argument('--interactive', action='store_true')
    args = parser.parse_args()
    vm = AspectVM(args.manifest)
    result = {'stage': 'original-app-menu', 'status': 'failed', 'camera_io': False,
              'aspect_unlock_requested': args.unlock, 'aspect_unlock_applied': False, 'menu_verified': False,
              'photo_interface_verified': False, 'commands_completed': 0}
    error = None
    try:
        print('RUN_DIRECTORY', vm.out, flush=True)
        vm.start()
        print('KERNEL_READY', flush=True)
        for index, command in enumerate(setup_commands()):
            if args.unlock and 'LD_PRELOAD=' in command:
                command='export A7R5_ASPECT_GUIDE406_UNLOCK=1; '+command
            if args.interactive and 'LD_PRELOAD=' in command:
                command='export A7R5_INITIAL_PRIVACY_NOTICE=1 A7R5_INPUT_COMPLETIONS=1; '+command
            FirmwareMonitor(vm.console).check()
            reply = vm.command(command, timeout=45)
            (vm.out/f'setup-{index:02d}.log').write_bytes(reply)
            result['commands_completed'] = index+1
            print('SETUP_COMPLETED', index, flush=True)
        # 由现有原厂页面初始化流程等待和操作，不直接写菜单或首次设置字段。
        vm.prime_native_menu()
        _, frame = capture(vm, 'aspect406-baseline-menu')
        result['aspect_unlock_applied'] = b'OBS A7R5_ASPECT406_INSTALLED ' in vm.console.read_bytes()
        result.update(status='frame-collected', menu_frame=frame)
        if args.interactive:
            research_loop(vm, frame, result)
    except Exception as exc:
        error = exc
        result['error'] = str(exc)
    finally:
        result['close'] = vm.close()
        result['run_directory'] = str(vm.out)
        (vm.out/'aspect406-menu.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if error is not None or result['close'].get('exit_code') != 0:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
