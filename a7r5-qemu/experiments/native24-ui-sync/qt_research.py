"""独立候选的真实 Qt 按钮测试台；虚拟器和串口工作均在独立进程。"""
import argparse
import json
from pathlib import Path
import select
import sys

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--unlock',action='store_true')
    parser.add_argument('--menu-isolation',action='store_true')
    parser.add_argument('--scenario',choices=('valid','bad-select-ack'),default='valid')
    args=parser.parse_args()
    app=QApplication(sys.argv)
    version=json.loads(Path(args.manifest).read_text()).get('package_source',{}).get('version','4.10')
    window=QWidget();window.setWindowTitle('A7R5 '+version+' 整合版离线菜单验证')
    layout=QVBoxLayout(window);picture=QLabel('正在启动独立客体…');picture.setFixedSize(640,480);layout.addWidget(picture)
    buttons={};bar=QHBoxLayout();layout.addLayout(bar)
    worker=QProcess(window);worker.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
    state={'ready':False,'busy':True,'run':None,'ticks':0,'operations':[]}
    for name in ('UP','DOWN','LEFT','RIGHT','ENTER','MENU','C4','MODE_M','DISP','PRIVACY','SNAPSHOT','IDLE_SHORT','IDLE_LONG','STOP'):
        button=QPushButton(name);bar.addWidget(button);buttons[name]=button;button.setEnabled(False)
        def send(checked=False,action=name):
            if state['busy']:return
            state['busy']=True
            state['operations'].append({'action':action,'source':'QTest.mouseClick -> QPushButton.clicked -> worker'})
            worker.write((json.dumps({'action':action})+'\n').encode())
        button.clicked.connect(send)
    buffer=bytearray()
    def output():
        buffer.extend(bytes(worker.readAllStandardOutput()))
        while b'\n' in buffer:
            line,_,rest=buffer.partition(b'\n');buffer[:]=rest
            if line.startswith(b'RUN_DIRECTORY '):print(line.decode(),flush=True)
            if not line.startswith(b'NATIVE410_REPLY '):continue
            response=json.loads(line[len(b'NATIVE410_REPLY '):]);state['busy']=False
            if response['action']=='ready':
                state['ready']=True;state['run']=response['run']
                image=Path(state['run'])/'native410-baseline-menu.png'
            elif response.get('stopping'):image=None
            else:image=Path(response['png'])
            if image:
                picture.setPixmap(QPixmap(str(image)))
                window.grab().save(str(Path(state['run'])/'qt-research-window.png'))
            for button in buttons.values():button.setEnabled(True)
            compact={k:v for k,v in response.items() if k!='frame'}
            if 'frame' in response:compact.update(sequence=response['frame']['sequence'],pixel=response['frame']['pixel_sha256'])
            print('QT_REPLY '+json.dumps(compact,ensure_ascii=False),flush=True)
    worker.readyReadStandardOutput.connect(output)
    def finished(code,status):
        output()
        state.update(worker_exit_code=code,worker_exit_status=str(status))
        if state['run']:
            (Path(state['run'])/'qt-research.json').write_text(json.dumps(state,indent=2)+'\n')
        print('QT_WORKER_EXIT '+str(code),flush=True)
        app.quit()
    worker.finished.connect(finished)
    def tick():
        state['ticks']+=1
        if not state['ready'] or state['busy'] or not select.select([sys.stdin],[],[],0)[0]:return
        line=sys.stdin.readline()
        if not line:
            # 控制端异常关闭也发送正常STOP，避免父进程退出后遗留虚拟器。
            timer.stop();state['busy']=True
            state['operations'].append({'action':'STOP','source':'controller EOF cleanup'})
            worker.write(b'{"action":"STOP"}\n')
            return
        action=line.strip()
        if action not in buttons:print('QT_UNKNOWN_ACTION '+action,flush=True);return
        QTest.mouseClick(buttons[action],Qt.MouseButton.LeftButton)
    timer=QTimer();timer.timeout.connect(tick);timer.start(20)
    command=[str(Path(__file__).with_name('probe_menu.py')),'--manifest',args.manifest,'--interactive','--scenario',args.scenario]
    if args.unlock:command.append('--unlock')
    if args.menu_isolation:command.append('--menu-isolation')
    window.show();worker.start(sys.executable,['-B']+command)
    app.exec()
    raise SystemExit(state.get('worker_exit_code',1))


if __name__=='__main__':main()
