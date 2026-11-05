"""完整应用启动探测；失败保留现场，不用合成画面作为菜单结果。"""
import argparse
import json
from pathlib import Path
import sys
import re
import time
import hashlib
import socket

from environment import LAB, MenuVM as AspectVM
sys.path.insert(0, str(LAB/'tools'))
from menu_live import FirmwareMonitor
from menu_bridge import capture
from menu_live import key_command
from input_completion import wait_input_completion, completed_sequence


def native_diagnostic(vm):
    return vm.command("/bin/busybox grep -E 'RCV_SITE|SND_MSG_OTHER|TRANSPORT_UNAVAILABLE' /tmp/menu-load.log; "
        'for p in /proc/[0-9]*; do if /bin/busybox grep -q /usr/lib/appFw.so "$p/maps" 2>/dev/null; then '
        'for t in "$p"/task/*; do echo "$t"; cat "$t/comm" "$t/wchan" "$t/syscall"; done; fi; done',timeout=20)


def completed_with_cp(vm,action,offset):
    if not vm.cp_service:return wait_input_completion(vm,action,offset)
    # 生产 UI 的原有20秒有界等待以客体时间计；TCG 下允许更长宿主预算，
    # 不改变客体 CP/E4 门禁，也不把超时视为成功。
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        FirmwareMonitor(vm.console).check();vm.pump_loading()
        try:return completed_sequence(vm.console.read_bytes()[offset:],action)
        except RuntimeError:pass
        if vm.process.poll() is not None:raise RuntimeError('输入完成前QEMU退出')
        time.sleep(.005)
    raise RuntimeError('输入处理／CP服务未在90秒内完成')


def research_loop(vm, initial, result):
    previous = initial
    result['actions'] = []
    def reply(value):
        print('NATIVE410_REPLY '+json.dumps(value, ensure_ascii=False), flush=True)
    reply({'action': 'ready', 'run': str(vm.out), 'frame': previous, 'screen': vm.last_native_screen()})
    for line in sys.stdin:
        request = json.loads(line)
        if not isinstance(request, dict) or set(request) != {'action'}:
            raise ValueError('研究请求只能包含固定 action')
        action = request['action']
        FirmwareMonitor(vm.console).check()
        if action == 'STOP':
            if vm.cp_service and json.loads(vm.manifest_path.read_text()).get('native_ui_trace'):
                evidence=vm.command("/bin/busybox grep '^N12_UI_' /tmp/menu-load.log",timeout=15)
                (vm.out/'native-ui-trace.log').write_bytes(evidence)
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
                after = max(previous['sequence'], completed_with_cp(vm, action, offset))
        elif action == 'SNAPSHOT':
            after = None
        else:
            raise ValueError('未知研究操作')
        if vm.cp_service:
            # 原生处理回执先于软件绘制完成；给客体一次短稳定期，同时服务CP请求。
            vm.command('sleep 0.15',timeout=10)
        name = 'research-%03d-%s' % (len(result['actions']), action)
        _, previous = capture(vm, name, after=after)
        values = re.findall(rb'OBS A7R5_NATIVE410_STATE ([^\r\n]+)', vm.console.read_bytes())
        row = {'action': action, 'frame': previous, 'screen': vm.last_native_screen(),
               'png': str(vm.out/(name+'.png')), 'model': values[-1].decode() if values else None}
        if vm.cp_service:
            state=vm.loading_state(name);row['available_mask']=state['available_mask'];row['selected_filter']=state['selected']
            row['command_state']=state['command_state'];row['native_refresh']=state['native_refresh']
            row['native_E4_inflight']=state['native_E4_inflight'];row['recovery_required']=state['recovery_required']
            row['CP_messages']=len(vm.cp_service.messages)
        result['actions'].append(row)
        (vm.out/'research-actions.json').write_text(json.dumps(result['actions'], indent=2)+'\n')
        reply(row)
    raise RuntimeError('研究控制端提前关闭')


def setup_commands():
    return [
        # 原厂中文字体位于 /tmp/images，挂载空 tmpfs 前保存，之后按原路径恢复。
        'cp -a /tmp/images /simulation/runtime-fonts && mount -t tmpfs tmpfs /tmp && '
        'cp -a /simulation/runtime-fonts /tmp/images && '
        'mount -t tmpfs tmpfs /setting; mount -t tmpfs tmpfs /tmp_wbshd',
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
    parser.add_argument('--menu-isolation',action='store_true',help='仅用原厂MENU进入菜单，不确认触控引导或启动拍摄初始化')
    parser.add_argument('--scenario',choices=('valid','invalid-bin','bad-ack','bad-select-ack'),default='valid')
    args = parser.parse_args()
    vm = AspectVM(args.manifest)
    vm.load_fault=args.scenario
    vm.menu_isolation=args.menu_isolation
    result = {'stage': 'original-app-menu', 'status': 'failed', 'camera_io': False,
              'aspect_unlock_requested': args.unlock, 'aspect_unlock_applied': False, 'menu_verified': False,
              'photo_interface_verified': False, 'commands_completed': 0}
    result['menu_isolation']=args.menu_isolation
    error = None
    try:
        print('RUN_DIRECTORY', vm.out, flush=True)
        vm.start()
        print('KERNEL_READY', flush=True)
        for index, command in enumerate(setup_commands()):
            if command=='insmod /usr/kmod/upm.ko' and json.loads(args.manifest.read_text()).get('native_frequency_lock'):
                command+=' && /simulation/hold-frequency'
            if vm.cp_service and 'LD_PRELOAD=' in command:
                if args.scenario=='invalid-bin':
                    # 客体精简dd没有notrunc；分段复制只改一个字节，保持文件长度。
                    corrupted=vm.command('dd if=/simulation/R5NATIVE.BIN of=/tmp/native12-invalid.bin bs=1 count=160 && '
                        "printf '\\001' >> /tmp/native12-invalid.bin && "
                        'dd if=/simulation/R5NATIVE.BIN bs=1 skip=161 >> /tmp/native12-invalid.bin && '
                        'mv /tmp/native12-invalid.bin /simulation/R5NATIVE.BIN && '
                        '/bin/busybox md5sum /simulation/R5NATIVE.BIN && /bin/busybox wc -c /simulation/R5NATIVE.BIN',timeout=15)
                    (vm.out/'invalid-bin-injection.log').write_bytes(corrupted)
                    damaged=bytearray(vm.loading_inputs['bin'].read_bytes());damaged[160]=1
                    if hashlib.md5(damaged).hexdigest().encode()+b'  /simulation/R5NATIVE.BIN' not in corrupted or not re.search(rb'\b58976\s+/simulation/R5NATIVE.BIN',corrupted):
                        raise RuntimeError('损坏BIN注入摘要／长度不符')
                mounted=vm.command('mkdir -p /usr/data/lut && mknod /dev/nflasha30 b 1 2 && '
                    'dd if=/simulation/native12-lut.fat of=/dev/nflasha30 bs=4096 && '
                    'mount -t vfat /dev/nflasha30 /usr/data/lut && echo A7R5_N12_LUT_READY',timeout=30)
                (vm.out/'lut-mount.log').write_bytes(mounted)
                if b'\nA7R5_N12_LUT_READY\r\n' not in mounted:raise RuntimeError('客体内部 vfat 未成功挂载')
                e4=' A7R5_N12_E4_SERVICES=1' if json.loads(args.manifest.read_text()).get('native_e4_services') else ''
                if json.loads(args.manifest.read_text()).get('pending_notify_model'):e4+=' A7R5_N12_PENDING_NOTIFY=1'
                command='export A7R5_N12_LOADING=1'+e4+'; '+command
            if args.unlock and 'LD_PRELOAD=' in command:
                command='export A7R5_ASPECT_GUIDE406_UNLOCK=1; '+command
            if args.interactive and 'LD_PRELOAD=' in command:
                command='export A7R5_INITIAL_PRIVACY_NOTICE=1 A7R5_INPUT_COMPLETIONS=1; '+command
            FirmwareMonitor(vm.console).check()
            reply = vm.command(command, timeout=45)
            (vm.out/f'setup-{index:02d}.log').write_bytes(reply)
            result['commands_completed'] = index+1
            print('SETUP_COMPLETED', index, flush=True)
        if vm.cp_service:
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                vm.pump_loading()
                messages=vm.cp_service.messages
                if any(r['request'].startswith('ea') for r in messages):break
                time.sleep(.01)
            result['loading_messages']=len(vm.cp_service.messages)
            if not vm.cp_service.messages:raise RuntimeError('原AP启动线程未发出CP请求')
        # 由现有原厂页面初始化流程等待和操作，不直接写菜单或首次设置字段。
        vm.prime_native_menu()
        _, frame = capture(vm, 'native410-baseline-menu')
        if vm.cp_service:
            result['loading_state']=vm.loading_state('baseline')
            if json.loads(args.manifest.read_text()).get('native_e4_services'):
                diagnostic=native_diagnostic(vm)
                (vm.out/'native-diagnostic.log').write_bytes(diagnostic)
            evidence=vm.command('cat /proc/self/mountinfo; '
                'if [ -f /usr/data/lut/R5NATIVE.BIN ]; then /bin/busybox md5sum /usr/data/lut/R5NATIVE.BIN && /bin/busybox wc -c /usr/data/lut/R5NATIVE.BIN; fi; '
                'ls -la /usr/data/lut; test ! -e /usr/data/lut/R5NATIVE.NEW',timeout=15)
            (vm.out/'internal-storage.log').write_bytes(evidence)
            if args.scenario!='invalid-bin':
                expected=hashlib.md5(vm.loading_inputs['bin'].read_bytes()).hexdigest().encode()
                if expected+b'  /usr/data/lut/R5NATIVE.BIN' not in evidence or not re.search(rb'\b58976\s+/usr/data/lut/R5NATIVE.BIN',evidence):
                    raise RuntimeError('内部文件摘要／长度与原BIN不符')
            vm.set_native_paused(True)
        result['scenario']=args.scenario
        result['aspect_unlock_applied'] = b'OBS A7R5_NATIVE410_INSTALLED ' in vm.console.read_bytes()
        result.update(status='frame-collected', menu_frame=frame)
        if args.interactive:
            research_loop(vm, frame, result)
    except Exception as exc:
        error = exc
        result['error'] = str(exc)
        if vm.process and vm.process.poll() is None and '串口命令缺少' in str(exc):
            # 串口失步后只用本实例QMP只读采样，不再发送客体命令。
            try:
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.settimeout(5);vm.connect_qmp(sock)
                    with sock.makefile('rwb') as stream:
                        stream.readline()
                        for query in ({'execute':'qmp_capabilities'},{'execute':'stop'},
                                      {'execute':'human-monitor-command','arguments':{'command-line':'info registers'}}):
                            stream.write(json.dumps(query).encode()+b'\n');stream.flush()
                            while True:
                                reply=json.loads(stream.readline())
                                if 'error' in reply:raise RuntimeError(str(reply))
                                if 'return' in reply:break
                        snapshot={'registers':reply}
                        stack=re.search(r' SP=([0-9a-f]{16})',reply['return'])
                        if stack:
                            query={'execute':'human-monitor-command','arguments':{'command-line':'x/64gx 0x'+stack[1]}}
                            stream.write(json.dumps(query).encode()+b'\n');stream.flush()
                            while True:
                                reply=json.loads(stream.readline())
                                if 'error' in reply:raise RuntimeError(str(reply))
                                if 'return' in reply:break
                            snapshot['stack']=reply
                        (vm.out/'serial-failure-registers.json').write_text(json.dumps(snapshot,indent=2)+'\n')
            except Exception as qmp_error:result['qmp_diagnostic_error']=str(qmp_error)
        if vm.process and vm.process.poll() is None and '串口命令缺少' not in str(exc) and b'Entering exception monitor.' not in vm.console.read_bytes():
            try:
                (vm.out/'native-failure-diagnostic.log').write_bytes(native_diagnostic(vm))
                capture(vm,'failure-page')
                if vm.cp_service:vm.loading_state('failure')
            except Exception as diagnostic_error:result['diagnostic_error']=str(diagnostic_error)
    finally:
        result['close'] = vm.close()
        result['run_directory'] = str(vm.out)
        (vm.out/'native410-menu.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if error is not None or result['close'].get('exit_code') != 0:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
