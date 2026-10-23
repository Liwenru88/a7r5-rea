"""不启动固件的会话所有权、失败路径及资源边界回归。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from emu_session import EmulatorSession
from app_paths import AppPaths
from platform_backend import capability


class SessionContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.session = EmulatorSession.__new__(EmulatorSession)
        self.session.bridge = self.root / 'ui-test'
        self.session.bridge.mkdir()
        self.session.lock = threading.Lock()
        self.session.closing = threading.Event()
        self.session.process = Mock()
        self.session.process.poll.return_value = None
        self.session.process.wait.return_value = 0
        self.session.log = Mock()
        self.state('running')

    def tearDown(self):
        self.temp.cleanup()

    def state(self, state):
        (self.session.bridge / 'status.json').write_text(json.dumps({'state': state, 'sequence': 0}))

    def test_web_and_desktop_share_one_session(self):
        spec = importlib.util.spec_from_file_location('web', ROOT / 'tools/menu-ui.py')
        web = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(web)
        self.assertIs(web.Session, EmulatorSession)

    def test_unknown_payloads_never_dispatch(self):
        for payload in ({'action': 'shell', 'key': 'reboot'}, {'action': 'key', 'key': []},
                        {'action': 'key', 'key': 'UP; reboot'}, {'action': 'key', 'key': 'DELETE'}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.session.command(payload)
        self.assertFalse((self.session.bridge / 'request.json').exists())

    def test_closed_busy_starting_and_duplicate_reject(self):
        for state in ('starting', 'failed', 'stopping', 'stopped'):
            self.state(state)
            with self.subTest(state=state), self.assertRaises(BlockingIOError):
                self.session.command({'action': 'key', 'key': 'UP'})
        self.state('running')
        self.session.lock.acquire()
        with self.assertRaises(BlockingIOError):
            self.session.command({'action': 'key', 'key': 'UP'})
        self.session.lock.release()
        (self.session.bridge / 'request.json').write_text('{}')
        with self.assertRaises(FileExistsError):
            self.session.command({'action': 'key', 'key': 'UP'})
        self.session.cancel()
        with self.assertRaises(BlockingIOError):
            self.session.command({'action': 'key', 'key': 'UP'})

    def test_timeout_cancels_without_second_request(self):
        with self.assertRaises(TimeoutError):
            self.session.command({'action': 'key', 'key': 'UP'}, timeout=.02)
        self.assertTrue((self.session.bridge / 'cancel').exists())
        self.assertTrue(self.session.closing.is_set())
        self.assertEqual(len(list(self.session.bridge.glob('request.json'))), 1)

    def test_exit_requires_receipt_and_owned_process_wait(self):
        run = self.root / 'native-app-test'
        run.mkdir()
        (self.session.bridge / 'started').write_text(str(run))
        for receipt in ({'method': 'qmp-quit', 'exit_code': 0},
                        {'method': 'owned-group-term', 'exit_code': -15}):
            (run / 'exit.json').write_text(json.dumps(receipt))
            if receipt['method'] == 'qmp-quit':
                self.assertEqual(self.session.close(), receipt)
            else:
                with self.assertRaises(RuntimeError):
                    self.session.close()
        self.session.process.wait.assert_called()
        self.session.process.wait.side_effect = subprocess.TimeoutExpired('owned-worker', 1)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.session.close(timeout=1)

    def test_stale_or_unchecked_png_not_displayed(self):
        png = b'frame'
        file = self.session.bridge / 'frame.png'
        file.write_bytes(png)
        state = {'state': 'running', 'sequence': 1, 'png_sha256': hashlib.sha256(png).hexdigest()}
        (self.session.bridge / 'status.json').write_text(json.dumps(state))
        self.assertEqual(self.session.frame(), (state, png))
        file.write_bytes(b'changed')
        self.assertIsNone(self.session.frame())

    def test_failed_worker_cannot_be_reported_as_normal_exit(self):
        run = self.root / 'native-app-test'
        run.mkdir()
        (self.session.bridge / 'started').write_text(str(run))
        (run / 'exit.json').write_text('{"method":"qmp-quit","exit_code":0}')
        self.session.process.wait.return_value = 1
        with self.assertRaisesRegex(RuntimeError, '工作进程'):
            self.session.close()

    def test_unsupported_platform_and_symlink_data(self):
        for system, machine in (('win32', 'AMD64'), ('linux', 'aarch64'), ('darwin', 'x86_64')):
            self.assertFalse(capability(system, machine)['supported'])
        link = self.root / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            AppPaths(ROOT, link).prepare()


if __name__ == '__main__':
    unittest.main()
