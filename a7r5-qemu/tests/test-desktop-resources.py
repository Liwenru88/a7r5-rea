"""共享锁、只读数据目录与包内依赖的失败门槛。"""
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from app_paths import AppPaths, worker_executable
from native_vm import NativeVM
from runtime_manifest import verified_libraries


class ResourceContract(unittest.TestCase):
    def test_frozen_runtime_python_alias_is_not_used_as_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'Contents/MacOS/A7R5Emulator'
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(executable.with_name('python'))):
                self.assertEqual(worker_executable(), str(executable))

    def test_owned_lock_conflict_stops_before_loading_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            with path.open('a') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                vm = NativeVM('lock-contract', capid=True, boot_services=True)
                try:
                    with patch('app_paths.open_vm_lock', side_effect=lambda: path.open('a')), \
                            patch('runtime_manifest.verified_inputs') as verify:
                        with self.assertRaises(BlockingIOError):
                            vm.start()
                        verify.assert_not_called()
                finally:
                    vm.close()

    def test_unwritable_data_root_is_not_silently_relocated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o500)
            try:
                with self.assertRaises(PermissionError):
                    AppPaths(ROOT, root / 'data').prepare()
            finally:
                root.chmod(0o700)

    def test_dependency_set_hash_and_symlinks_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'runtime').mkdir()
            (root / 'lib').mkdir()
            library = root / 'lib/fixed.dylib'
            library.write_bytes(b'pinned')
            record = {'libraries': {'fixed.dylib': {'bytes': 6, 'sha256': hashlib.sha256(b'pinned').hexdigest()}}}
            (root / 'runtime/manifest.json').write_text(json.dumps(record))
            self.assertEqual(verified_libraries(root), [library])
            library.write_bytes(b'edited')
            with self.assertRaises(ValueError):
                verified_libraries(root)
            library.unlink()
            library.symlink_to(ROOT / 'bin/qemu-system-aarch64')
            with self.assertRaises(ValueError):
                verified_libraries(root)
            (root / 'lib/extra.dylib').touch()
            with self.assertRaises(ValueError):
                verified_libraries(root)


if __name__ == '__main__':
    unittest.main()
