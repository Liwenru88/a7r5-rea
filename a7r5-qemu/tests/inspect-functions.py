"""受限 Qt 研究会话：仅六键与退出，不开放 shell 或候选键码。"""
import json
import re
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from client.window import Window
from menu_bridge import atomic_json


def main():
    directory = ROOT / 'logs/function-expansion' / ('inspect-'+uuid.uuid4().hex)
    directory.mkdir()
    atomic_json(directory.parent/'inspection.json', {'directory': str(directory)})
    app = QApplication(sys.argv)
    window = Window()
    # 研究阶段不展示窗口，避免人工点击与记录中的固定动作混合；最终另做可见窗口验收。
    start = time.monotonic()
    pending = None
    closing = False

    def status(**extra):
        state = window.session.status() if window.session else {'state': 'starting'}
        atomic_json(directory/'status.json', dict(state, **extra))

    def completed(result):
        nonlocal pending
        if pending:
            atomic_json(directory/('reply-'+pending['id']+'.json'), {'ok': True, 'result': result,
                                                                    'state': window.session.status()})
            pending = None

    def exited(receipt):
        status(cleanup=receipt)
        atomic_json(directory/'exit.json', receipt)
        QTimer.singleShot(100, app.quit)

    def tick():
        nonlocal pending, closing
        try:
            status()
            state = window.session.status() if window.session else {'state': 'starting'}
            if time.monotonic()-start > 1200 or state.get('error') or state['state'] == 'failed':
                closing = True; window.close(); return
            path = directory/'request.json'
            if closing or pending or not path.exists() or state['state'] != 'running' or not window.sequence:
                return
            if path.is_symlink() or path.stat().st_size > 128:
                raise ValueError('研究请求文件不符')
            request = json.loads(path.read_text())
            if set(request) != {'id', 'key'} or not isinstance(request['id'], str) or not re.fullmatch('[0-9a-f]{32}', request['id']):
                raise ValueError('研究请求结构不符')
            path.rename(directory/('request-'+request['id']+'.json'))
            if request['key'] == 'STOP':
                closing = True; window.close(); return
            if request['key'] not in ('UP','DOWN','LEFT','RIGHT','ENTER','MENU'):
                raise ValueError('仅接受六个已验证菜单键')
            pending = request
            QTest.mouseClick(window.controls.buttons[request['key']], Qt.MouseButton.LeftButton)
        except Exception as error:
            atomic_json(directory/'error.json', {'error': str(error)})
            closing = True; window.close()

    window.operation_done.connect(completed)
    window.exit_ready.connect(exited)
    timer = QTimer(); timer.setInterval(50); timer.timeout.connect(tick); timer.start()
    app.exec()
    if not (directory/'exit.json').exists() or (directory/'error.json').exists():
        raise RuntimeError('研究会话没有取得正常结果')


if __name__ == '__main__':
    main()
