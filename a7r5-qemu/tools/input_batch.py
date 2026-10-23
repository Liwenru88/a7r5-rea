"""固定三候选诊断批次；无任意键码、无遍历、无自动重试。"""
import json
import re
import time
from menu_bridge import capture, atomic_json
from menu_live import key_command, KEYS, SINGLE_STATUS, TAP_STATUS, clean_console


def received(data, key, mapping=None):
    # 与串口命令使用相同的已识别内核记录边界规则；未知内容、来源和释放顺序仍严格拒绝。
    clean = clean_console(data).replace(b'\r', b'')
    events = []
    for code, status in re.findall(rb'^(?:/ # )?OBS A7R5_INPUT_RECEIVED .*?queue=0x807a0020 source=0x92840747 key_code=(0x[0-9a-f]+|0) sub=0 status=(0x[0-9a-f]+|0) ex=0 from=0x1$', clean, re.M):
        if int(code, 0) == int((mapping or KEYS)[key], 0):
            events.append(int(status, 0))
    expected = [int(SINGLE_STATUS[key], 0)] if key in SINGLE_STATUS else [int(TAP_STATUS.get(key,'1'),0), 0]
    if events != expected:
        raise RuntimeError('消费端输入回执不符，停止本批：' + key + ' ' + str(events))
    return events


def research_receipt(data,key,before):
    """已知原生重入刻意消费 MENU，单独核对注入对与适配回执，不冒充原厂消费。"""
    if key=='MENU' and before==0x355:
        clean=clean_console(data).replace(b'\r',b'')
        states=[int(x,0) for x in re.findall(rb'^INJECT_KEY_SEND queue=0x807a0020 src=0x92840747 key_code=0x1ab sub=0 status=(0x1|0) ex=0 from=0x1 result=0$',clean,re.M)]
        if states!=[1,0] or b'OBS A7R5_NATIVE_BOOT_EXIT_OMITTED ' not in clean or b'OBS A7R5_NATIVE_MENU_REENTER_RETURN current=0x354 ' not in clean:
            raise RuntimeError('原生重入的注入对或适配回执不符')
        return {'received':None,'injected':states,'delivery':'known-native-menu-reentry'}
    from menu_live import RESEARCH_KEYS
    return {'received':received(data,key,RESEARCH_KEYS if key in RESEARCH_KEYS else None),'delivery':'original-input-consumer'}


def wait_research_receipt(vm,key,before,offset,timeout=5):
    """命令结束不等于消费端已释放；只读本次日志等待，不重发按键或追加客体请求。"""
    from menu_live import FirmwareMonitor
    monitor=FirmwareMonitor(vm.console);deadline=time.monotonic()+timeout
    while True:
        monitor.check()
        data=vm.console.read_bytes()[offset:]
        try:return research_receipt(data,key,before)
        except RuntimeError as error:
            if time.monotonic()>=deadline:raise RuntimeError('等待原厂消费回执超时；'+str(error)) from error
        if vm.process.poll() is not None:raise RuntimeError('等待消费回执时虚拟器退出')
        time.sleep(.01)


def run(vm):
    report = {'status': 'running', 'batch': 'delete-dial', 'entries': [],
              'boundary': '固定候选；只作用于隔离 VM RAM；不证明实体来源或拍摄功能'}
    target = vm.out / 'input-batch.json'
    _, initial = capture(vm, 'batch-0000-INITIAL')
    reference = initial['pixel_sha256']
    report['initial_pixel_sha256'] = reference
    atomic_json(target, report)
    try:
        for index, key in enumerate(('DELETE', 'REAR_RIGHT', 'REAR_LEFT'), 1):
            data = vm.command(key_command(key) + ' && sleep 1', timeout=30)
            events = received(data, key)
            _, frame = capture(vm, f'batch-{index:04d}-{key}')
            row = {'key': key, 'code': KEYS[key], 'received_statuses': events,
                   'pixel_sha256': frame['pixel_sha256'], 'changed_from_initial': frame['pixel_sha256'] != reference,
                   'enable_physical_control': False,
                   'reason': '消费端收到消息；实体映射和具体上下文行为仍须分别证明'}
            report['entries'].append(row)
            atomic_json(target, report)
            if key == 'DELETE':
                expected = '2b9fb0a0278266fa0b30ea249523d0d317b56fb8bbbccaf4e8c5b1f4d171c868'
                if frame['pixel_sha256'] != expected or vm.last_native_screen() != 0x259:
                    raise RuntimeError('帮助页不符合已观察场景，停止本批')
                data = vm.command(key_command('ENTER') + ' && sleep 1', timeout=30)
                events = received(data, 'ENTER')
                _, back = capture(vm, 'batch-0001b-GUIDE_RETURN')
                if back['pixel_sha256'] != reference:
                    raise RuntimeError('帮助页确认未恢复菜单，停止本批')
                report['guide_return'] = {'key': 'ENTER', 'received_statuses': events,
                                           'pixel_sha256': back['pixel_sha256']}
                row['reason'] = 'C4/删除在菜单中打开机内帮助，确认返回相同菜单；不证明回放删除'
        # 恢复相同菜单后，复用原六键独立预期核对共享链路。
        if report['entries'][-1]['pixel_sha256'] != reference:
            raise RuntimeError('反向旋转未恢复菜单基线，停止本批')
        report['navigation'] = []
        for index, key in enumerate(('RIGHT', 'DOWN', 'ENTER', 'UP', 'LEFT', 'MENU'), 4):
            data = vm.command(key_command(key) + ' && sleep 1', timeout=30)
            events = received(data, key)
            _, frame = capture(vm, f'batch-{index:04d}-{key}')
            report['navigation'].append({'key': key, 'received_statuses': events,
                                         'pixel_sha256': frame['pixel_sha256']})
            atomic_json(target, report)
        report['status'] = 'collected-not-enabled'
        return report
    except Exception as error:
        report.update(status='stopped', error=str(error))
        raise
    finally:
        atomic_json(target, report)
