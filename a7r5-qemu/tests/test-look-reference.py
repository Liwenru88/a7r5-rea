"""保护参数真实性、ST 参照空间和参考渲染边界。"""
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))
from look_materials import load
from look_native import parse_ap,parse_cp
from look_reference import Dataset,fixture,pixel,decode_srgb,encode_srgb,unpack_bank


class ReferenceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=Dataset(Path(os.environ['LOOK_REFERENCE_PARAMETERS']))

    def test_ST_reference_does_not_apply_sensor_matrix_twice(self):
        source=fixture();result,audit=self.data.render(source,'ST')
        self.assertEqual(result.tobytes(),source.tobytes())
        self.assertFalse(audit['native_pixel_pipeline_verified'])

    def test_missing_matrix_reproduced_and_repair_has_distinct_native_output(self):
        for endpoint in range(3):
            before=[self.data.parameters(look,fixed=False,endpoint=endpoint)['matrix'] for look in ('ST','FL2','FL3')]
            self.assertEqual(before[0],before[1]);self.assertEqual(before[1],before[2])
            after=[self.data.parameters(look,endpoint=endpoint)['matrix'] for look in ('FL2','FL3')]
            self.assertNotEqual(after[0],after[1])

    def test_six_AP_markers_packed_signs_levels_and_no_alias(self):
        d=self.data
        for i in range(6):
            marker=d.record['AP_mapping'][f'{10+i}:0'];self.assertEqual(marker,249+i)
            raw=struct.unpack('1215b',d.files[f'slot{i+1}.raw-s8.bin'])
            for level in (1,8):
                grid=unpack_bank(d.cp,bytes.fromhex(d.native[f'L:{marker}:{level}']))
                for n in (0,101,404):self.assertEqual(grid[n],tuple(raw[n+c*405]*level>>3 for c in range(3)))

    def test_Gamma_routes_custom_ST_and_FL2_FL3_separated(self):
        from look_materials import NAMES
        for movie in (False,True):
            baseline=self.data.parameters('ST',movie=movie)
            for look in NAMES:self.assertEqual(self.data.parameters(look,movie=movie)['gamma'],baseline['gamma'])
            a,b=[self.data.parameters(v,movie=movie) for v in ('FL2','FL3')]
            self.assertEqual((a['audit']['gamma_id'],b['audit']['gamma_id']),(49,50) if movie else (47,48))
            self.assertNotEqual(a['gamma'],b['gamma'])
        self.assertEqual(self.data.files['gamma-before.bin'],self.data.parameters('FL2')['gamma'])

    def test_sRGB_roundtrip_has_no_second_encoding(self):
        identity=(1,0,0,0,1,0,0,0,1)
        for rgb in ((0,0,0),(1,1,1),(.25,.5,.75)):
            self.assertEqual(pixel(rgb,identity),tuple(round(v*255) for v in rgb))
        for v in (0,.003,.04,.18,.5,1):self.assertAlmostEqual(encode_srgb(decode_srgb(v)),v)

    def test_optional_Gamma_diagnostic_preserves_ST_and_rejects_unknown_axis(self):
        source=fixture();result,_=self.data.render(source,'ST',gamma_diagnostic=True)
        self.assertEqual(result.tobytes(),source.tobytes())
        for look in ('FL2','FL3'):
            image,audit=self.data.render(source,look,gamma_diagnostic=True)
            self.assertEqual(image.size,source.size);self.assertTrue(audit['Gamma_curve_applied'])
            self.assertIn('diagnostic',audit['Gamma_coordinate_assumption'])

    def test_missing_duplicate_and_truncated_native_records_fail_closed(self):
        d=self.data;r=d.record
        ap=(Path(r['AP_run'])/'console.log').read_bytes()
        cp=(Path(r['CP_run'])/'console.log').read_bytes()
        for raw in (ap[:-20],ap.replace(b'LOOK_AP_END',b'A 00000000 00000000 00000000\nLOOK_AP_END')):
            with self.assertRaises(ValueError):parse_ap(raw)
        for raw in (cp[:-20],cp.replace(b'LOOK_CP_END',b'X 00000000\nLOOK_CP_END')):
            with self.assertRaises(ValueError):parse_cp(raw,d.files)

    def test_material_corruption_detected_before_execution(self):
        d=self.data;root=Path(d.record['materials']);original=(root/'slot1.raw-s8.bin').read_bytes()
        import look_materials
        reader=look_materials.regular
        def broken(path,*args):
            raw=reader(path,*args)
            return bytes([raw[0]^1])+raw[1:] if Path(path).name=='slot1.raw-s8.bin' else raw
        with patch('look_materials.regular',broken):
            with self.assertRaisesRegex(ValueError,'校验失败'):load(root)
        self.assertEqual((root/'slot1.raw-s8.bin').read_bytes(),original)

    def test_unknown_look_slot_endpoint_and_bank_are_rejected(self):
        for args in [('unknown',{}),('ST',{'slot':16}),('ST',{'endpoint':3}),('ST',{'level':0})]:
            with self.assertRaises(ValueError):self.data.parameters(args[0],**args[1])
        with self.assertRaises(ValueError):unpack_bank(self.data.cp,bytes(1619))
        with self.assertRaises(ValueError):unpack_bank(self.data.cp,b'\xff'*1620)


if __name__=='__main__':unittest.main()
