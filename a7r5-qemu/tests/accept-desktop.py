"""在真实 Qt 事件循环中验证菜单、后台响应、帧来源和正常退出。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from client.window import Window


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default='logs/desktop-implementation/qt-acceptance.json')
    args = parser.parse_args()
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    start = time.monotonic()
    history = json.loads((ROOT / 'evidence/history/logs/native-reentry-acceptance.json').read_text())
    expected = history['navigation']
    if isinstance(expected, dict):
        expected = expected['frames']
    keys = ['C4', 'ENTER'] + ['MENU'] * 8 + ['RIGHT', 'DOWN', 'ENTER', 'UP', 'LEFT', 'MENU']
    report = {'status': 'running', 'heartbeats': 0, 'operations': [], 'frames': [], 'errors': []}
    report_path = ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    clicked_at = None
    index = 0
    idle_start = None
    initial = None
    closed_hash = None
    idle_hash = None
    pending = False
    exiting = False

    def fail(error):
        nonlocal exiting
        exiting = True
        report['errors'].append(str(error))
        report['status'] = 'failed'
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        if not window.closing:
            window.close()

    def frame(state):
        report['frames'].append(state)

    def done(result):
        nonlocal pending, index, closed_hash
        try:
            state = window.session.status()
            pixel = state['pixel_sha256']
            if index == 0:
                assert pixel == '2b9fb0a0278266fa0b30ea249523d0d317b56fb8bbbccaf4e8c5b1f4d171c868'
                assert state['input_context'] == 'guide'
            elif index == 1:
                assert pixel == initial and state['input_context'] == 'menu'
            elif index < 10:
                if index % 2 == 0:
                    assert pixel != initial
                    closed_hash = closed_hash or pixel
                    assert pixel == closed_hash
                else:
                    assert pixel == initial
            else:
                assert pixel == expected[index - 9]['pixel_sha256'], (keys[index], pixel)
            report['operations'].append({'key': keys[index], 'pixel_sha256': pixel,
                                         'click_to_display_ms': round((time.perf_counter()-clicked_at)*1000, 3)})
            index += 1
            pending = False
        except Exception as error:
            fail(error)

    def exit_ready(receipt):
        report['cleanup'] = receipt
        try:
            assert receipt == {'method': 'qmp-quit', 'exit_code': 0}, receipt
            run = Path(window.session.status()['run'])
            spec = importlib.util.spec_from_file_location('cycles', ROOT / 'tests/check-menu-cycles.py')
            cycles = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cycles)
            frames, result = cycles.saved_frames(run.name, prefix='live-')
            assert len(frames) == 17
            report['verified_raw_frames'] = frames
            assert len(report['operations']) == 16 and report['heartbeats'] > 50
            report['status'] = 'verified'
        except Exception as error:
            report['errors'].append(str(error))
            report['status'] = 'failed'
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        QTimer.singleShot(100, app.quit)

    def tick():
        nonlocal idle_start, initial, idle_hash, pending, exiting, clicked_at
        report['heartbeats'] += 1
        try:
            if time.monotonic() - start > 360:
                raise TimeoutError('Qt 验收超过总时间限制')
            if exiting or not window.session:
                return
            state = window.session.status()
            if state['state'] in ('failed', 'stopped') or state.get('error'):
                raise RuntimeError(state)
            if pending:
                return
            if state['state'] != 'running' or not window.sequence:
                return
            report['run'] = state['run']
            report['bridge'] = str(window.session.bridge)
            run = Path(state['run'])
            if idle_start is None:
                initial = state['pixel_sha256']
                idle_hash = hashlib.sha256((run / 'console.log').read_bytes()).hexdigest()
                idle_start = time.monotonic()
                window.grab().save(str(ROOT / 'logs/desktop-implementation/qt-menu.png'))
                return
            if index == 0:
                if time.monotonic() - idle_start < 5:
                    return
                assert hashlib.sha256((run / 'console.log').read_bytes()).hexdigest() == idle_hash
                assert json.loads((run / 'native-runtime-state.json').read_text())['paused_for_input']
                report['idle_seconds'] = 5
            if index == len(keys):
                exiting = True
                QTest.mouseClick(window.quit_button, Qt.MouseButton.LeftButton)
                return
            pending = True
            button = (window.controls.physical_buttons['C4'] if keys[index] == 'C4'
                      else window.controls.buttons[keys[index]])
            # 机身页 C4 的可点击性也在真实窗口布局内验证。
            if keys[index] == 'C4':
                from PySide6.QtWidgets import QTabWidget
                window.controls.findChild(QTabWidget).setCurrentIndex(1)
                window.controls.findChild(__import__('PySide6.QtWidgets',fromlist=['QScrollArea']).QScrollArea).ensureWidgetVisible(button)
            else:
                from PySide6.QtWidgets import QTabWidget
                window.controls.findChild(QTabWidget).setCurrentIndex(0)
            assert button.isEnabled(), keys[index]
            clicked_at = time.perf_counter()
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        except Exception as error:
            traceback.print_exc()
            fail(error)

    window.frame_ready.connect(frame)
    window.operation_done.connect(done)
    window.exit_ready.connect(exit_ready)
    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(tick)
    timer.start()
    app.exec()
    print(json.dumps({k: v for k, v in report.items() if k not in ('frames', 'verified_raw_frames')}, indent=2), flush=True)
    if report['status'] != 'verified':
        raise RuntimeError('Qt 验收未通过')


if __name__ == '__main__':
    main()
