"""执行结果必须完整且逐项符合参考值；退出码或结束文字不能单独放行。"""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from cp_native_probe import reference, verify_output, run, SLOTS


class NativeCPContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows=[b'CP_NATIVE_MATRIX_BEGIN version=1 synthetic_parameters=1']
        for profile in (*range(257),0xffffffff):
            for slot in SLOTS:
                for cal in range(3):
                    rows.append(f'CP_MATRIX profile={profile:08x} slot={slot:08x} calibration={cal} data={reference(profile,slot,cal).hex()}'.encode())
        rows.append(b'CP_NATIVE_MATRIX_END cases=00000c18')
        cls.rows=rows
        cls.raw=b'\n'.join(rows)+b'\n'

    def test_complete_contract(self):
        result=verify_output(self.raw)
        self.assertEqual(result['native_instruction_cases'],3096)
        self.assertFalse(result['CP_RTOS_booted'])
        self.assertFalse(result['ISP_pixels_verified'])
        # 首分组的六个输入为 -512,-481,-450,-419,-388,-357。
        self.assertEqual(reference(0,0,0)[:18],struct.pack('<9h',-993,512,481,450,-869,419,388,357,-745))

    def test_truncated_duplicate_reordered_or_corrupt_output_rejected(self):
        bad_rows=list(self.rows);bad_rows[1],bad_rows[2]=bad_rows[2],bad_rows[1]
        corrupt=bytearray(self.raw);at=corrupt.index(b'data=')+5;corrupt[at]=ord('0') if corrupt[at]!=ord('0') else ord('1')
        for raw in (self.raw[:80],self.raw+b'CP_NATIVE_MATRIX_END cases=00000c18\n',
                    b'\n'.join(bad_rows),bytes(corrupt),b'\n'.join(self.rows[:2]+self.rows[3:])):
            with self.subTest(length=len(raw)),self.assertRaises(ValueError):
                verify_output(raw)

    def test_unbounded_observation_is_rejected_before_io(self):
        for value in (0,49,2001,True,1.5):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'50至2000'):
                run(Path('/does-not-exist'),boot_trace=True,observe_ms=value)


if __name__=='__main__':unittest.main()
