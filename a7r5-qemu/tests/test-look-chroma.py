"""CC1 有符号耦合、符号增益和单色分支的独立数值边界。"""
from pathlib import Path
import sys
import unittest
import json

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))


class ChromaReference(unittest.TestCase):
    def test_signed_branches_and_inverse(self):
        from look_chroma import forward,inverse
        p=(-193,-269,-251,-51,408,554,563,563)
        # 原CP顺序：cross[3/1]、cross[0/2]；正负增益分别选4/6及7/5。
        self.assertAlmostEqual(forward(1,0,p)[0],408/512)
        for u,v in ((1,0),(-1,0),(0,1),(0,-1),(.2,-.7),(-.6,.1)):
            cr,cb=forward(u,v,p);actual=inverse(cr,cb,p)
            self.assertAlmostEqual(actual[0],u);self.assertAlmostEqual(actual[1],v)

    def test_zero_native_gain_is_monochrome_without_name_switch(self):
        from look_chroma import relative
        p=(-193,-269,-251,-51,408,554,563,563)
        for rgb in ((1.,0.,0.),(0.,1.,0.),(.2,.4,.6)):
            bw=relative(rgb,p,(0,)*8)
            self.assertEqual(bw[0],bw[1]);self.assertEqual(bw[1],bw[2])
            self.assertEqual(relative(rgb,p,p),rgb)

    def test_invalid_or_singular_baseline_is_rejected(self):
        from look_chroma import inverse
        for p in ((0,)*8,(0,)*7,(1024,1024,1024,1024,512,512,512,512)):
            with self.assertRaises(ValueError):inverse(.1,.2,p)

    def test_native_CC1_application_and_control_records_are_required_and_bound(self):
        from look_live import native_rows
        from look_materials import load
        receipt=json.loads((LAB/'runs/look-selection-w55he2_s/result.json').read_text())
        files,_=load(receipt['materials']);raw=(Path(receipt['CP_run'])/'console.log').read_bytes()
        rows=native_rows(raw,files,0,8,True,False,require_chroma=True)
        self.assertEqual(tuple(__import__('struct').unpack('<8h',rows[1]['cc1_applied'])),
            (-193,-269,-251,-51,408,554,563,563))
        lines=raw.splitlines()
        missing=b'\n'.join(l for l in lines if not l.startswith(b'P '))+b'\n'
        wrong=raw.replace(b'P 00000001 00000000 3fff',b'P 00000001 00000000 40ff')
        wrong_mode=raw.replace(b'N 00000001 00000000 0000',b'N 00000001 00000000 0100')
        for bad in (missing,wrong,wrong_mode):
            with self.assertRaises(ValueError):native_rows(bad,files,0,8,True,False,require_chroma=True)


if __name__=='__main__':unittest.main()
