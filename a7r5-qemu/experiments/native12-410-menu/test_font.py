"""字体覆盖层的完整前像、映射边界和精确逆还原回归。"""
import importlib.util
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from elftools.elf.elffile import ELFFile
import environment


class FontPatchContract(unittest.TestCase):
    def test_derived_image_preserves_all_bytes_outside_explicit_overlay(self):
        module=environment.ROOT/'a7r5-firmware-features/native24-combined/dependencies/native12-combined'
        spec=importlib.util.spec_from_file_location('menu_font_test',module/'menu_font.py')
        font=importlib.util.module_from_spec(spec);spec.loader.exec_module(font)
        raw=(module/'verification/2026-11-02-runtime/readback/components/usr/lib/appFw.so').read_bytes()
        with tempfile.TemporaryDirectory(prefix='native410-font-test-',dir=environment.LAB/'build') as temporary:
            root=Path(temporary)
            with self.assertRaisesRegex(ValueError,'完整前像'):font.build(b'unknown',root/'bad')
            self.assertFalse((root/'bad').exists())
            path,receipt=font.build(raw,root/'font');changed=path.read_bytes()
            self.assertEqual(font.sha(changed),environment.FONT_AP_SHA)
            self.assertEqual(len(changed),len(raw));self.assertLess(receipt['code_bytes'],2240)
            self.assertEqual(len(receipt['patches']),3)
            # 已失败的备用布局不得混入字体修复；原No12的完整setup保持。
            setup=0x5ce0000+0x8a70
            self.assertEqual(changed[setup:setup+1088],raw[setup:setup+1088])
            reconstructed=bytearray(changed);intervals=[]
            for row in receipt['patches']:
                off=row['offset'];before=bytes.fromhex(row['before']);after=bytes.fromhex(row['after'])
                self.assertEqual(raw[off:off+len(before)],before)
                self.assertEqual(changed[off:off+len(after)],after)
                self.assertTrue(all(off+len(after)<=a or b<=off for a,b in intervals));intervals.append((off,off+len(after)))
                reconstructed[off:off+len(before)]=before
            self.assertEqual(reconstructed,raw)
            old,new=ELFFile(io.BytesIO(raw)),ELFFile(io.BytesIO(changed))
            for a,b in zip(old.iter_segments(),new.iter_segments()):
                if a['p_type']=='PT_LOAD' and a['p_vaddr']==0x8e90000:
                    self.assertEqual(b['p_filesz'],b['p_memsz']);self.assertLessEqual(b['p_filesz'],65536)
                    self.assertEqual(b['p_flags'],5);self.assertEqual(a['p_offset'],b['p_offset'])
                else:self.assertEqual(a.header,b.header)
            branch=struct.unpack_from('<I',changed,0x5ce0000+font.CALL-0x8e90000)[0]
            delta=branch&0x3ffffff
            if delta&(1<<25):delta-=1<<26
            self.assertEqual(font.CALL+delta*4,font.START)
            with self.assertRaises(ValueError):font.build(changed,root/'double')


if __name__=='__main__':unittest.main()
