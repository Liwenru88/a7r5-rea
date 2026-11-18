"""只运行隔离QEMU中的AP自然启动，观察真实启动库状态；不连接相机。"""
from pathlib import Path
import argparse
import importlib.util
import json
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / 'a7r5-qemu'
sys.path.insert(0, str(LAB / 'tools'))
import app_paths
from native_vm import NativeVM, digest


class BootVM(NativeVM):
    def __init__(self, path):
        self.manifest_path = path.absolute()
        self.runtime_inputs()
        super().__init__('boot-menu406', capid=True, boot_services=True)

    def runtime_inputs(self):
        report = json.loads(self.manifest_path.read_text())
        assert report['schema'] == 'af-boot-menu406/1'
        assert set(report['files']) == {'binary', 'gpe', 'kernel', 'initrd', 'dtb'}
        result = {}
        for key, row in report['files'].items():
            p = Path(row['path'])
            assert p.is_file() and not p.is_symlink() and p.resolve() == p.absolute()
            assert p.stat().st_size == row['bytes'] and digest(p) == row['sha256']
            assert p.is_relative_to(ROOT / '.local/fixed-custom-filters') or p.is_relative_to(LAB)
            result[key] = p
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--interactive', action='store_true')
    args = parser.parse_args()
    assert args.manifest.absolute().is_relative_to(ROOT / '.local/fixed-custom-filters')
    app_paths.paths = lambda: app_paths.AppPaths(LAB, args.manifest.absolute().parent / 'execution')
    # NativeVM已导入的VM输出根显式隔离，不修改默认manifest或共享客体。
    import vm_session
    app_paths.paths().prepare()
    vm_session.RUNS = app_paths.paths().runs
    module_path = LAB / 'experiments/aspect-guide406/probe_menu.py'
    sys.path.insert(0, str(module_path.parent))
    spec = importlib.util.spec_from_file_location('boot406_original_setup', module_path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    vm = BootVM(args.manifest)
    configuration=json.loads(args.manifest.read_text())
    result = dict(status='RUNNING', camera_io=False, CP_hardware_emulated=False, actual_CP_peer=False)
    try:
        print('RUN_DIRECTORY', vm.out, flush=True)
        vm.start()
        print('KERNEL_READY', flush=True)
        setup=module.setup_commands()
        if configuration.get('software_storage'):
            setup[0]=' && '.join([
                'mount -t tmpfs tmpfs /tmp', 'mount -t tmpfs tmpfs /tmp_wbshd',
                'test ! -e /dev/nflasha2', 'mknod /dev/nflasha2 b 1 2',
                'dd if=/simulation/af-body.fat of=/dev/nflasha2 bs=4096',
                'mount -t vfat -o uid=0,gid=0,dmask=0077,fmask=0177,iocharset=ascii /dev/nflasha2 /setting',
                'mkdir -m 700 /tmp/af-sd0 /tmp/af-sd1',
                'for af_source in /simulation/sd0-*; do af_name=${af_source##*/}; cp "$af_source" "/tmp/af-sd0/${af_name#sd0-}" || exit; done',
                'for af_source in /simulation/sd1-*; do af_name=${af_source##*/}; cp "$af_source" "/tmp/af-sd1/${af_name#sd1-}" || exit; done'])
            if configuration.get('restore_records'):
                setup[0]+=' && mkdir -m 700 /setting/A7LOOKS1 && for af_source in /simulation/restore-*; do af_name=${af_source##*/}; cp "$af_source" "/setting/A7LOOKS1/${af_name#restore-}" || exit; done'
        if configuration.get('chinese'):
            setup[0]+=' && mkdir -p /tmp/images && cp /simulation/MYingHeiC-GB18030-SJ_wIcon.ltt /simulation/MYingHeiC-Big5-SJ_wIcon.ltt /simulation/Sony_DI_Icons.ttf /tmp/images/'
        for index, command in enumerate(setup):
            if 'LD_PRELOAD=' in command and args.interactive:
                command = 'export A7R5_INITIAL_PRIVACY_NOTICE=1 A7R5_INPUT_COMPLETIONS=1; ' + command
            if 'LD_PRELOAD=' in command and configuration.get('software_protocol_peer'):
                command = 'export A7R5_SOFTWARE_AF_PEER=1; ' + command
            reply = vm.command(command, timeout=45)
            (vm.out / f'setup-{index:02d}.log').write_bytes(reply)
            print('SETUP', index, flush=True)
        # 仅给原应用有限时间执行自然初始化，既不设admission也不调用publish。
        for _ in range(20):
            time.sleep(1)
            if vm.process.poll() is not None:
                raise RuntimeError('QEMU提前退出')
        reply = vm.command('ps -ef', timeout=15)
        (vm.out / 'processes.log').write_bytes(reply)
        pids = re.findall(rb'^(?:root|0)\s+(\d+)\s+.*?/usr/bin/im\.elf', reply, re.M)
        assert len(pids) == 1, reply[-1500:]
        state = vm.command('/simulation/af-state ' + pids[0].decode() + '; echo AF_STATE_RC=$?', timeout=20)
        (vm.out / 'state.log').write_bytes(state)
        log = vm.command('cat /tmp/menu-load.log', timeout=20)
        (vm.out / 'application.log').write_bytes(log)
        assert b'AF_STATE_RC=0' in state, state
        result.update(status='NATURAL_STARTUP_STATE_COLLECTED_NOT_MENU_ACCEPTANCE', pid=pids[0].decode(),
                      state=state.decode(errors='replace'), forced_admission=False, forced_publish=False)
        print('\n'.join(s for s in state.decode(errors='replace').splitlines() if s.startswith('AF_STATE ')), flush=True)
        if args.interactive:
            from menu_bridge import capture
            from menu_live import key_command
            from input_completion import wait_input_completion
            vm.prime_native_menu()
            _, frame = capture(vm, 'menu-initial')
            actions = []
            print('MENU_READY ' + json.dumps(dict(png=str(vm.out/'menu-initial.png'), screen=vm.last_native_screen())), flush=True)
            for line in sys.stdin:
                request = json.loads(line)
                assert isinstance(request, dict) and set(request) == {'action'}
                action = request['action']
                if action == 'STOP':
                    break
                assert action in ('UP','DOWN','LEFT','RIGHT','ENTER','MENU','SNAPSHOT','MODE_M','STORE_EXPORT','STATE')
                after = None
                if action == 'STORE_EXPORT':
                    assert configuration.get('software_storage')
                    raw=vm.command('/simulation/af-store-export; af_export_rc=$?; echo AF_STORE_RC=$af_export_rc; test "$af_export_rc" -eq 0',timeout=45)
                    (vm.out/f'store-export-{len(actions):03d}.log').write_bytes(raw)
                    assert b'AF_STORE_RC=0' in raw
                    from store_records import export
                    from menu_live import clean_console
                    # 串口原始回执保留；仅去掉既有UDIF内核日志插入，再按严格契约解析。
                    report=export(clean_console(raw).decode(errors='strict'),vm.out/f'store-export-{len(actions):03d}')
                    print('STORE_REPLY '+json.dumps(report,ensure_ascii=False),flush=True)
                elif action == 'STATE':
                    raw=vm.command('/simulation/af-state '+pids[0].decode()+'; cat /proc/mounts',timeout=20)
                    (vm.out/f'state-{len(actions):03d}.log').write_bytes(raw)
                    print(raw.decode(errors='replace'),flush=True)
                elif action != 'SNAPSHOT':
                    offset = vm.console.stat().st_size
                    before = vm.last_native_screen()
                    vm.command(key_command(action), timeout=30)
                    if action == 'MENU' and before == 0x355:
                        vm.wait_native_screen(0x2d6)
                        after = frame['sequence']
                    else:
                        # TCG下导入确认会执行有界拟合步骤；仍等待真实完成回执，不重发按键。
                        after = max(frame['sequence'], wait_input_completion(vm, action, offset, timeout=45))
                name = 'menu-%03d-%s' % (len(actions), action)
                # 原导出助手只等2秒客体时间；TCG拟合时允许有界等待下一真实帧。
                # 只重试导出超时，不重发输入、不放行旧帧或固件异常。
                deadline=time.monotonic()+45
                while True:
                    try:
                        _, frame = capture(vm, name, after=after)
                        break
                    except RuntimeError as error:
                        if after is None or str(error)!='guest 命令失败，返回码 2' or time.monotonic()>=deadline:raise
                        with (vm.out/'frame-waits.jsonl').open('a') as wait_log:
                            wait_log.write(json.dumps(dict(action=action,after=after,timeout_guest_ms=2000))+'\n')
                row = dict(action=action, png=str(vm.out/(name+'.png')), frame=frame, screen=vm.last_native_screen())
                actions.append(row)
                (vm.out/'actions.json').write_text(json.dumps(actions, ensure_ascii=False, indent=2)+'\n')
                print('MENU_REPLY ' + json.dumps(dict(action=action,png=row['png'],screen=row['screen'])), flush=True)
            else:
                raise RuntimeError('未收到STOP，控制输入提前关闭')
            result['actions'] = actions
    except Exception as error:
        result.update(status='FAILED', error=str(error))
        raise
    finally:
        result['exit'] = vm.close()
        (vm.out / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        print('RESULT', vm.out / 'verification.json', flush=True)


if __name__ == '__main__':
    main()
