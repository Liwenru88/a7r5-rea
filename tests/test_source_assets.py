"""资源恢复的外部契约：逐字节还原、失败不发布、拒绝覆盖和越界。"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'scripts/prepare_source_assets.py'


class SourceAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.payload = b'original bytes\n' * 100
        self.parts = []
        for index, data in enumerate((self.payload[:555], self.payload[555:])):
            name = f'source-assets/chunks/example/{index}.chunk'
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            self.parts.append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        self.row = dict(path='inputs/original.gz', bytes=len(self.payload),
                        sha256=hashlib.sha256(self.payload).hexdigest(), chunks=self.parts)
        self.manifest = self.root / 'scripts/source-assets.json'
        self.manifest.parent.mkdir()
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(dict(schema=1, assets=[self.row])))

    def run_tool(self, *extra):
        return subprocess.run([sys.executable, '-B', str(TOOL), '--root', str(self.root),
                               'restore', *extra], capture_output=True, text=True)

    def test_chunk_restore_keeps_original_bytes(self):
        done = self.run_tool()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.root / self.row['path']).read_bytes(), self.payload)
        again = self.run_tool()
        self.assertEqual(again.returncode, 0, again.stderr)

    def test_corrupt_chunk_does_not_publish_target(self):
        (self.root / self.parts[1]['path']).write_bytes(b'corrupt')
        done = self.run_tool()
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse((self.root / self.row['path']).exists())
        self.assertIn('摘要', done.stderr)

    def test_existing_different_file_is_never_overwritten(self):
        target = self.root / self.row['path']
        target.parent.mkdir()
        target.write_bytes(b'keep my data')
        done = self.run_tool()
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(target.read_bytes(), b'keep my data')
        self.assertIn('覆盖', done.stderr)

    def test_unsafe_manifest_paths_are_refused(self):
        for name in ('../outside', '/absolute'):
            with self.subTest(name=name):
                self.row['path'] = name
                self.write_manifest()
                done = self.run_tool()
                self.assertNotEqual(done.returncode, 0)
                self.assertIn('路径', done.stderr)

    def test_symlink_parent_is_refused(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'inputs').symlink_to(outside, target_is_directory=True)
        done = self.run_tool()
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse((outside / 'original.gz').exists())
        self.assertIn('链接', done.stderr)

    def test_remote_assets_require_explicit_download(self):
        self.row.pop('chunks')
        self.row['source'] = 'https://raw.githubusercontent.com/example/repo/' + 'a' * 40 + '/asset'
        self.write_manifest()
        done = self.run_tool()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('--download', done.stderr)

    def test_incorrect_download_is_not_published(self):
        self.row.pop('chunks')
        self.row['source'] = 'https://raw.githubusercontent.com/example/repo/' + 'a' * 40 + '/asset'
        self.write_manifest()
        spec = importlib.util.spec_from_file_location('source_asset_download', TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_manifest(self.root)
        with patch.object(module, 'urlopen', return_value=io.BytesIO(b'corrupt')):
            with self.assertRaisesRegex(ValueError, '摘要'):
                module.restore(self.root, self.row, download=True)
        self.assertFalse((self.root / self.row['path']).exists())
        self.assertFalse(list(self.root.rglob('.restore-*')))


if __name__ == '__main__':
    unittest.main()
