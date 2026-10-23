"""等长布局、真实引导复制、损坏拒绝与封装文件长度契约。"""
import json
from pathlib import Path
import re
import struct
import sys
import tempfile
import unittest

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))
from look_materials import load,sha
from look_matrix_embed import payload
from look_matrix_compact import build,compile_copy,COPY_BYTES,COPY_VA,SOURCE_VA


class CompactMatrix(unittest.TestCase):
    def test_equal_size_layout_and_inverse(self):
        original,_=load(LAB/'build/look-materials-77zf0trj')
        image,report=build(original['cpapp-b.bin'],original['matrix-delta.bin'])
        candidate,_=load(LAB/'build/look-materials-compact-m60gnero')
        self.assertEqual(image,candidate['cpapp-b.bin'])
        self.assertEqual(len(image),17617008)
        self.assertEqual(image[0x20124:0x20148],original['cpapp-b.bin'][0x20124:0x20148])
        self.assertEqual(image[0x20150:0x2017c],original['cpapp-b.bin'][0x20150:0x2017c])
        self.assertEqual(image[SOURCE_VA-0x108000:SOURCE_VA-0x108000+2304],payload(original['matrix-delta.bin']))
        restored=bytearray(image)
        for row in report['patches']:restored[row['offset']:row['offset']+row['bytes']]=bytes.fromhex(row['before'])
        self.assertEqual(bytes(restored),original['cpapp-b.bin'])
        self.assertFalse(report['initialized_data_span_overlaps_existing_BSS'])

    def test_boot_copy_assembly_rebuild(self):
        with tempfile.TemporaryDirectory(dir=LAB/'build') as out:compile_copy(Path(out))

    def test_original_entry_copy_survives_RTOS_mapping(self):
        folder=LAB/'runs/native-look-cp-boot-xx0nc7mr'
        r=json.loads((folder/'result.json').read_text())
        self.assertTrue(r['bootstrap_shadow_matches_header'])
        self.assertTrue(r['matrix_mapping']['matches_embedded_payload'])
        prefix=(folder/'boot-prefix.bin').read_bytes()
        self.assertEqual(prefix[COPY_VA-0x108000:COPY_VA-0x108000+len(COPY_BYTES)],COPY_BYTES)
        self.assertEqual(r['first_data_abort']['DFAR'],'0xf1388100')
        self.assertEqual(r['cross_domain_callback'],0x1164434)
        self.assertFalse(r['full_CP_boot_verified'])
        self.assertFalse(r['DAT_packaging_allowed'])

    def test_bad_RAM_source_is_rejected_before_destination_copy(self):
        folder=LAB/'runs/native-look-cp-t90987rv'
        r=json.loads((folder/'result.json').read_text())
        pc=int(re.search(r'R15=([0-9a-fA-F]+)',(folder/'failure-registers.txt').read_text())[1],16)
        self.assertIn(pc,(0x108f68,0x108f6a))
        self.assertFalse(any((folder/'matrix-at-failure.bin').read_bytes()))
        self.assertEqual(r['status'],'failed')
        self.assertEqual(r['exit']['exit_code'],0)

    def test_changed_payload_cannot_authorize_itself(self):
        files,r=load(LAB/'build/look-materials-compact-m60gnero')
        image=bytearray(files['cpapp-b.bin']);image[SOURCE_VA-0x108000]^=1
        files['cpapp-b.bin']=bytes(image)
        with tempfile.TemporaryDirectory(prefix='look-materials-bad-compact-',dir=LAB/'build') as out:
            out=Path(out)
            for name,raw in files.items():(out/name).write_bytes(raw)
            r['files']={name:dict(bytes=len(raw),sha256=sha(raw)) for name,raw in files.items()}
            (out/'receipt.json').write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,'重建'):load(out)


if __name__=='__main__':unittest.main()
