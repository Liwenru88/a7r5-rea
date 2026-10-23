"""用真实 Qt 点击验证选项帮助、设置回读、八类菜单及正常退出。"""
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabWidget, QScrollArea
from client.window import Window


def main():
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    evidence = ROOT/'logs/function-expansion'
    target = evidence/'qt-functions.json'
    reference = ROOT/'runs/native-app-4apfb8fm'
    def expected(index):
        return json.loads(next(reference.glob('live-%04d-*.json' % index)).read_text())['pixel_sha256']
    # 每个期望均来自已单独查看的原厂客体帧；未绘制替代菜单。
    scenario = [(key, None, None) for key in ['DOWN']*5]
    scenario += [('ENTER', expected(6), 'menu_option'), ('C4', None, 'guide'),
                 ('ENTER', expected(6), 'menu_option'), ('UP', None, 'menu_option'),
                 ('ENTER', expected(8), 'menu'), ('ENTER', expected(9), 'menu_option'),
                 ('DOWN', None, 'menu_option'), ('ENTER', expected(11), 'menu'),
                 ('ENTER', expected(12), 'menu_option'), ('MENU', expected(13), 'menu')]
    scenario += [('MENU', expected(14 if index % 2 == 0 else 15),
                  'shooting' if index % 2 == 0 else 'menu') for index in range(8)]
    scenario += [('LEFT', None, None)]*2
    scenario += [('UP', expected(index), None) for index in range(18,26)]
    report = {'status': 'running', 'operations': [], 'errors': [], 'heartbeats': 0,
              'scope': 'real firmware UI; settings in guest RAM only'}
    started = time.monotonic()
    pending = False
    stopping = False
    clicked_at = None

    def save():
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')

    def fail(error):
        nonlocal stopping
        report['errors'].append(str(error) or repr(error))
        report['status'] = 'failed'
        stopping = True
        save()
        window.close()

    def done(result):
        nonlocal pending
        try:
            index = len(report['operations'])
            key, pixel, context = scenario[index]
            state = window.session.status()
            if pixel:
                assert state['pixel_sha256'] == pixel, (index, key, state['pixel_sha256'], pixel)
            if context:
                assert state['input_context'] == context, (index, state['input_context'], context)
            report['operations'].append({'index': index, 'key': key, 'pixel_sha256': state['pixel_sha256'],
                'context': state['input_context'],
                'click_to_display_ms': round((time.perf_counter()-clicked_at)*1000,3)})
            if index in (6,10,13,32):
                window.grab().save(str(evidence/('qt-function-%02d.png' % index)))
            pending = False
            save()
        except Exception as error:
            traceback.print_exc()
            fail(error)

    def exited(receipt):
        report['cleanup'] = receipt
        try:
            assert not report['errors'], report['errors']
            assert len(report['operations']) == len(scenario)
            assert receipt == {'method':'qmp-quit','exit_code':0}, receipt
            spec = importlib.util.spec_from_file_location('cycles', ROOT/'tests/check-menu-cycles.py')
            cycles = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cycles)
            frames, _ = cycles.saved_frames(Path(report['run']).name, prefix='live-')
            assert len(frames) == len(scenario)+1
            report['verified_raw_frames'] = frames
            report['status'] = 'verified'
        except Exception as error:
            report['status'] = 'failed'
            report['errors'].append(str(error) or repr(error))
        save()
        QTimer.singleShot(100, app.quit)

    def tick():
        nonlocal pending, stopping, clicked_at
        report['heartbeats'] += 1
        try:
            if time.monotonic()-started > 360:
                raise TimeoutError('菜单设置验收超时')
            if stopping or not window.session:
                return
            state = window.session.status()
            if state['state'] in ('failed','stopped') or state.get('error'):
                raise RuntimeError(state)
            if pending or state['state'] != 'running' or not window.sequence:
                return
            report['run'] = state['run']
            index = len(report['operations'])
            if index == len(scenario):
                stopping = True
                QTest.mouseClick(window.quit_button, Qt.MouseButton.LeftButton)
                return
            key = scenario[index][0]
            tabs = window.controls.findChild(QTabWidget)
            tabs.setCurrentIndex(1 if key == 'C4' else 0)
            button = window.controls.physical_buttons['C4'] if key == 'C4' else window.controls.buttons[key]
            if key == 'C4':
                window.controls.findChild(QScrollArea).ensureWidgetVisible(button)
            assert button.isEnabled(), (index, key, state.get('input_context'))
            pending = True
            clicked_at = time.perf_counter()
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        except Exception as error:
            traceback.print_exc()
            fail(error)

    window.operation_done.connect(done)
    window.exit_ready.connect(exited)
    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(tick)
    timer.start()
    app.exec()
    print(json.dumps({key: value for key,value in report.items() if key != 'verified_raw_frames'}, ensure_ascii=False, indent=2))
    if report['status'] != 'verified':
        raise RuntimeError('菜单设置 Qt 验收失败')


if __name__ == '__main__':
    main()
