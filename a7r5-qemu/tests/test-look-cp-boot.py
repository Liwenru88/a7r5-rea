"""保护启动观察边界、真实页表解码与未完成启动不放行的契约。"""
import json
from pathlib import Path
import struct
import sys
import unittest

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))
from look_cp_boot import translate,observe,inspect_dump


class CPBootContract(unittest.TestCase):
    def test_real_boot_page_tables_resolve_embedded_matrix(self):
        folder=LAB/'runs/native-look-cp-boot-_3e96_mz'
        record=json.loads((folder/'result.json').read_text())
        table=(folder/'mmu-l1.bin').read_bytes()
        physical,entries=translate(0x1a3a000,table,lambda a:(folder/f'mmu-l2-{a:08x}.bin').read_bytes())
        self.assertEqual(physical,0x1a3a000)
        self.assertEqual(entries,record['matrix_mapping']['descriptors'])
        self.assertTrue(record['matrix_mapping']['matches_embedded_payload'])
        self.assertTrue(record['bootstrap_shadow_matches_header'])
        self.assertFalse(record['DAT_packaging_allowed'])
        self.assertFalse(record['full_CP_boot_verified'])

    def test_section_small_page_and_invalid_descriptors(self):
        l1=bytearray(0x4000);va=0x1123456
        struct.pack_into('<I',l1,(va>>20)*4,0x3000002)
        self.assertEqual(translate(va,l1,lambda a:b'')[0],0x3023456)
        struct.pack_into('<I',l1,(va>>20)*4,0x3000401)
        l2=bytearray(1024);struct.pack_into('<I',l2,((va>>12)&255)*4,0x4567002)
        self.assertEqual(translate(va,l1,lambda a:bytes(l2))[0],0x4567456)
        for table,reader in ((bytes(8),lambda a:b''),(bytes(0x4000),lambda a:b''),(l1,lambda a:b'bad')):
            with self.assertRaises(ValueError):translate(va,table,reader)

    def test_bounded_observation_rejected_before_reading_inputs(self):
        for ms in (0,True,2001,1.5):
            with self.assertRaises(ValueError):observe(None,Path('/missing'),observe_ms=ms)
        with self.assertRaises(ValueError):inspect_dump(None,0xf1388100,4,'mmio.bin')


if __name__=='__main__':unittest.main()
