"""保护逐次原生参数、非等距横轴、照片输入和完整菜单顺序。"""
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))


class LiveReference(unittest.TestCase):
    def test_full_camera_order_and_extension_slots(self):
        from look_live import CAMERA_LOOKS,LOOKS
        self.assertEqual(CAMERA_LOOKS,('ST','PT','NT','VV','VV2','FL','IN','SH','BW','SE','FL2','FL3'))
        self.assertEqual(len(LOOKS),18)

    def test_native_gamma_grid_is_not_uniform(self):
        from look_live import gamma_axis
        record=bytearray(576);record[0x204:0x210]=bytes((0,0,1,2,3,4,5,4,3,4,4,3))
        axis=gamma_axis(record)
        self.assertEqual(len(axis),129)
        self.assertEqual(axis[:5],(0,32,64,96,128))
        self.assertEqual(axis[-1],65535)
        self.assertGreater(len(set(b-a for a,b in zip(axis,axis[1:]))),2)
        record[0x204]=255
        with self.assertRaises(ValueError):gamma_axis(record)

    def test_matrix_uses_native_Q10_baseline(self):
        from look_live import matrix_q10
        raw=struct.pack('<27h',*((1024,0,0,0,1024,0,0,0,1024)*3))
        self.assertEqual(matrix_q10(raw,1),(1,0,0,0,1,0,0,0,1))

    def test_photo_read_is_oriented_color_managed_and_source_unchanged(self):
        from PIL import Image,ImageCms
        from look_live import read_image
        from look_materials import sha
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp).resolve()
            path=tmp/'reference.jpg';image=Image.new('RGB',(960,640),(120,55,20))
            exif=Image.Exif();exif[274]=6
            image.save(path,exif=exif,icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
            before=sha(path.read_bytes());result,audit=read_image(path)
            self.assertEqual(result.size,(171,256));self.assertEqual(result.mode,'RGB')
            self.assertIn('converted',audit['color_management']);self.assertEqual(sha(path.read_bytes()),before)
            bad=Path(tmp)/'bad.jpg';bad.write_bytes(b'not an image')
            with self.assertRaises(Exception):read_image(bad)
            path=Path(tmp)/'unknown-profile.png';image.save(path,icc_profile=b'invalid')
            with self.assertRaisesRegex(ValueError,'ICC'):read_image(path)

    def test_gamma_plateau_and_reference_identity(self):
        from look_live import gamma_relative
        axis=tuple(range(129));values=tuple(min(n,120) for n in range(129))
        baseline={'x':axis,'y':values};target={'x':axis,'y':tuple(v*2 for v in values)}
        self.assertEqual(gamma_relative(1,baseline,target),1)
        for at in (0,.1,.5,1):self.assertEqual(gamma_relative(at,baseline,baseline),at)

    def test_invalid_selection_fails_before_native_execution(self):
        from look_live import LiveEngine
        engine=LiveEngine(LAB/'build/look-materials-77zf0trj')
        with patch('look_live.execute') as run:
            for look,opts in [('unknown',{}),('ST',{'level':0}),('ST',{'movie':1}),('FL2',{'movie':True})]:
                with self.assertRaises(ValueError):engine.capture(look,**opts)
            run.assert_not_called()

    def test_AP_failure_cannot_fall_back_to_saved_parameters(self):
        from look_live import LiveEngine
        engine=LiveEngine(LAB/'build/look-materials-77zf0trj')
        with patch('look_live.execute',side_effect=RuntimeError('AP unavailable')) as run:
            with self.assertRaisesRegex(RuntimeError,'AP unavailable'):engine.capture('ST')
            self.assertEqual(run.call_count,1)

    def test_native_record_truncation_duplicate_and_wrong_gamma_fail(self):
        import json
        from look_live import native_rows
        from look_materials import load
        rows=json.loads((LAB/'runs/look-live-first-native-list.json').read_text())
        receipt=json.loads(Path(rows[10]['receipt']).read_text());raw=(Path(receipt['CP_run'])/'console.log').read_bytes()
        files,_=load(receipt['materials'])
        native_rows(raw,files,19,8,True,False)
        for bad in (raw[:-30],raw.replace(b'LOOK_LIVE_END',raw.splitlines()[1]+b'\nLOOK_LIVE_END'),
                    raw.replace(b'X 00000001 00000013 0000000020000000',b'X 00000001 00000013 0000000021000000')):
            with self.assertRaises(ValueError):native_rows(bad,files,19,8,True,False)


if __name__=='__main__':unittest.main()
