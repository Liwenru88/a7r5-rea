"""原生重入与原厂消费必须使用不同证据，不得缺少释放或扩大适配状态。"""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from input_batch import research_receipt

def injection(state):
    return f'INJECT_KEY_SEND queue=0x807a0020 src=0x92840747 key_code=0x1ab sub=0 status={state} ex=0 from=0x1 result=0\n'.encode()

class ReentryEvidence(unittest.TestCase):
    def test_exact_native_reentry_does_not_claim_original_consumption(self):
        markers=b'OBS A7R5_NATIVE_BOOT_EXIT_OMITTED known MENU reentry only\nOBS A7R5_NATIVE_MENU_REENTER_RETURN current=0x354 tid=269\n'
        valid=injection('0x1')+markers+injection('0')
        result=research_receipt(valid,'MENU',0x355)
        self.assertIsNone(result['received']);self.assertEqual(result['injected'],[1,0])
        for data,key,before in [(injection('0x1')+markers,'MENU',0x355),(valid,'MENU',0),
                                (injection('0x1')+injection('0'),'MENU',0x355),(valid,'FN',0x355),
                                (valid+injection('0'),'MENU',0x355)]:
            with self.subTest(data=data,key=key,before=before),self.assertRaises(RuntimeError):
                research_receipt(data,key,before)

if __name__=='__main__':unittest.main()
