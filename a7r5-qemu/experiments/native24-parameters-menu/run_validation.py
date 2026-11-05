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
    # 先沿已验证原厂路线进入ST，再从真实菜单导航到第一款附加滤镜。
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
            route = list(actions)
            actions = []
            def perform(action):
                i=len(actions)
                proc.stdin.write((action+'\n').encode());proc.stdin.flush()
                reply = wait_reply()
                if reply['action']!=action:
                    raise RuntimeError('Qt动作顺序不符')
                if i<21 and reply['screen']!=expected[i]['screen']:
                    raise RuntimeError('前台原厂设置导航偏离已验证路线')
                actions.append(action)
                replies.append(reply)
                if i<21 or i%8==0 or action in ('STOP','RIGHT','ENTER'):
                    print(json.dumps({'step':i+1,'action':action,'screen':reply.get('screen'),
                                      'command':reply.get('command_state'),'tune':reply.get('tune')},ensure_ascii=False),flush=True)
                return reply
            for action in route:
                reply=perform(action)
            for _ in range(24):
                reply=perform('UP')
            if reply.get('tune',{}).get('slot')!=1:
                raise RuntimeError('原菜单未导航到第一款附加配方')
            reply=perform('RIGHT')
            if reply['screen']!=0xda or reply.get('tune',{}).get('slot')!=1:
                raise RuntimeError('附加滤镜未进入原调参页')
            initial=reply['tune']['values']
            if any(v==-2147483648 for v in initial):
                raise RuntimeError('调参工作值尚未建立')
            expected_values=list(initial)
            steps=[]
            high=(9,9,9,9,9,9,5,9)
            for p in range(8):
                action='UP' if expected_values[p]<high[p] else 'DOWN'
                expected_values[p]+=1 if action=='UP' else -1
                reply=perform(action)
                if reply['screen']!=0xda or reply['tune']['values']!=expected_values:
                    raise RuntimeError('原调参按键与八项工作值不符：'+str(p))
                if reply['tune']['defaults']!=initial:
                    raise RuntimeError('调节修改了导入默认值')
                steps.append({'parameter':p,'action':action,'values':list(expected_values),'png':reply['png']})
                if p<7:perform('RIGHT')
            reply=perform('ENTER')
            if reply['screen']!=0x2d6:
                raise RuntimeError('原调参确认未回到上级菜单')
            reply=perform('ENTER')
            for _ in range(43):
                if reply.get('tune',{}).get('slot')==1:break
                reply=perform('UP')
            reply=perform('RIGHT')
            if reply['screen']!=0xda or reply['tune']['values']!=expected_values:
                raise RuntimeError('重新进入附加滤镜丢失工作值')
            reply=perform('C4')
            if reply['tune']['values']!=initial:
                if reply['screen']!=0x44c:
                    raise RuntimeError('原重置确认框未出现')
                perform('UP')
                reply=perform('ENTER')
                reply=perform('SNAPSHOT')
            if reply['tune']['values']!=initial or reply['tune']['defaults']!=initial:
                raise RuntimeError('原重置操作未恢复当前配方的独立基准')
            for _ in range(5):
                reply=perform('MENU')
                if reply['screen']==0x2d6:break
            if reply['screen']!=0x2d6:
                raise RuntimeError('菜单退出未回到上级')
            for _ in range(4):
                if perform('MENU')['screen']!=0 or perform('MENU')['screen']!=0x2d6:
                    raise RuntimeError('顶层MENU往返不符')
            perform('ENTER')
            perform('STOP')
            (run/'parameter-validation.json').write_text(json.dumps({'status':'PASS','initial':initial,
                'working_before_reset':expected_values,'steps':steps,'reopen_preserved':True,
                'reset_verified':True,'camera_io':False,
                'boundary':'真实AP工作模型和原Qt页面；不代表E4完成、保存或成像成功'},ensure_ascii=False,indent=2)+'\n')
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
