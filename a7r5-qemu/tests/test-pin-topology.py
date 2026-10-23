"""独立采集契约：短读、重复和错型号不能生成端口登记表。"""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from pin_topology import parse, cp_properties


class PinTopology(unittest.TestCase):
    def fixture(self):
        output = []
        for kind in ('pins', 'pins-template'):
            output.append(f'PIN_TOPOLOGY_BEGIN kind={kind} address=7f00000000')
            for i in range(50):
                own = '0x90050004,0,2,1' if i == 1 else '0x805700f9,0,2,0'
                output.append(f'PIN_ATOM index={i} mode=0 own={own} peer=0,0,0,0')
            output.append('PIN_TOPOLOGY_DONE count=50 readonly=1')
        return '\n'.join(output)

    def test_native_ap_services_stay_original_and_incomplete_receipts_fail(self):
        text = self.fixture()
        self.assertEqual(cp_properties(parse(text)), [(0, 2, 1, 0x90050004), (0, 1, 1, 0x9284074a)])
        for bad in (text + '\n' + text, text.replace('index=49', 'index=48'),
                    text.replace('0x90050004,0,2,1', '0x90050004,0,2,0'),
                    text.replace('PIN_ATOM index=49 mode=0 own=0x805700f9,0,2,0 peer=0,0,0,0\n', '', 1)):
            with self.subTest(bad=bad[-160:]), self.assertRaises(ValueError):
                parse(bad)


if __name__ == '__main__':
    unittest.main()
