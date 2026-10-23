"""键表保留项导致 UI ID 与记录下标不一致，不能据此生成错误原始键码。"""
import importlib.util
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('keymap',ROOT/'tools/research-input-map.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class MapContract(unittest.TestCase):
    def test_sparse_ui_ids_are_found_by_record_identity_not_index(self):
        forward=[(100,(3,2)),(108,(0x10000013,0x2ea)),(116,(0x1000001c,0x2f5))]
        inverse=[(200,(2,3)),(208,(0x2ea,0x10000013)),(216,(0x2f5,0x1000001c))]
        self.assertEqual(module.mapping_records(forward,inverse,0x2f5),(116,216))
        for f,i in ((forward+forward[2:],inverse),(forward,inverse[:-1]),
                    (forward,inverse[:-1]+[(216,(0x2f5,0x1000ffff))])):
            with self.assertRaises(ValueError):module.mapping_records(f,i,0x2f5)


if __name__=='__main__':unittest.main()
