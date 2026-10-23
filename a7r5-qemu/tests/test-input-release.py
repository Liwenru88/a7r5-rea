"""实际 shell 契约：失败仍尝试一次释放，失败状态不能被等待命令掩盖。"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from menu_live import key_command


class ReleaseContract(unittest.TestCase):
    def test_paired_tap_and_both_failures_propagate(self):
        for failed in ('none', '1', '0'):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                log = root / 'states'
                tool = root / 'inject'
                tool.write_text('#!/bin/sh\nprintf "%s\\n" "$5" >> ' + str(log) + '\n' +
                                ('exit 0\n' if failed == 'none' else '[ "$5" != "' + failed + '" ]\n'))
                tool.chmod(0o700)
                command = key_command('MENU').replace('/simulation/inject-key', str(tool)) + ' && sleep 0'
                result = subprocess.run(['/bin/sh', '-c', command], capture_output=True)
                self.assertEqual(log.read_text().splitlines(), ['1', '0'])
                self.assertEqual(result.returncode == 0, failed == 'none')


if __name__ == '__main__':
    unittest.main()
