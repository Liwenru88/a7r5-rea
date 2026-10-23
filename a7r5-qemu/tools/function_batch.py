"""由已提取映射支持的固定 Fn/显示诊断，不在正式界面启用候选。"""
from menu_bridge import capture, atomic_json
from menu_live import key_command, RESEARCH_KEYS
from input_batch import received, wait_research_receipt


def run(vm, profile='fn-display'):
    if profile not in ('fn-display', 'display-playback', 'option-help', 'all-inputs', 'neutral-fn', 'waited-fn', 'privacy-fn', 'privacy-disp', 'privacy-playback', 'initial-fn', 'initial-disp', 'initial-playback', 'initial-up', 'initial-inspect', 'initial-controls'):
        raise ValueError('不支持的固定诊断场景')
    report = {'status': 'running', 'profile': profile, 'steps': [],
              'boundary': 'isolated emulator RAM; static mapping is not function acceptance'}
    target = vm.out/'function-batch.json'
    def step(key, after=None):
        before=vm.last_native_screen();offset=vm.console.stat().st_size
        data = vm.command(key_command(key), timeout=30)
        if key=='MENU' and before==0x355:
            vm.wait_native_screen(0x2d6)
            data=vm.console.read_bytes()[offset:]
        evidence=wait_research_receipt(vm,key,before,offset)
        _, info = capture(vm, 'function-%02d-%s' % (len(report['steps']), key), after=after)
        row = {'key': key, **evidence, 'frame': info, 'screen': vm.last_native_screen()}
        report['steps'].append(row); atomic_json(target, report)
        return info
    try:
        _, initial = capture(vm, 'function-initial')
        previous = initial
        if profile.startswith('initial-'):
            vm.command('touch /tmp/a7r5-request-initial-privacy',timeout=30)
            vm.wait_native_screen(0x1e3)
            _,previous=capture(vm,'function-initial-privacy',after=initial['sequence'])
            if previous['pixel_sha256']!='7abe6e64a90e14621b6bda99afafe096d805b03383a76b297381f7284e2b98ee':
                raise RuntimeError('首次隐私说明画面不符，未确认')
            report['privacy_notice_initial_frame']=previous
            if profile=='initial-inspect':
                from key_research_session import run as inspect
                report['interactive']=inspect(vm,previous)
                dispatch=vm.command("grep '^KEY_TRACE_' /tmp/menu-load.log",timeout=30)
                (vm.out/'input-dispatch.log').write_bytes(dispatch)
                vm.set_native_paused(True)
                report['status']='collected-not-enabled'
                return report
            from initial_setup import finish_test_setup
            previous=finish_test_setup(vm,previous,step)
            report['initial_setup_completed']=True
            if profile=='initial-controls':
                from key_research_session import run as inspect
                report['interactive']=inspect(vm,previous)
                dispatch=vm.command("grep '^KEY_TRACE_' /tmp/menu-load.log",timeout=30)
                (vm.out/'input-dispatch.log').write_bytes(dispatch)
                vm.set_native_paused(True)
                report['status']='collected-not-enabled'
                return report
        if profile.startswith('privacy-'):
            for key in ('LEFT','UP','RIGHT')+('DOWN',)*6:
                previous=step(key,after=previous['sequence'])
            menu=previous
            previous=step('ENTER',after=previous['sequence'])
            if vm.last_native_screen()!=0x1e3 or previous['pixel_sha256']!='63711c719cf896bd91e5ed8f74990c19af25a8409fc11704c18ab2d1051cf0e8':
                raise RuntimeError('原厂隐私说明页面不符，未确认')
            previous=step('ENTER',after=previous['sequence'])
            if previous['pixel_sha256']!=menu['pixel_sha256']:
                raise RuntimeError('隐私说明未返回原设置页')
            report['privacy_notice']='original informational notice viewed and OK acknowledged in guest RAM'
        if profile == 'neutral-fn':
            neutral = vm.command('/simulation/inject-key 0x807a0020 0x92840747 0x7095 0 0 0 1', timeout=30)
            report['initial_neutral_event'] = neutral.decode(errors='replace')
        if profile == 'option-help':
            for key in ('DOWN',)*5+('ENTER',):
                previous = step(key, after=previous['sequence'])
            if vm.last_native_screen() != 0x2ed:
                raise RuntimeError('未进入已观察到的菜单选项弹层')
            option = previous
            help_frame = step('C4', after=previous['sequence'])
            if vm.last_native_screen() != 0x259 or help_frame['pixel_sha256'] == option['pixel_sha256']:
                raise RuntimeError('未打开原厂帮助')
            restored = step('ENTER', after=help_frame['sequence'])
            if restored['pixel_sha256'] != option['pixel_sha256']:
                raise RuntimeError('帮助返回未恢复同一选项弹层')
            report['option_help_roundtrip'] = True
        else:
            previous = step('MENU', after=previous['sequence'])
            if vm.last_native_screen() != 0:
                raise RuntimeError('未到已知拍摄信息页面，拒绝测试候选')
            keys = (profile.split('-',1)[1].upper(),) if profile.startswith(('privacy-','initial-')) else ('FN',) if profile in ('fn-display','neutral-fn','waited-fn') else ('FN','DISP','PLAYBACK') if profile == 'all-inputs' else ('DISP','PLAYBACK')
            for key in keys:
                if profile == 'waited-fn':
                    data=vm.command(key_command(key)+' && sleep 1', timeout=30)
                    events=received(data,key,RESEARCH_KEYS if key in RESEARCH_KEYS else None)
                    _, previous=capture(vm,'function-%02d-%s' % (len(report['steps']),key),after=previous['sequence'])
                    report['steps'].append({'key':key,'received':events,'frame':previous,'screen':vm.last_native_screen(),'settle_seconds':1})
                    continue
                previous = step(key, after=previous['sequence'])
        dispatch=vm.command("grep '^KEY_TRACE_' /tmp/menu-load.log",timeout=30)
        (vm.out/'input-dispatch.log').write_bytes(dispatch)
        vm.set_native_paused(True)
        report['status'] = 'collected-not-enabled'
        return report
    except Exception as error:
        report.update(status='stopped', error=str(error))
        raise
    finally:
        atomic_json(target, report)
