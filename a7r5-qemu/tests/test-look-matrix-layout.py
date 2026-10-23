"""保护无重叠初始化布局和原厂页表/栈保留边界。"""
from pathlib import Path
import struct
import sys
import unittest

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))
from look_materials import load
from look_matrix_embed import build,TABLE_VA


class ResolvedLayout(unittest.TestCase):
    def test_initialized_BSS_preserves_page_table_root_without_overlap(self):
        files,_=load(LAB/'build/look-materials-77zf0trj')
        original=files['cpapp-b.bin']
        legacy,_=build(original,files['matrix-delta.bin'])
        image,report=build(original,files['matrix-delta.bin'],initialized_bss=True)
        old=struct.unpack_from('<3I',original,0x20148)
        bss=struct.unpack_from('<3I',image,0x20148)
        data=struct.unpack_from('<3I',image,0x2013c)
        self.assertEqual(bss[1],0)
        self.assertEqual(bss[2],(data[2]+data[1]+4095)&~4095)
        translation=old[2]-old[0]
        self.assertEqual(bss[2]-bss[0],translation)
        self.assertEqual(((bss[0]+bss[1]+0x4fff)&~0x3fff),((old[0]+old[1]+0x4fff)&~0x3fff))
        self.assertLessEqual(old[2]+old[1],data[2]+data[1])
        self.assertLessEqual(TABLE_VA+2304,bss[2])
        self.assertLessEqual(bss[2]+0x418,report['page_table_root'])
        # 原全局变量区域现在由文件中的零初始化数据提供。
        self.assertFalse(any(image[old[2]-0x108000:old[2]+old[1]-0x108000]))
        self.assertEqual(image[:0x1000],original[:0x1000])
        self.assertEqual(image[0x20154:0x2017c],original[0x20154:0x2017c])
        self.assertEqual(image[0x20154:],legacy[0x20154:])
        self.assertFalse(report['initialized_data_span_overlaps_existing_BSS'])
        self.assertFalse(report['device_deployment_ready'])


if __name__=='__main__':unittest.main()
