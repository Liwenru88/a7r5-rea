"""发布边界回归：实际 Git 忽略行为、凭据拦截和干净导出。"""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_check', PROJECT/'scripts/release_check.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
spec = importlib.util.spec_from_file_location('local_inputs', PROJECT/'scripts/check_local_inputs.py')
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()/'source'
        self.root.mkdir()
        shutil.copy2(PROJECT/'.gitignore', self.root/'.gitignore')

    def write(self, name, raw=b'source\n'):
        p = self.root/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        return p

    def test_real_ignore_rules_protect_originals_and_keep_sources(self):
        local = ['a7r5-firmware-images/官方升级包/BODYDATA.DAT',
                 'a7r5-desktop/dist/final/test.zip', 'a7r5-desktop/prepared/engine/file.py',
                 'a7r5-ssh/libjit-ssh-on-demand/ACTIVE_SERVICE.json',
                 'a7r5-ssh/pkg/ATTEMPT_LOCK/record', 'a7r5-ssh/pkg/client-key',
                 'a7r5-ssh/ssh-service/fixed-password-input',
                 'a7r5-ssh/libjit-ssh-on-demand/quick-runs/example/result.json',
                 'a7r5-implementation-kit/profiles/prepared-card.json',
                 'a7r5-libjit/packages/example/result.json', '.venv/bin/python']
        for name in local:
            self.write(name)
        self.write('a7r5-desktop/engine/device.py')
        self.write('a7r5-desktop/src-tauri/Cargo.lock')
        self.write('a7r5-updater-trust/public-key.pem')
        names = release.candidates(self.root)
        self.assertFalse(set(local) & set(names))
        self.assertIn('a7r5-desktop/engine/device.py', names)
        self.assertIn('a7r5-desktop/src-tauri/Cargo.lock', names)
        self.assertIn('a7r5-updater-trust/public-key.pem', names)
        self.assertFalse((self.root/'.git').exists())

    def test_research_key_exception_requires_exact_path_and_identity(self):
        name = 'a7r5-dat-tool/keys/research-signing-private.pem'
        raw = b'-----BEGIN '+b'PRIVATE KEY-----\npublic-research-fixture\n'
        p = self.write(name, raw)
        shutil.copy2(PROJECT/'a7r5-dat-tool/.gitignore', p.parents[1]/'.gitignore')
        with patch.dict(release.PUBLIC_RESEARCH_KEYS, {name: hashlib.sha256(raw).hexdigest()}, clear=True):
            self.assertIn(name, release.candidates(self.root))
            self.assertEqual(release.inspect(self.root, [name])[1], [])
            self.write('another-key.txt', raw)
            self.assertTrue(release.inspect(self.root, ['another-key.txt'])[1])
            p.write_bytes(raw+b'changed')
            errors = release.inspect(self.root, [name])[1]
            self.assertIn('公开研究私钥内容变化，须重新确认发布身份', [r['reason'] for r in errors])

    def test_machine_evidence_and_restored_assets_stay_local(self):
        local = [
            'docs/private-publication/20261111/index.before',
            'docs/cleanup-audit-20261111/execution-03-deep/surviving-files-before.json',
            'a7r5-firmware-features/firmware-runtime/audits/relative-parameters/build.json',
            'a7r5-firmware-features/releases/4.19-full-repaired-20261111/qemu/qt-driver.json',
            'a7r5-firmware-features/independent/profiles/native24/12.delta.gz',
            'sony-r5-colorlab/R5ColorLab/web/data/r5/paired-20261102-shared-c1-c50.json',
            'sony-r5-colorlab/R5ColorLab/web/data/chart/sony100mp_5300k_v45/SONY-v4.5-100MP-5300K.ARW.gz',
        ]
        source = [
            'a7r5-firmware-features/firmware-runtime/audits/relative-parameters/probe.py',
            'a7r5-firmware-features/releases/4.19-full-repaired-20261111/README.md',
            'a7r5-firmware-features/independent/profiles/native24/resources.json',
            'source-assets/chunks/sample/0000.chunk', 'scripts/source-assets.json',
        ]
        for name in local + source:
            self.write(name)
        names = release.candidates(self.root)
        self.assertFalse(set(local) & set(names), '本地证据或恢复的大资源进入了源码集')
        self.assertTrue(set(source) <= set(names), '恢复工具、清单或源码被误排除')

    def test_nested_upstream_ignore_does_not_publish_built_templates(self):
        upstream = 'a7r5-firmware-features/firmware-runtime/dependencies/native12-combined/upstream'
        self.write(upstream + '/.gitignore', (PROJECT / upstream / '.gitignore').read_bytes())
        local = [upstream + '/R5FlashWorkbench/engine/templates/capture.so',
                 upstream + '/R5FlashWorkbench/engine/templates.json']
        for name in local:
            self.write(name)
        self.assertFalse(set(local) & set(release.candidates(self.root)))

    def test_force_tracked_private_file_is_still_rejected(self):
        subprocess.run(['git', 'init', '--quiet', str(self.root)], check=True)
        name = 'hidden.pem'
        self.write(name, b'-----BEGIN '+b'PRIVATE KEY-----\nfixture\n')
        subprocess.run(['git', '-C', str(self.root), 'add', '-f', name], check=True)
        records, errors = release.inspect(self.root, release.candidates(self.root))
        self.assertIn(name, [r['path'] for r in records])
        self.assertIn('包含私钥正文', [r['reason'] for r in errors])

    def test_disguised_credentials_and_executable_cannot_export(self):
        for raw in (b'-----BEGIN '+b'OPENSSH PRIVATE KEY-----\nfixture\n',
                    b'$6$'+b'fixture$'+b'A'*86,
                    b'\x7fELF'+b'fixture'):
            with self.subTest(kind=raw[:4]):
                self.write('notes.txt', raw)
                _, errors = release.inspect(self.root, ['notes.txt'])
                self.assertTrue(errors)

    def test_unknown_large_file_is_still_rejected(self):
        self.write('unknown.data', bytes((10 << 20) + 1))
        _, errors = release.inspect(self.root, ['unknown.data'])
        self.assertIn('超过项目源码文件大小门槛10MiB', [row['reason'] for row in errors])

    def test_export_matches_bytes_and_refuses_overwrite_change_or_link(self):
        p = self.write('module.py')
        records, errors = release.inspect(self.root, ['module.py'])
        self.assertEqual(errors, [])
        dest = self.root.parent/'export'
        release.export(self.root, dest, records)
        self.assertEqual((dest/'module.py').read_bytes(), p.read_bytes())
        with self.assertRaises(ValueError):
            release.export(self.root, dest, records)
        p.write_text('changed')
        with self.assertRaises(ValueError):
            release.export(self.root, Path(self.temp.name)/'changed', records)
        (self.root/'linked.py').symlink_to(p)
        self.assertTrue(release.inspect(self.root, ['linked.py'])[1])

    def test_local_input_missing_wrong_hash_and_symlink_are_closed(self):
        records = [dict(path='absent'), dict(path='input', sha256='0'*64), dict(path='link')]
        p = self.write('input')
        (self.root/'link').symlink_to(p)
        result = inputs.check(self.root, records)
        self.assertEqual([r['status'] for r in result], ['missing', 'hash_mismatch', 'symlink_rejected'])


if __name__ == '__main__':
    unittest.main()
