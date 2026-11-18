"""本次模拟器的文件控制通道；不接受任意客体 shell。"""
import hashlib
import json
import re
import time
from pathlib import Path
from vm_session import RUNS
from menu_live import snapshot_png, key_command, FirmwareMonitor
from headless_osd_capture import decode_export, HEADER, METADATA
from input_context import InputContext,MENU_SCREENS
from input_registry import InputRegistry
from control_actions import ACTION_SPECS
from mode_state import displayed_mode,wait_mode_frame,shooting_signature
from input_completion import wait_input_completion
from latency import stage, record

NAVIGATION = ('UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'MENU')


def atomic_json(path, value):
    temp = path.with_suffix('.part')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    temp.replace(path)


def capture(vm, name, timings=None, after=None):
    timings = timings if timings is not None else {}
    if b'OBS OSD_HEADLESS_FAILED ' in vm.console.read_bytes():
        raise RuntimeError('图形消费者已停止，拒绝显示旧帧')
    with stage(timings, 'export_ms'):
        command = '/simulation/headless-osd-export'
        if after is not None:
            command += ' --after ' + str(int(after))
        data = vm.command(command, timeout=90)
    timings.update({'export_' + key: value for key, value in getattr(vm, 'last_command_timings', {}).items()})
    ready = re.search(rb'HEADLESS_OSD_READY after=([0-9]+) sequence=([0-9]+) wait_ms=([0-9]+)', data)
    if after is not None:
        if not ready or int(ready[1]) != after:
            raise ValueError('缺少本次新帧等待回执')
        timings['guest_ready_wait_ms'] = int(ready[3])
    with stage(timings, 'decode_validate_ms'):
        raw, info = decode_export(data)
        if after is not None and info['sequence'] <= after:
            raise ValueError('按键后未取得新序列，拒绝发布旧帧')
        if ready and int(ready[2]) != info['sequence']:
            raise ValueError('就绪回执与导出帧序列不一致')
    timings['serial_output_bytes'] = len(data)
    timings['transport_bytes'] = info['transport_bytes']
    with stage(timings, 'png_ms'):
        png = snapshot_png(raw)
    info['pixel_sha256'] = hashlib.sha256(raw[HEADER+METADATA:]).hexdigest()
    # 拍摄信息页顶部的无卡提示闪烁；返回提示框时比较其下方的原始像素。
    pixels=raw[HEADER+METADATA:]
    info['stable_pixel_sha256']=shooting_signature(pixels)
    info['shooting_mode']=displayed_mode(pixels)
    with stage(timings, 'persist_ms'):
        (vm.out/(name+'.bin')).write_bytes(raw)
        (vm.out/(name+'.png')).write_bytes(png)
        atomic_json(vm.out/(name+'.json'), info)
    return png, info


def validate_request(request):
    if not isinstance(request, dict) or set(request) != {'id','action','key'}:
        raise ValueError('请求结构不符')
    if not isinstance(request['id'], str) or not re.fullmatch('[0-9a-f]{32}', request['id']):
        raise ValueError('请求 ID 不符')
    if request['action'] == 'key' and isinstance(request['key'], str) and request['key'] in ACTION_SPECS:
        return
    if request['action'] in ('stop','snapshot','initial_setup') and request['key'] is None:
        return
    raise ValueError('仅允许固定导航键、截图和退出')


def run_live(vm, directory):
    bridge = Path(directory)
    if bridge.is_symlink() or bridge.resolve().parent != RUNS.resolve() or not re.fullmatch('ui-[0-9a-f]{32}', bridge.name):
        raise ValueError('控制目录超出本次实验')
    with (bridge/'started').open('x') as f:
        f.write(str(vm.out)+'\n')
    (bridge/'requests').mkdir()
    monitor = FirmwareMonitor(vm.console)
    state = {'state':'starting', 'run':str(vm.out), 'keys':NAVIGATION, 'sequence':0}
    atomic_json(bridge/'status.json', state)
    index = 0
    context = InputContext()
    registry = InputRegistry.load()
    initial_pixel = None
    setup_requested = False

    def privacy_state():
        data=vm.command("grep '^KEY_TRACE_PRIVACY_STATUS ' /tmp/menu-load.log",timeout=30)
        values=re.findall(rb'^KEY_TRACE_PRIVACY_STATUS accepted=([012])\r?$',data,re.M)
        if not values:
            raise RuntimeError('缺少原厂首次设置状态，停止')
        vm.set_native_paused(True)
        return int(values[-1])

    def refresh(key, timings=None, after=None, expected_mode=None):
        nonlocal index, initial_pixel
        name=f'live-{index:04d}-{key}'
        if expected_mode:
            def sample(attempt,sequence):
                return capture(vm,f'mode-wait-{index:04d}-{attempt:03d}',timings,sequence)
            png,info,attempt=wait_mode_frame(sample,expected_mode,after)
            source=vm.out/f'mode-wait-{index:04d}-{attempt:03d}'
            for suffix in ('.bin','.png','.json'):
                (vm.out/(name+suffix)).write_bytes(source.with_suffix(suffix).read_bytes())
        else:png, info = capture(vm,name, timings, after)
        screen=vm.last_native_screen()
        privacy=None
        if key=='INITIAL' or (setup_requested and key in ('ENTER','MENU') and screen in (0x355,0x1e3)):
            privacy=privacy_state()
        if key=='INITIAL':
            initial_pixel=info['pixel_sha256']
        temp=bridge/'frame.part'; temp.write_bytes(png);temp.replace(bridge/'frame.png')
        index += 1
        state.update(state='running', sequence=info['sequence'], pixel_sha256=info['pixel_sha256'],
                     png_sha256=hashlib.sha256(png).hexdigest(), last_key=key,
                     input_context=context.observe(key, info['pixel_sha256'], screen, privacy,info['stable_pixel_sha256']),
                     initial_setup_available=not setup_requested and not context.privacy_accepted and info['pixel_sha256']==initial_pixel,
                     privacy_accepted=context.privacy_accepted)
        state['shooting_mode']=info['shooting_mode']
        atomic_json(bridge/'status.json',state)

    try:
        refresh('INITIAL')
        deadline=time.monotonic()+6*3600
        while time.monotonic()<deadline:
            if (bridge/'cancel').exists():break
            monitor.check()
            if vm.process.poll() is not None:
                raise RuntimeError('本次虚拟器提前退出')
            request_path=bridge/'request.json'
            if not request_path.exists():
                time.sleep(.01);continue
            if request_path.is_symlink() or request_path.stat().st_size>256:
                raise ValueError('控制请求文件不符')
            request=json.loads(request_path.read_text())
            validate_request(request)
            request_path.rename(bridge/'requests'/(request['id']+'.json'))
            if request['action']=='stop':
                state['state']='stopping';atomic_json(bridge/'status.json',state)
                atomic_json(bridge/('reply-'+request['id']+'.json'),{'ok':True})
                break
            state['state']='busy';atomic_json(bridge/'status.json',state)
            timings = {}
            started = time.perf_counter()
            frame_after=state['sequence']
            if request['action']=='initial_setup':
                if not state.get('initial_setup_available') or context.context!='menu':
                    raise ValueError('首次设置仅允许从本次初始菜单请求一次')
                setup_requested=True
                vm.command('touch /tmp/a7r5-request-initial-privacy',timeout=30)
                vm.wait_native_screen(0x1e3)
            if request['action']=='key':
                control=ACTION_SPECS[request['key']][0]
                if not registry.available(control, context.context):
                    raise ValueError('该按键尚未在当前原厂界面验证')
                if control=='MODE_DIAL' and not state.get('shooting_mode'):
                    raise ValueError('当前信息布局未显示已验证的模式标志，未发送模式事件')
                with stage(timings, 'key_wait_ms'):
                    offset=vm.console.stat().st_size
                    before=vm.last_native_screen()
                    vm.command(key_command(request['key']),timeout=30)
                    # 仅 0x355 的已知原生重入不经过原厂 input process；保持单独门槛。
                    if not (request['key']=='MENU' and before==0x355):
                        frame_after=max(frame_after,wait_input_completion(vm,request['key'],offset))
                    if request['key'] == 'MENU' and context.context in ('shooting','shooting_ready','setup_complete'):
                        vm.wait_native_screen(MENU_SCREENS)
                timings.update({'key_' + key: value for key, value in getattr(vm, 'last_command_timings', {}).items()})
            refresh(request['key'] or ('INITIAL_SETUP' if request['action']=='initial_setup' else 'SNAPSHOT'), timings,
                    after=frame_after if request['action'] in ('key','initial_setup') else None,
                    expected_mode=request['key'][5:] if request['action']=='key' and request['key'].startswith('MODE_') else None)
            timings['worker_ms'] = round((time.perf_counter() - started) * 1000, 3)
            record(bridge, dict(id=request['id'], key=request['key'], **timings))
            atomic_json(bridge/('reply-'+request['id']+'.json'),{'ok':True,'sequence':state['sequence']})
        return {'live_actions':index-1, 'bridge':str(bridge)}
    except Exception as error:
        state.update(state='failed',error=str(error));atomic_json(bridge/'status.json',state)
        raise
    finally:
        if state['state']!='failed':
            state['state']='stopping';atomic_json(bridge/'status.json',state)
