"""原研究目录已删除时，材料准备仍须使用固定项目内来源。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB/'tools'))
import look_materials as materials


class LocalMaterials(unittest.TestCase):
    def test_prepare_without_original_research_preserves_pinned_bytes(self):
        self.assertFalse((LAB.parent/'analysis').exists())
        source = LAB/'build/look-materials-77zf0trj'
        expected, _ = materials.load(source)
        folder = materials.prepare(LAB.parent)
        try:
            actual, receipt = materials.load(folder)
            self.assertEqual(actual, expected)
            self.assertFalse(receipt['camera_io'])
            self.assertFalse(receipt['original_images_read'])
            self.assertEqual(receipt['local_copy_source'], str(source.relative_to(LAB)))
        finally:
            import shutil
            shutil.rmtree(folder)

    def test_bad_local_source_cannot_be_accepted_by_rehashing_its_receipt(self):
        source = LAB/'build/look-materials-77zf0trj'
        files, receipt = materials.load(source)
        with tempfile.TemporaryDirectory(prefix='look-materials-invalid-local-', dir=LAB/'build') as temporary:
            folder = Path(temporary)
            for name, raw in files.items():
                (folder/name).write_bytes(raw)
            cp = bytearray(files['cpapp-b.bin'])
            cp[0] ^= 1
            (folder/'cpapp-b.bin').write_bytes(cp)
            receipt['files']['cpapp-b.bin']['sha256'] = materials.sha(cp)
            (folder/'receipt.json').write_text(json.dumps(receipt))
            with patch.object(materials, 'LOCAL_BASE', folder, create=True):
                with self.assertRaisesRegex(ValueError, '固定材料身份'):
                    materials.prepare(LAB.parent)


if __name__ == '__main__':
    unittest.main()
