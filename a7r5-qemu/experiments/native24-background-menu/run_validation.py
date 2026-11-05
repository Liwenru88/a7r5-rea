"""通过实际Qt按钮执行固定导航，保留原帧、进程退出和源身份。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

LAB = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True)
    args = parser.parse_args()
    baseline = LAB/'runs/native-native12-410-rsdd3lr1'
    previous = json.loads((baseline/'qt-research.json').read_text())['operations'][:21]
    expected = json.loads((baseline/'research-actions.json').read_text())[:21]
    actions = [item['action'] for item in previous]
    # 首次原厂ST状态正常时进入调参，再检查PT／NT往返。
    actions += ['RIGHT','ENTER','ENTER','DOWN','DOWN','UP','UP']
    actions += ['UP']*24 + ['DOWN']*24 + ['DOWN']*7 + ['UP']*7
    actions += ['MENU','MENU'] + ['MENU','MENU']*4 + ['MENU','ENTER','DOWN','DOWN','UP','UP','STOP']
    command = [sys.executable,'-B',str(HERE/'qt_research.py'),'--manifest',str(args.manifest.resolve())]
    with args.log.open('xb') as log:
        proc = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,cwd=LAB)
        buf = bytearray()
        replies = []
        def wait_reply(timeout=180):
            deadline = time.monotonic()+timeout
            while time.monotonic()<deadline:
                while b'\n' in buf:
                    line, _, rest = buf.partition(b'\n');buf[:] = rest
                    if line.startswith(b'QT_REPLY '):
                        return json.loads(line[len(b'QT_REPLY '):])
                if select.select([proc.stdout],[],[],.1)[0]:
                    data = os.read(proc.stdout.fileno(),65536)
                    if data:
                        log.write(data);log.flush();buf.extend(data)
                    elif proc.poll() is not None:
                        raise RuntimeError('Qt退出前缺少预期回执')
                elif proc.poll() is not None:
                    raise RuntimeError('Qt提前退出')
            raise RuntimeError('Qt回执超时')
        try:
            first = wait_reply(300)
            if first['action']!='ready':
                raise RuntimeError('Qt初始回执不符')
            run = Path(first['run'])
            print('RUN_DIRECTORY '+str(run),flush=True)
            for i, action in enumerate(actions):
                proc.stdin.write((action+'\n').encode());proc.stdin.flush()
                reply = wait_reply()
                if reply['action']!=action:
                    raise RuntimeError('Qt动作顺序不符')
                if i<21 and reply['screen']!=expected[i]['screen']:
                    raise RuntimeError('前台原厂设置导航偏离已验证路线')
                if i==21 and reply['screen']!=0xda:
                    raise RuntimeError('正常ST没有进入原厂调参页')
                if i==22 and reply['screen']!=0x2d6:
                    raise RuntimeError('原厂调参确认没有返回上级菜单')
                if i==23 and reply['screen']!=0xd9:
                    raise RuntimeError('上级菜单没有重新进入创意外观')
                replies.append(reply)
                if i<21 or i%12==0 or action=='STOP':
                    print(json.dumps({'step':i+1,'action':action,'screen':reply.get('screen'),
                                      'command':reply.get('command_state'),'selected':reply.get('selected_filter')},ensure_ascii=False),flush=True)
            code = proc.wait(timeout=30)
            if code:
                raise RuntimeError('Qt控制器非零退出')
            source_files = [p for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py','.c')]
            source_files += [p for p in args.manifest.resolve().parent.iterdir() if p.suffix in ('.inc','.c')]
            source_files += [LAB/'tools'/name for name in ('menu_live.py','menu_bridge.py','headless_osd_capture.py','input_completion.py')]
            source_files += [LAB/'experiments/native12-410-menu/environment.py']
            sources = {str(p):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'text':p.read_text()} for p in source_files}
            (run/'observer-layout.json').write_bytes((args.manifest.resolve().parent/'observer-layout.json').read_bytes())
            (run/'qemu-service-build.json').write_bytes((args.manifest.resolve().parent/'service-build.json').read_bytes())
            (run/'validation-sources.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2)+'\n')
            (run/'validation-driver.json').write_text(json.dumps({'command':command,'exit_code':code,
                'actions':actions,'replies':replies,'camera_io':False},ensure_ascii=False,indent=2)+'\n')
            print('VALIDATION_COMPLETE '+str(run),flush=True)
        except BaseException:
            if proc.poll() is None:
                proc.stdin.close()
                try:proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.terminate();proc.wait(timeout=10)
            raise


if __name__=='__main__':
    main()
