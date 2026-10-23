"""相机 MPF JPEG 读取主照片；不能将缩略图或动画冒充主照片。"""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))
from PIL import Image
from look_live import read_image
from look_materials import sha


class CameraJpeg(unittest.TestCase):
    def test_MPF_primary_is_read_and_thumbnail_is_not_selected(self):
        with tempfile.TemporaryDirectory(dir=LAB/'runs') as folder:
            path=Path(folder)/'camera.JPG'
            Image.new('RGB',(960,640),(180,25,20)).save(path,format='MPO',save_all=True,
                append_images=[Image.new('RGB',(160,100),(20,30,190))])
            before=sha(path.read_bytes());image,audit=read_image(path)
            self.assertEqual(image.size,(384,256));self.assertGreater(image.getpixel((0,0))[0],150)
            self.assertEqual(audit['container_format'],'MPO')
            self.assertEqual(audit['selected_frame'],0);self.assertEqual(audit['container_frames'],2)
            self.assertEqual(before,sha(path.read_bytes()))

    def test_unknown_multiframe_container_is_not_silently_flattened(self):
        with tempfile.TemporaryDirectory(dir=LAB/'runs') as folder:
            path=Path(folder)/'pages.tif'
            Image.new('RGB',(16,16),'red').save(path,save_all=True,
                append_images=[Image.new('RGB',(16,16),'blue')])
            with self.assertRaisesRegex(ValueError,'单帧|主照片'):read_image(path)


if __name__=='__main__':unittest.main()
