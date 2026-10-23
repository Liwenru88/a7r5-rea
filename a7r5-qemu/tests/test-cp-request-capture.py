"""用真实 C 生产器验证完整捕获；截断、损坏、未提交及序列缺口必须拒绝。"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB/'tools'))
from cp_request_capture import decode_capture, export_capture, CAPTURE_BYTES


class CaptureContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix='cp-capture-test-', dir=LAB/'build')
        cls.binary = Path(cls.folder.name)/'capture'
        command = ['/usr/bin/clang', '-O1', '-g', '-fsanitize=address,undefined',
                   str(LAB/'tests/test-cp-request-capture.c'), '-o', str(cls.binary)]
        subprocess.run(command, check=True, capture_output=True)
        cls.raw = subprocess.run([str(cls.binary)], check=True, capture_output=True).stdout

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_c_producer_preserves_complete_request_and_is_observation_only(self):
        records = decode_capture(self.raw)
        expected = bytearray((i*37+9)&255 for i in range(2400))
        expected[:8] = bytes.fromhex('0500634003000080')
        self.assertEqual([row['payload'] for row in records], [bytes(expected)])
        self.assertEqual(records[0]['bytes'], 2400)
        self.assertEqual(len(self.raw), CAPTURE_BYTES)

    def test_partial_corrupt_or_wrong_identity_is_not_accepted(self):
        for offset in (0, 8, 12, 16, 20, 24, 28, 32, 40, 64, 64+2399, 4095):
            with self.subTest(offset=offset):
                bad = bytearray(self.raw)
                bad[offset] ^= 1
                with self.assertRaises(ValueError):
                    decode_capture(bad)
        for raw in (self.raw[:80], self.raw[:-1], bytes(CAPTURE_BYTES)):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                decode_capture(raw)

    def test_sequence_gap_is_rejected(self):
        bad = bytearray(CAPTURE_BYTES)
        bad[4096:8192] = self.raw[:4096]
        with self.assertRaisesRegex(ValueError, '不连续'):
            decode_capture(bad)

    def test_qmp_export_issues_no_guest_command_and_preserves_failure(self):
        for broken in (False,True):
            with self.subTest(broken=broken),tempfile.TemporaryDirectory(dir=LAB/'build') as folder:
                import json
                root=Path(folder);vm=Mock(out=root)
                raw=self.raw[:-1] if broken else self.raw
                class Stream:
                    def __init__(self):self.replies=[b'{"QMP":{}}\n']
                    def __enter__(self):return self
                    def __exit__(self,*args):pass
                    def write(self,request):
                        request=json.loads(request)
                        if request['execute']=='pmemsave':
                            self_target=Path(request['arguments']['filename'])
                            self_target.write_bytes(raw)
                        self.replies.append(b'{"return":{}}\n')
                    def flush(self):pass
                    def readline(self):return self.replies.pop(0)
                sock=Mock();sock.__enter__=Mock(return_value=sock);sock.__exit__=Mock()
                sock.makefile.return_value=Stream()
                with patch('cp_request_capture.socket.socket',return_value=sock):
                    if broken:
                        with self.assertRaises(ValueError):export_capture(vm)
                        self.assertFalse((root/'cp-init-capture.json').exists())
                    else:
                        result=export_capture(vm)
                        self.assertEqual(result['guest_commands_after_failure'],0)
                        self.assertEqual(result['CP_replies_added'],0)
                        self.assertFalse(result['CP_firmware_running'])
                        self.assertEqual((root/'cp-init-00.bin').read_bytes(),decode_capture(raw)[0]['payload'])
                self.assertTrue((root/'cp-init-reserved.bin').exists())
                vm.command.assert_not_called()
                vm.set_native_paused.assert_called_once_with(True)


if __name__ == '__main__':
    unittest.main()
