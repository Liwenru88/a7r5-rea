"""真实Qt按钮→独立工作进程→原厂按键；不向客体开放任意命令。"""
import argparse
import json
from pathlib import Path
import select
import sys

from PySide6.QtCore import QProcess,QTimer,Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QPushButton,QVBoxLayout,QHBoxLayout

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True);parser.add_argument('--attach',action='store_true')
    parser.add_argument('--seed-c07',action='store_true')
    parser.add_argument('--names-fixture',action='store_true')
    parser.add_argument('--storage',action='store_true')
    parser.add_argument('--media',action='store_true');parser.add_argument('--chinese',action='store_true')
    args=parser.parse_args();app=QApplication(sys.argv);window=QWidget();window.setWindowTitle('A7R5 4.06 自定义滤镜离线验证')
    layout=QVBoxLayout(window);picture=QLabel('正在启动独立客体…');picture.setFixedSize(640,480);layout.addWidget(picture)
    bar=QHBoxLayout();layout.addLayout(bar);buttons={};state={'busy':True,'ready':False,'run':None,'ticks':0,'operations':[]}
    worker=QProcess(window);worker.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
    for name in ('UP','DOWN','LEFT','RIGHT','ENTER','MENU','C4','MODE_M','DISP','PRIVACY','SNAPSHOT','NAME_EN','NAME_ZH','NAME_TOMBSTONE','RESET_ARM','RESET_VERIFY_CANCEL','RESET_VERIFY_CONFIRM','CONFIG_COPY20','STORE_SNAPSHOT','STORE_EXPORT','STORE_FILL','STOP'):
        button=QPushButton(name);bar.addWidget(button);buttons[name]=button;button.setEnabled(False)
        def send(checked=False,action=name):
            if state['busy']:return
            state['busy']=True;state['operations'].append({'action':action,'source':'QTest.mouseClick -> QPushButton.clicked -> worker'})
            worker.write((json.dumps({'action':action})+'\n').encode())
        button.clicked.connect(send)
    buffer=bytearray()
    def output():
        buffer.extend(bytes(worker.readAllStandardOutput()))
        while b'\n' in buffer:
            line,_,rest=buffer.partition(b'\n');buffer[:]=rest
            if not line.startswith(b'UI406_REPLY '):print(line.decode(errors='replace'),flush=True);continue
            row=json.loads(line[len(b'UI406_REPLY '):]);state['busy']=False
            if row['action']=='ready':state.update(ready=True,run=row['run'])
            if row.get('png'):
                picture.setPixmap(QPixmap(row['png']));window.grab().save(str(Path(state['run'])/'qt-research-window.png'))
            for button in buttons.values():button.setEnabled(True)
            print('QT_REPLY '+json.dumps({k:v for k,v in row.items() if k!='frame'},ensure_ascii=False),flush=True)
    worker.readyReadStandardOutput.connect(output)
    def finished(code,status):
        output();state.update(worker_exit_code=code,worker_exit_status=str(status))
        if state['run']:(Path(state['run'])/'qt-research.json').write_text(json.dumps(state,indent=2)+'\n')
        print('QT_WORKER_EXIT '+str(code),flush=True);app.quit()
    worker.finished.connect(finished)
    def tick():
        state['ticks']+=1
        if not state['ready'] or state['busy'] or not select.select([sys.stdin],[],[],0)[0]:return
        line=sys.stdin.readline()
        if not line:return
        action=line.strip()
        if action not in buttons:print('QT_UNKNOWN_ACTION '+action,flush=True);return
        QTest.mouseClick(buttons[action],Qt.MouseButton.LeftButton)
    timer=QTimer();timer.timeout.connect(tick);timer.start(20)
    command=[str(Path(__file__).with_name('probe_menu.py')),'--manifest',args.manifest]
    if args.attach:command.append('--attach')
    if args.seed_c07:command.append('--seed-c07')
    if args.names_fixture:command.append('--names-fixture')
    if args.storage:command.append('--storage')
    if args.media:command.append('--media')
    if args.chinese:command.append('--chinese')
    window.show();worker.start(sys.executable,['-B',*command]);app.exec()
    raise SystemExit(state.get('worker_exit_code',1))

if __name__=='__main__':main()
