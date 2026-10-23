"""应用包固定冒烟流程：启动、真实帧、一次 MENU 和窗口退出。"""
import hashlib
import json
import time
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from app_paths import paths


def attach(application, window):
    report = {'status': 'running', 'mode': 'frozen-desktop-smoke', 'heartbeats': 0}
    data = paths().prepare().data
    target = data / 'package-smoke.json'
    start = time.monotonic()
    initial = None
    sent = False
    stopping = False
    timer = QTimer(window)
    timer.setInterval(100)

    def save():
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    def stop(error=None):
        nonlocal stopping
        if stopping:
            return
        stopping = True
        if error:
            report['error'] = str(error)
        window.close()

    def tick():
        nonlocal initial, sent, stopping
        report['heartbeats'] += 1
        try:
            if time.monotonic() - start > 240:
                raise TimeoutError('应用包启动/帧验收超过固定上限')
            if stopping or not window.session:
                return
            state = window.session.status()
            if state['state'] == 'failed':
                raise RuntimeError(state)
            if state['state'] != 'running' or not window.sequence:
                return
            report.update(run=state['run'], bridge=str(window.session.bridge))
            if initial is None:
                initial = state['pixel_sha256']
                report['initial_pixel_sha256'] = initial
                report['initial_png_sha256'] = state['png_sha256']
                window.grab().save(str(data / 'package-menu.png'))
                save()
                sent = True
                QTest.mouseClick(window.controls.buttons['MENU'], Qt.MouseButton.LeftButton)
            elif sent and not window.busy:
                if state['pixel_sha256'] == initial:
                    return
                report['menu_closed_pixel_sha256'] = state['pixel_sha256']
                QTest.mouseClick(window.quit_button, Qt.MouseButton.LeftButton)
                stopping = True
        except Exception as error:
            stop(error)

    def exited(receipt):
        report['cleanup'] = receipt
        report['status'] = 'verified' if (not report.get('error') and report.get('menu_closed_pixel_sha256') and
                                         receipt == {'method': 'qmp-quit', 'exit_code': 0}) else 'failed'
        report['elapsed_seconds'] = time.monotonic() - start
        save()
        QTimer.singleShot(100, application.quit)

    window.exit_ready.connect(exited)
    timer.timeout.connect(tick)
    timer.start()
    timer.report = report
    save()
    return timer
