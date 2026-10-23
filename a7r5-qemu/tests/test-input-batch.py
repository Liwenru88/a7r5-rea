"""消费端证据要求精确来源、按下/释放顺序和旋转增量。"""
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import Mock, patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import input_batch
from input_batch import received
from menu_live import RESEARCH_KEYS, KEYS, SINGLE_STATUS, key_command


def event(code, status, source='0x92840747'):
    return (f'OBS A7R5_INPUT_RECEIVED tid=1 queue=0x807a0020 source={source} '
            f'key_code={code} sub=0 status={status} ex=0 from=0x1\n').encode()


class ReceiptContract(unittest.TestCase):
    def test_candidate_mapping_is_explicit_and_not_added_to_default_controls(self):
        for key, code in RESEARCH_KEYS.items():
            with self.subTest(key=key):
                self.assertNotIn(key, KEYS)
                data = event(code,SINGLE_STATUS[key]) if key in SINGLE_STATUS else event(code, '0x1') + event(code, '0')
                expected=[int(SINGLE_STATUS[key],0)] if key in SINGLE_STATUS else [1,0]
                self.assertEqual(received(data, key, RESEARCH_KEYS), expected)
                with self.assertRaises(KeyError):
                    received(data, key)
                self.assertIn(' '+code+' 0 '+(SINGLE_STATUS[key] if key in SINGLE_STATUS else '1')+' 0 1', key_command(key))

    def test_consumed_tap_and_rotation_are_distinct(self):
        self.assertEqual(received(event('0x1f8', '0x1') + event('0x1f8', '0'), 'DELETE'), [1, 0])
        self.assertEqual(received(event('0x10000013', '0xfffffc00'), 'REAR_LEFT'), [0xfffffc00])

    def test_shell_prompt_and_late_release_do_not_require_another_key(self):
        press=event('0x1f8','0x1');release=b'/ # '+event('0x1f8','0')
        self.assertEqual(received(press+release,'C4'),[1,0])
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'console.log';p.write_bytes(press)
            vm=Mock(console=p);vm.process.poll.return_value=None
            def advance(_):p.write_bytes(press+release)
            with patch('input_batch.time.sleep',side_effect=advance):
                self.assertEqual(input_batch.wait_research_receipt(vm,'C4',0,0)['received'],[1,0])
            vm.command.assert_not_called()

    def test_late_receipt_still_stops_on_missing_duplicate_and_firmware_fault(self):
        for data in (event('0x1f8','0x1'),event('0x1f8','0x1')*2+event('0x1f8','0')):
            with tempfile.TemporaryDirectory() as folder:
                p=Path(folder)/'console.log';p.write_bytes(data);vm=Mock(console=p);vm.process.poll.return_value=None
                with self.assertRaises(RuntimeError):input_batch.wait_research_receipt(vm,'C4',0,0,timeout=.01)
                vm.command.assert_not_called()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'console.log';p.write_bytes(b'Entering exception monitor.\n');vm=Mock(console=p)
            from menu_live import FirmwareFault
            with self.assertRaises(FirmwareFault):input_batch.wait_research_receipt(vm,'C4',0,0)
            vm.command.assert_not_called()

    def test_recognized_kernel_records_do_not_erase_a_real_release(self):
        press = event('0x1ac', '0x1')
        release = event('0x1ac', '0')
        kernel = b'[  680.989562] [K]**UIPC ERROR** osal_snd_msg: No snd_msg registered. Skip snd to 0x86f\n'
        for data in (press + release[:-1] + kernel + b'\n',
                     press + release[:90] + kernel + release[90:]):
            with self.subTest(data=data):
                self.assertEqual(received(data, 'ENTER'), [1, 0])
        for data in (press + kernel, press + release[:-1] + b'Entering exception monitor.\n'):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                received(data, 'ENTER')

    def test_missing_release_duplicate_wrong_source_and_wrong_increment_stop(self):
        invalid = [event('0x1f8', '0x1'), event('0x1f8', '0') + event('0x1f8', '0x1'),
                   event('0x1f8', '0x1') * 2 + event('0x1f8', '0'),
                   event('0x1f8', '0x1', '0x123') + event('0x1f8', '0', '0x123')]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                received(data, 'DELETE')
        with self.assertRaises(RuntimeError):
            received(event('0x10000013', '0x400'), 'REAR_LEFT')


if __name__ == '__main__':
    unittest.main()
