"""虚拟卡验收失败必须停止；不把主机伪造内容当原厂结果。"""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import json
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from virtual_fat import make_fixture, read_files, MARKER, photo_payloads
from media_candidate import entry, add_files, compare, ADDITIONS, patch_property, MediaVM, LAB
from native_vm import dtb_properties
from runtime_manifest import verified_inputs, digest

class VirtualMedia(unittest.TestCase):
    def test_candidate_cannot_hide_tampering_or_symlinks(self):
        with tempfile.TemporaryDirectory(prefix='media-test-',dir=LAB/'build') as folder:
            root=Path(folder);base=root/'base.cpio';base.write_bytes(entry('usr/bin/original',b'firmware')+entry('TRAILER!!!',b''))
            original_dtb=root/'base.dtb';original_dtb.write_bytes(b'pinned-dtb')
            candidate=root/'media.cpio';add_files(base,candidate,{n:b'candidate' for n in ADDITIONS})
            dtb=root/'media.dtb';dtb.write_bytes(b'candidate-dtb')
            record={'base_initrd_sha256':digest(base),'base_dtb_sha256':digest(original_dtb),
                'candidate':{p.name:{'bytes':p.stat().st_size,'sha256':digest(p)} for p in (candidate,dtb)}}
            receipt=root/'receipt.json';receipt.write_text(json.dumps(record))
            vm=MediaVM.__new__(MediaVM);vm.candidate=root
            with patch('media_candidate.verified_inputs',side_effect=lambda:{'initrd':base,'dtb':original_dtb}):
                self.assertEqual(vm.runtime_inputs()['initrd'],candidate)
                dtb.write_bytes(b'altered')
                with self.assertRaisesRegex(ValueError,'摘要'):vm.runtime_inputs()
                dtb.unlink();dtb.symlink_to(original_dtb)
                with self.assertRaisesRegex(ValueError,'摘要'):vm.runtime_inputs()
                dtb.unlink();dtb.write_bytes(b'candidate-dtb')
                other=root/'receipt-copy';other.write_text(receipt.read_text());receipt.unlink();receipt.symlink_to(other)
                with self.assertRaisesRegex(ValueError,'符号链接'):vm.runtime_inputs()

    def test_dcf_images_have_declared_identity_and_distinct_content(self):
        import io
        from PIL import Image
        photos=photo_payloads();self.assertEqual(len(photos),2)
        self.assertEqual(read_files(make_fixture(photos=True)),{'/SEED.TXT':MARKER,**photos})
        self.assertEqual(len(set(photos.values())),2)
        for data in photos.values():
            image=Image.open(io.BytesIO(data))
            self.assertEqual(image.size,(1280,960))
            self.assertEqual(image.getexif()[305],'A7R5 virtual input')
            image.verify()

    def test_fixture_and_corrupt_fat_rejected(self):
        raw=make_fixture();self.assertEqual(read_files(raw),{'/SEED.TXT':MARKER})
        for kind in ('length','signature','copies','loop','bounds'):
            bad=bytearray(raw)
            if kind=='length':bad.pop()
            if kind=='signature':bad[510]=0
            if kind=='copies':bad[512+4]=7
            if kind in ('loop','bounds'):
                for off in (512,33*512):struct.pack_into('<H',bad,off+4,2 if kind=='loop' else 9000)
            with self.subTest(kind=kind),self.assertRaises(ValueError):read_files(bad)

    def test_original_firmware_cannot_be_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=root/'base';out=root/'out'
            base.write_bytes(entry('usr/bin/original',b'firmware')+entry('TRAILER!!!',b''))
            add_files(base,out,{n:b'candidate' for n in ADDITIONS})
            self.assertTrue(compare(base,out)['all_original_entries_identical'])
            out.write_bytes(out.read_bytes().replace(b'firmware',b'changed!'))
            with self.assertRaisesRegex(ValueError,'原归档'):compare(base,out)

    def test_dtb_patch_preserves_unrelated_properties(self):
        raw=verified_inputs()['dtb'].read_bytes();before=dtb_properties(raw)
        value=before[('/chosen','bootargs')].rstrip(b'\0')+b' test.virtual=1\0'
        after=dtb_properties(patch_property(raw,'/chosen','bootargs',value))
        self.assertEqual(after.pop(('/chosen','bootargs')),value)
        before.pop(('/chosen','bootargs'));self.assertEqual(before,after)
        with self.assertRaisesRegex(ValueError,'不存在'):patch_property(raw,'/chosen','missing',b'bad')

if __name__=='__main__':unittest.main()
