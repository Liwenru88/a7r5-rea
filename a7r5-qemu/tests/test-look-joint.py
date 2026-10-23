"""联合参数材料、字节重建和原厂路径边界。"""
import base64
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))
from look_joint import build,basis,curve,memory,GAMMA_VA,NAMES,TARGET_SHA
from look_materials import load,sha
MATERIALS=LAB/'build/look-materials-joint-oj2ed8ok'


class JointContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files,cls.receipt=load(MATERIALS)
        cls.spec=json.loads(cls.files['six-looks.json'])
        cls.documents=[dict(schema='a7c2-creative-look/1',name=s['name'],target=s['source_target'],base='ST',
            table_format='native-5x9x9-s7-planar',table_base64=base64.b64encode(cls.files[s['table']]).decode(),
            native_photo=dict(runtime_basis=s['native_photo_basis'])) for s in cls.spec['slots']]

    def test_final_CP_rebuild_and_inverse_are_byte_exact(self):
        with tempfile.TemporaryDirectory(dir=LAB/'build') as folder:
            cp,report=build(self.files['cp-joint-source.bin'],self.documents,folder)
        self.assertEqual(sha(cp),TARGET_SHA)
        inverse=bytearray(cp)
        for row in report['patches']:inverse[row['offset']:row['offset']+row['bytes']]=bytes.fromhex(row['before'])
        self.assertEqual(bytes(inverse),self.files['cp-joint-source.bin'])
        self.assertTrue(report['page_table_root_unchanged'])
        self.assertFalse(report['device_deployment_ready'])

    def test_unsupported_source_and_incomplete_parameters_are_rejected(self):
        for change in ('model','table','range','dimension'):
            d=copy.deepcopy(self.documents[0])
            if change=='model':d['target']['firmware']='unknown'
            elif change=='table':d['table_base64']=base64.b64encode(bytes(1214)).decode()
            elif change=='range':d['native_photo']['runtime_basis']['tone_q10'][0]=1025
            else:d['native_photo']['runtime_basis']['matrix_planes'][0].pop()
            with self.subTest(change=change),self.assertRaises(ValueError):basis(d)

    def test_matrix_deltas_preserve_row_sum_and_three_planes(self):
        for doc in self.documents:
            _,raw,_=basis(doc)
            for plane in range(3):
                values=struct.unpack_from('<9h',raw,6+plane*18)
                self.assertEqual([sum(values[i:i+3]) for i in (0,3,6)],[0,0,0])

    def test_joint_tone_gain_is_not_erased_by_per_curve_normalization(self):
        from look_live import gamma_relative
        base=dict(x=(0,100),y=(0,100));target=dict(x=(0,100),y=(0,90))
        self.assertAlmostEqual(gamma_relative(.5,base,target,common_scale=True),.45)
        self.assertAlmostEqual(gamma_relative(.5,base,target),.5)

    def test_curve_identity_and_domain_metadata_preservation(self):
        for domain,column in ((0,0),(0,6),(1,6)):
            pointer=struct.unpack('<I',memory(self.files,GAMMA_VA+(51+domain)*28+column*4,4))[0]
            record=memory(self.files,pointer,576)
            self.assertEqual(curve(record,(0,0,0)),record)
            changed=curve(record,(-32,34,64))
            self.assertEqual(changed[516:544],record[516:544])
            self.assertEqual(changed[548:],record[548:])

    def test_rehashed_manifest_does_not_authorize_CP_substitution(self):
        files=dict(self.files);cp=bytearray(files['cpapp-b.bin']);cp[0x37762c]^=1;files['cpapp-b.bin']=bytes(cp)
        receipt=copy.deepcopy(self.receipt)
        with tempfile.TemporaryDirectory(prefix='look-materials-invalid-joint-',dir=LAB/'build') as folder:
            folder=Path(folder)
            for name,raw in files.items():(folder/name).write_bytes(raw)
            receipt['files']={n:dict(bytes=len(r),sha256=sha(r)) for n,r in files.items()}
            (folder/'receipt.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'联合参数候选'):load(folder)

    def test_preview_order_is_bound_to_materials(self):
        from look_live import LiveEngine
        current=LiveEngine(MATERIALS);legacy=LiveEngine(LAB/'build/look-materials-integrated-8wzq2z0r')
        self.assertEqual(current.looks[-6:],NAMES)
        self.assertNotIn('Eterna',current.looks)
        self.assertIn('Eterna',legacy.looks)
        self.assertEqual(len(current.looks),18)

    def test_all_51_original_gamma_rows_including_FL3_movie_are_preserved(self):
        source=self.files['cp-joint-source.bin'];expected=bytearray(source[0xf76968:0xf76efc])
        layout=json.loads(self.files['joint-layout.json'])
        for row in layout['curve_relocations']:
            for offset in row['pointer_offsets']:struct.pack_into('<I',expected,offset-0xf76968,row['after'])
        self.assertEqual(len(expected),51*28)
        self.assertEqual(memory(self.files,GAMMA_VA,len(expected)),expected)

    def test_native_secondary_FL2_unsupported_branch_is_not_a_fake_ST_result(self):
        from look_live import native_rows
        receipt=json.loads((LAB/'runs/look-selection-njd2g4wi/result.json').read_text())
        raw=(Path(receipt['CP_run'])/'console.log').read_bytes()
        native_rows(raw,self.files,19,8,False,False,require_chroma=True)
        lines=raw.splitlines();key=b'D 00000001 00000013 '
        bad=b'\n'.join(key+b'01'+line[len(key)+2:] if line.startswith(key) else line for line in lines)+b'\n'
        with self.assertRaisesRegex(ValueError,'第二域'):native_rows(bad,self.files,19,8,False,False,require_chroma=True)


if __name__=='__main__':unittest.main()
