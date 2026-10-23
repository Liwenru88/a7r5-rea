"""离屏窗口失败路径测试；此处的假会话不作为固件验收。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from PySide6.QtWidgets import QApplication
from client.window import Window


class FakeSession:
    def __init__(self):
        self.cancelled = threading.Event()
        self.executing = threading.Event()
        self.commands = []
        self.bridge = ROOT / 'runs'
        self.mode = 'starting'
        self.command_thread = None

    def status(self):
        return {'state': self.mode, 'sequence': 0}

    def frame(self):
        return None

    def command(self, request):
        self.commands.append(request)
        self.command_thread = threading.get_ident()
        self.executing.set()
        self.cancelled.wait(2)
        return {'ok': True}

    def cancel(self):
        self.cancelled.set()

    def close(self):
        self.cancel()
        return {'method': 'qmp-quit', 'exit_code': 0}


class WindowFailureContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate())

    def make(self):
        with patch('client.controller.EmulatorSession', FakeSession):
            window = Window()
            self.until(lambda: window.session is not None)
        return window

    def test_close_while_starting_waits_for_owned_thread(self):
        window = self.make()
        window.close()
        self.until(lambda: window.receipt is not None)
        self.assertTrue(window.session.cancelled.is_set())
        self.assertFalse(window.controller.thread.isRunning())
        self.assertEqual(window.session.commands, [])

    def test_busy_close_and_focus_loss_do_not_leave_host_key_held(self):
        window = self.make()
        window.session.mode = 'running'
        window.send_key('UP')
        self.until(window.session.executing.is_set)
        window.send_key('DOWN')
        window.hide()
        window.close()
        self.until(lambda: window.receipt is not None)
        self.assertEqual(window.session.commands, [{'action': 'input', 'control': 'UP', 'event': 'tap', 'value': None}])
        self.assertNotEqual(window.session.command_thread, threading.get_ident())
        self.assertFalse(window.controller.thread.isRunning())

    def test_unsupported_platform_opens_without_worker(self):
        with patch('client.window.capability', return_value={'supported': False, 'reason': '未验收平台'}):
            window = Window()
        self.assertFalse(window.controller.thread.isRunning())
        self.assertTrue(all(not button.isEnabled() for button in window.controls.buttons.values()))
        self.assertIn('未验收平台', window.state_label.text())
        window.close()


if __name__ == '__main__':
    unittest.main()
