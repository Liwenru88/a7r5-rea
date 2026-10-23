"""组合边界：旧声音与色彩必须保留，清单不能授权任意新CP。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))
from look_integrated import build,SOUND_OFFSET,OLD_INTEGRATED_SHA
from look_materials import load,sha
from look_matrix_compact import build as compact


class IntegrationContract(unittest.TestCase):
    def test_composition_reverses_exactly_to_both_sealed_candidates(self):
        files,_=load(LAB/'build/look-materials-77zf0trj')
        cp,report=build(files['cpapp-b.bin'],files['matrix-delta.bin'])
        self.assertEqual(len(cp),17617008)
        old=bytearray(cp)
        for row in report['patches'][:-1]:
            old[row['offset']:row['offset']+row['bytes']]=bytes.fromhex(row['before'])
        self.assertEqual(sha(old),OLD_INTEGRATED_SHA)
        without_sound=bytearray(cp);without_sound[SOUND_OFFSET]=0x0f
        self.assertEqual(bytes(without_sound),compact(files['cpapp-b.bin'],files['matrix-delta.bin'])[0])
        self.assertFalse(report['settings_writes_required_for_target_matrices'])
        self.assertFalse(report['device_deployment_ready'])

    def test_mutated_CP_with_rehashed_manifest_is_rejected(self):
        files,receipt=load(LAB/'build/look-materials-77zf0trj')
        cp,report=build(files['cpapp-b.bin'],files['matrix-delta.bin'])
        files.update({'cp-matrix-source.bin':files['cpapp-b.bin'],
            'matrix-inline.json':(json.dumps(report)+'\n').encode()})
        changed=bytearray(cp);changed[SOUND_OFFSET]=0x0f
        files['cpapp-b.bin']=bytes(changed)
        with tempfile.TemporaryDirectory(prefix='look-materials-invalid-integrated-',dir=LAB/'build') as name:
            folder=Path(name)
            for n,r in files.items():(folder/n).write_bytes(r)
            receipt.update(schema=6,files={n:dict(bytes=len(r),sha256=sha(r)) for n,r in files.items()})
            (folder/'receipt.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'整合内嵌CP重建'):load(folder)


if __name__=='__main__':unittest.main()
