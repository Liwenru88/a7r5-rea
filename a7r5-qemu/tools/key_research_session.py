"""隔离 VM 的固定符号键研究入口；没有任意命令、原始键码或自动重试。"""
import json
import re
import time
from menu_bridge import atomic_json, capture
from menu_live import key_command, RESEARCH_KEYS
from input_batch import wait_research_receipt

# 只增加已有正反向表/设置种子或既有拨轮研究记录支持的固定候选。
RESEARCH_CONTROLS = ('UP','DOWN','LEFT','RIGHT','ENTER','MENU','C4','FN','DISP','PLAYBACK',
                     'CUSTOM','CUSTOM2','CUSTOM3','REAR_LEFT','REAR_RIGHT',
                     'FRONT_DIAL_LEFT','FRONT_DIAL_RIGHT','REAR_DIAL_L_LEFT','REAR_DIAL_L_RIGHT',
                     'REAR_DIAL_R_LEFT','REAR_DIAL_R_RIGHT','CONTROL_WHEEL_LEFT','CONTROL_WHEEL_RIGHT',
                     'MODE_P','MODE_A','MODE_S','MODE_M','MODE_AUTO',
                     'JOYSTICK_UP','JOYSTICK_DOWN','JOYSTICK_LEFT','JOYSTICK_RIGHT','JOYSTICK_CENTER')


def run(vm, initial):
    report={'status':'running','steps':[],'initial':initial}
    directory=vm.out/'research'
    directory.mkdir()
    target=directory/'status.json'
    def publish(frame):
        atomic_json(target,{'state':'running','run':str(vm.out),'frame':frame,'screen':vm.last_native_screen()})
        atomic_json(directory/'report.json',report)
    previous=initial
    publish(previous)
    deadline=time.monotonic()+1200
    while time.monotonic()<deadline:
        path=directory/'request.json'
        if not path.exists():
            time.sleep(.05);continue
        if path.is_symlink() or path.stat().st_size>128:
            raise ValueError('研究请求文件不符')
        request=json.loads(path.read_text())
        if set(request)!={'id','key'} or not isinstance(request['id'],str) or not re.fullmatch('[0-9a-f]{32}',request['id']):
            raise ValueError('研究请求结构不符')
        key=request['key']
        if key not in (*RESEARCH_CONTROLS,'OBSERVE','STOP'):
            raise ValueError('非固定研究键')
        path.rename(directory/('request-'+request['id']+'.json'))
        if key=='STOP':
            report['status']='collected-not-enabled'
            atomic_json(directory/'report.json',report)
            return report
        if key=='OBSERVE':
            # 固定研究等待与只读日志，不重发事件；不进入正式客户端。
            vm.command('sleep 0.25',timeout=5)
            _,previous=capture(vm,'research-%04d-OBSERVE' % len(report['steps']),after=previous['sequence'])
            row={'key':key,'delivery':'observation-only','frame':previous,'screen':vm.last_native_screen()}
            report['steps'].append(row);publish(previous)
            atomic_json(directory/('reply-'+request['id']+'.json'),row)
            continue
        before=vm.last_native_screen();offset=vm.console.stat().st_size
        data=vm.command(key_command(key),timeout=30)
        if key=='MENU' and before==0x355:
            vm.wait_native_screen(0x2d6)
            data=vm.console.read_bytes()[offset:]
        evidence=wait_research_receipt(vm,key,before,offset)
        _,previous=capture(vm,'research-%04d-%s' % (len(report['steps']),key),after=previous['sequence'])
        row={'key':key,**evidence,'frame':previous,'screen':vm.last_native_screen()}
        report['steps'].append(row)
        publish(previous)
        atomic_json(directory/('reply-'+request['id']+'.json'),row)
    raise TimeoutError('固定输入研究会话超时')
