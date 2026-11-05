"""核对长空闲红绿对照、真实客体帧及原厂组件身份。"""
import argparse
import json
from pathlib import Path
import re

from cpio_inputs import entries, only_observer_changed
from menu_live import snapshot_png
import environment as env


def load(path):
    return json.loads(path.read_text())


def match_run(run, manifest):
    candidate = load(manifest)
    vm = type('Candidate', (), {'manifest_path': manifest})()
    files = env.MenuVM.runtime_inputs(vm)
    used = load(run / 'inputs.json')
    for name in ('binary', 'kernel', 'initrd', 'dtb'):
        path = run / 'virt.dtb' if name == 'dtb' else files[name]
        if used[str(path)]['sha256'] != candidate['files'][name]['sha256']:
            raise ValueError('运行输入与清单不符：' + name)
    return files


def checked_frames(run):
    frames = {}
    for path in sorted(run.glob('*.png')):
        raw = path.with_suffix('.bin')
        if not raw.is_file():
            continue
        if snapshot_png(raw.read_bytes()) != path.read_bytes():
            raise ValueError('原帧与PNG不符：' + path.name)
        frames[path.name] = env.digest(path)
    return frames


def clean_exit(run):
    codes = [load(run / 'qt-research.json')['worker_exit_code'],
             load(run / 'exit.json')['exit_code'], load(run / 'cp/close.json')['exit_code']]
    if codes != [0, 0, 0]:
        raise ValueError('Qt工作进程、AP或CP侧车未正常退出')


def verify(baseline, original, before, repaired, after, menu):
    old_files = match_run(before, original)
    new_files = match_run(after, repaired)
    match_run(menu, repaired)
    changes = only_observer_changed(env.verified(load(baseline))['initrd'], new_files['initrd'])
    if changes['changed'] != ['simulation/menu-observe-a7r5-baseline.so']:
        raise ValueError('新客体的修复库身份不符')
    only_observer_changed(old_files['initrd'], new_files['initrd'])
    cpio = entries(new_files['initrd'])
    for name, expected in env.COMPONENT_SHAS.items():
        folder = 'usr/lib' if name == 'appFw.so' else 'cp' if name == 'cpapp-b.bin' else 'usr/share/app'
        if cpio[f'{folder}/{name}']['sha256'] != expected:
            raise ValueError('客体实际组件漂移：' + name)
    if load(repaired).get('shutdown_lifecycle_guard') is not True:
        raise ValueError('关机保护未开启')
    captures = [load(p / 'native410-menu.json')['lifecycle_capture'] for p in (before, after)]
    expected_packet = 'b3a5829f8751d224b49b64c3fa3ee7efce1aa1683d6877c0682144e0ce4702b2'
    if captures[0] != captures[1] or any(
        env.digest(p / 'original-init-4063.bin') != expected_packet for p in (before, after)
    ):
        raise ValueError('原厂初始化请求的红绿对照漂移')
    old_log = (before / 'console.log').read_text()
    new_log = (after / 'console.log').read_text()
    if not all(part in old_log for part in ('[Master][Shutdown] factor:00000011',
        'TASK_LOOKUP command=0x4d8 object=0', 'SEGV (PC=')):
        raise ValueError('缺少修复前原始崩溃证据')
    ordered = ('SHUTDOWN_GUARD enabled', '[Master][Shutdown] factor:00000011',
               'TASK_LOOKUP command=0x4d8 object=0', 'ABSENT_STILL_TASK command=0x4d8 caller=0x2771884',
               'id=790 count=0', 'A7R5_MANAGER_APPLY_RETURN original apply stack unwound')
    end = 0
    for marker in ordered:
        pos = new_log.find(marker, end)
        if pos < 0:
            raise ValueError('缺少按时序出现的原厂关机证据：' + marker)
        end = pos + len(marker)
    if re.search(r'SEGV \(PC=|Kernel panic|unhandled exception', new_log, re.I):
        raise ValueError('修复后仍有客体异常')
    soak = load(after / 'validation-driver.json')
    if soak['exit_code'] or soak['actions'][-3:] != ['ENTER', 'IDLE_SOAK', 'STOP']:
        raise ValueError('空闲对照期间出现意外操作或进程退出')
    original_screen, shutdown = soak['replies'][-3:-1]
    if (original_screen['screen'], shutdown['screen']) != (0xd9, 0x316):
        raise ValueError('原厂ST和关机页面不符')
    clean_exit(after)
    clean_exit(menu)
    tabs = load(menu / 'tabs-validation.json')
    parameters = load(menu / 'parameter-validation.json')
    idle = load(menu / 'idle-validation.json')
    if any(row['status'] != 'PASS' for row in (tabs, parameters, idle)):
        raise ValueError('菜单行为复验失败')
    if tabs['custom_rows'] != list(range(0x1611, 0x161c)) + [0x1610] or len(parameters['steps']) != 8:
        raise ValueError('正式十二款或八项工作值验证不完整')
    menu_log = (menu / 'console.log').read_text()
    if not all(marker in menu_log for marker in ('LIFECYCLE_INIT_ENTER', 'NOTIFY_PENDING')) or 'LIFECYCLE_INIT_RETURN' in menu_log:
        raise ValueError('原生初始化等待证据发生变化')
    frames = {p.name: checked_frames(p) for p in (before, after, menu)}
    for p, required in ((after, ['research-020-ENTER.png', 'research-021-IDLE_SOAK.png']),
                        (menu, [Path(parameters['steps'][-1]['png']).name])):
        if any(name not in frames[p.name] for name in required):
            raise ValueError('缺少要求的真实客体帧')
    return {'status': 'PARTIAL', 'QEMU_shutdown_null_dereference_fixed': True,
            'soak_host_seconds_minimum': 90, 'shutdown_screen_reached': True,
            'full_shutdown_power_cycle_verified': False, 'E4_init_completed': False,
            'twelve_recipe_menu_and_eight_working_values_verified': True, 'ISP_verified': False,
            'camera_io': False, 'CPIO_delta': changes, 'components': env.COMPONENT_SHAS,
            'recipe_BIN_sha256': env.BIN_SHA, 'captured_init_sha256': expected_packet,
            'manifest_sha256': env.digest(repaired), 'raw_png_frames': frames}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'original', 'before', 'repaired', 'after', 'menu', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    proof = verify(*(getattr(args, name).resolve() for name in
                     ('baseline', 'original', 'before', 'repaired', 'after', 'menu')))
    with args.output.open('x') as stream:
        json.dump(proof, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({run: len(frames) for run, frames in proof['raw_png_frames'].items()}))
