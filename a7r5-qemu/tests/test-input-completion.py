"""收到输入、提交新帧和原厂界面处理完成是三个不同阶段。"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from input_completion import completed_sequence


def row(key,status,sequence):
    return f'OBS A7R5_INPUT_COMPLETED key={key} status={status} frame_sequence={sequence} result=0\n'.encode()


class CompletionContract(unittest.TestCase):
    def test_paired_ui_completion_and_rotations_use_their_own_sequence(self):
        self.assertEqual(completed_sequence(row('0x13','0x1',100)+row('0x13','0',102),'MENU'),102)
        self.assertEqual(completed_sequence(row('0x2f5','0x1e',105),'FRONT_DIAL_RIGHT'),105)
        self.assertEqual(completed_sequence(row('0xf1','0x10',106)+row('0xf1','0',107),'JOYSTICK_CENTER'),107)
        for data,action in ((row('0x13','0x1',100),'MENU'),
                            (row('0x13','0x1',100)*2+row('0x13','0',102),'MENU'),
                            (row('0x13','0x1',0)+row('0x13','0',0),'MENU'),
                            (row('0x1ab','0x1',100)+row('0x1ab','0',102),'MENU'),
                            (row('0x2f5','0xffffffe2',105),'FRONT_DIAL_RIGHT')):
            with self.subTest(action=action,data=data), self.assertRaises(RuntimeError):
                completed_sequence(data,action)


if __name__=='__main__':unittest.main()
