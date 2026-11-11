"""以真实Qt按钮复现双组设置，导出虚拟存储供另一客体恢复。"""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
LAB=HERE.parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--log',type=Path,required=True)
    parser.add_argument('--restore',type=Path)
    args=parser.parse_args()
    route=json.loads((HERE/'route.json').read_text())['actions']
    assert route[-3:]==['LEFT','UP','RIGHT']
    command=[sys.executable,'-B',str(HERE/'qt_research.py'),'--manifest',str(args.manifest.resolve())]
    env=dict(os.environ)
    if args.restore:
        env.update(R5_SOUND_QEMU_RESTORE=str(args.restore.resolve()),R5_SOUND_QEMU_NO_CARD='1')
    with args.log.open('xb') as log:
        p=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,cwd=LAB,env=env)
        pending=bytearray();replies=[]
        def wait(timeout=180):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                while b'\n' in pending:
                    line,_,rest=pending.partition(b'\n');pending[:]=rest
                    if line.startswith(b'QT_REPLY '):return json.loads(line[9:])
                if select.select([p.stdout],[],[],.1)[0]:
                    data=os.read(p.stdout.fileno(),65536)
                    if not data and p.poll() is not None:raise RuntimeError('Qt退出前没有完成回执')
                    log.write(data);log.flush();pending.extend(data)
                elif p.poll() is not None:raise RuntimeError('Qt提前退出')
            raise RuntimeError('Qt回执超时')
        try:
            first=wait(240);assert first['action']=='ready';run=Path(first['run'])
            print('RUN_DIRECTORY '+str(run),flush=True)
            if args.restore:
                assert first['sound']['count']==2
                assert (first['sound']['mechanical_selected'],first['sound']['electronic_selected'],first['sound']['mechanical_volume'],first['sound']['electronic_volume'])==(1,2,3,8)
            def perform(action):
                p.stdin.write((action+'\n').encode());p.stdin.flush();reply=wait()
                if reply['action']!=action:raise RuntimeError('Qt回执动作不符')
                replies.append(reply)
                if action in ('ENTER','EXPORT_STORE','STOP') or len(replies)%10==0:
                    print(json.dumps({'step':len(replies),'action':action,'sound':reply.get('sound')},ensure_ascii=False),flush=True)
                return reply
            for action in route:perform(action)
            if not args.restore:
                # 从音频选项第一行进入电子组，浏览不应用，中键确认。
                for action in ['DOWN']*3+['ENTER','DOWN','DOWN']:
                    row=perform(action);assert row['sound']['electronic_selected']==0
                assert perform('ENTER')['sound']['electronic_selected']==2
                # 电子80%，机械选择第一份、30%。
                for action in ['DOWN','ENTER','DOWN','DOWN','DOWN','ENTER','DOWN','ENTER','DOWN','ENTER','DOWN','ENTER','UP','UP','ENTER']:
                    row=perform(action)
                s=row['sound'];assert (s['mechanical_selected'],s['electronic_selected'],s['mechanical_volume'],s['electronic_volume'])==(1,2,3,8)
                assert s['active_selected']==1 and s['installed_volume']==3 and s['installs']>=2
                perform('EXPORT_STORE')
            else:
                row=perform('SNAPSHOT');assert row['sound']['active_selected']==1 and row['sound']['installed_volume']==3
            # 四轮顶层MENU开关保留原有操作；不依赖旧的创建场景号。
            for _ in range(4):perform('MENU');perform('MENU')
            assert [x['screen'] for x in replies[-8:]]==[0,0x2d6]*4
            perform('STOP');code=p.wait(timeout=30)
            assert code==0
            (run/'qt-driver.json').write_text(json.dumps({'status':'PASS','restore':bool(args.restore),'command':command,'replies':replies,'exit_code':code,'camera_io':False},ensure_ascii=False,indent=2)+'\n')
            print('VALIDATION_COMPLETE '+str(run),flush=True)
        finally:
            if p.poll() is None:
                p.stdin.close()
                try:p.wait(timeout=30)
                except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=10)


if __name__=='__main__':main()
