"""迁移后的入口不依赖已不存在的旧工程；不启动 VM 或读取镜像。"""
from pathlib import Path
import importlib.util
import os
import subprocess
import sys
import unittest

LAB = Path(__file__).resolve().parents[1]
OLD = str(Path.home()/'Desktop/a7r5-qemu')


class RelocatedEntrypoints(unittest.TestCase):
    def test_environment_launchers_and_activation_follow_current_project(self):
        stale = [p.name for p in (LAB / '.venv/bin').iterdir()
                 if p.is_file() and not p.is_symlink() and OLD.encode() in p.read_bytes()]
        self.assertEqual(stale, [])
        result = subprocess.run(['/bin/bash', '-c',
            'source "$1/.venv/bin/activate"; python -B -c "import sys; print(sys.prefix)"',
            'relocation-test', str(LAB)], capture_output=True, text=True, check=True)
        self.assertEqual(Path(result.stdout.strip()), LAB / '.venv')
        result = subprocess.run([str(LAB / '.venv/bin/wheel'), 'version'],
            capture_output=True, text=True, check=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertIn('wheel', result.stdout.lower())

    def test_original_verifier_can_be_imported_without_reading_images(self):
        spec = importlib.util.spec_from_file_location('image_verifier', LAB / 'tools/verify-originals.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.image_root(LAB), LAB.parent / 'a7r5-firmware-images')
        self.assertEqual(module.image_root(Path('/tmp/包含空格 test/a7r5-qemu')),
                         Path('/tmp/包含空格 test/a7r5-firmware-images'))


if __name__ == '__main__':
    unittest.main()
