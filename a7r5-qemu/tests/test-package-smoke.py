"""固定包验收定时器在等待 worker 时保持运行，不能误触发关闭。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from app_paths import AppPaths
from client.acceptance import attach


class FakeWindow(QObject):
    exit_ready = Signal(object)
    operation_done = Signal(object)
    session = None
    was_closed = False

    def close(self):
        self.was_closed = True


class SmokeTimerContract(unittest.TestCase):
    def test_fixed_functions_wait_for_worker_and_incomplete_exit_cannot_pass(self):
        from client.function_acceptance import attach,scenario
        self.assertTrue({'JOYSTICK_CENTER','MODE_P','C1','C2','C3'} <= {row[0] for row in scenario()})
        app=QApplication.instance() or QApplication([]);window=FakeWindow()
        with tempfile.TemporaryDirectory() as directory,patch('client.function_acceptance.paths',return_value=AppPaths(ROOT,Path(directory).resolve())):
            timer=attach(app,window)
            deadline=time.monotonic()+.15
            while time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertFalse(window.was_closed)
            window.exit_ready.emit({'method':'qmp-quit','exit_code':0})
            self.assertEqual(timer.report['status'],'failed')
            timer.stop()

    def test_waiting_for_worker_does_not_cancel_startup(self):
        app = QApplication.instance() or QApplication([])
        window = FakeWindow()
        with tempfile.TemporaryDirectory() as directory, patch('client.acceptance.paths', return_value=AppPaths(ROOT, Path(directory).resolve())):
            timer = attach(app, window)
            deadline = time.monotonic() + .3
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.005)
            timer.stop()
            self.assertFalse(window.was_closed)


if __name__ == '__main__':
    unittest.main()
