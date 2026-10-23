"""矩阵暂存区必须在完整加载范围内；静态审计不得升级为运行证明。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))
from look_load_audit import audit
from look_materials import load
from media_candidate import extract
from runtime_manifest import verified_inputs


class LoadAuditContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files,_=load(LAB/'build/look-materials-integrated-8wzq2z0r')
        cls.nor=extract(verified_inputs()['initrd'],['cp/nor_ldr.img'])['cp/nor_ldr.img']

    def test_tail_is_in_second_read_and_runtime_is_explicitly_unproven(self):
        r=audit(self.files['cpapp-b.bin'],self.files['matrix-delta.bin'],self.nor)
        self.assertEqual(r['first_read_bytes']+r['remaining_read_bytes'],17617408)
        self.assertEqual(r['padding_bytes'],400)
        self.assertTrue(r['staged_matrix_in_remaining_read'])
        self.assertFalse(r['original_loader_executed'])
        self.assertFalse(r['AP_PCIe_transfer_verified'])

    def test_changed_descriptor_and_short_CP_are_rejected(self):
        changed=bytearray(self.nor);changed[0x144]^=1
        with self.assertRaisesRegex(ValueError,'身份不符'):
            audit(self.files['cpapp-b.bin'],self.files['matrix-delta.bin'],bytes(changed))
        with self.assertRaisesRegex(ValueError,'长度'):
            audit(self.files['cpapp-b.bin'][:-512],self.files['matrix-delta.bin'],self.nor)


if __name__=='__main__':unittest.main()
