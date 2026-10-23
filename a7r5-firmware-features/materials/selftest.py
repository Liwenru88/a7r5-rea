#!/usr/bin/env python3
"""用临时合成工作副本验证重建入口的成功和拒绝条件，不读取固件或设备。"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch as mock_patch

import reproduce as r


class ReproductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='a7r5-doc-selftest-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.receipt = self.root / 'receipt.json'
        self.ap = self.work / 'ap.bin'
        self.wbi = self.work / 'wbi.bin'
        self.ap.write_bytes(b'AP00')
        self.wbi.write_bytes(b'WBI2')

        def recipe(name, before, after):
            return dict(path=name, before_bytes=len(before), after_bytes=len(after),
                before_sha256=r.sha(before), after_sha256=r.sha(after),
                patches=[dict(offset=3, before=before[3:].hex(), after=after[3:].hex())])

        self.rec = recipe('ap.bin', b'AP00', b'AP01')
        self.recipe = dict(official_DAT_sha256='test-source', integrated=[self.rec],
            ntsc_only=self.rec, resources=[], names=['n']*6,
            WBI=recipe('wbi.bin', b'WBI2', b'WBI3'))
        (self.root / 'recipes.json').write_text(json.dumps(self.recipe))
        (self.work / 'manifest.json').write_text(json.dumps(dict(
            source=dict(sha256='test-source'), header=dict(major=4, minor=0))))
        self.here = mock_patch.object(r, 'HERE', self.root)
        self.here.start()
        self.addCleanup(self.here.stop)

    def save_recipe(self):
        (self.root / 'recipes.json').write_text(json.dumps(self.recipe))

    def test_success_and_refuse_second_application(self):
        for feature in ('all', 'ntsc-only'):
            with self.subTest(feature=feature):
                self.ap.write_bytes(b'AP00'); self.wbi.write_bytes(b'WBI2')
                receipt = self.root / (feature+'.json')
                self.assertEqual(r.run(self.work, feature, receipt)['status'], 'WORKSPACE_COMPONENTS_VERIFIED')
                self.assertEqual(self.ap.read_bytes(), b'AP01')
                self.assertEqual(self.wbi.read_bytes(), b'WBI3')
                with self.assertRaises(ValueError):
                    r.run(self.work, feature, self.receipt)
                self.assertEqual(self.ap.read_bytes(), b'AP01')

    def test_bad_later_preimage_changes_nothing(self):
        self.wbi.write_bytes(b'FAIL')
        with self.assertRaises(ValueError): r.run(self.work, 'all', self.receipt)
        self.assertEqual(self.ap.read_bytes(), b'AP00')
        self.assertFalse(self.receipt.exists())

    def test_bad_resource_rejects_before_any_replacement(self):
        self.recipe['resources'] = [dict(path='ap.bin', before_bytes=4, before_sha256=r.sha(b'AP00'))]
        self.save_recipe()
        with self.assertRaises(ValueError): r.run(self.work, 'all', self.receipt)
        self.assertEqual(self.ap.read_bytes(), b'AP00')

    def test_wrong_manifest_source(self):
        p=self.work/'manifest.json'; doc=json.loads(p.read_text())
        doc['source']['sha256']='wrong'; p.write_text(json.dumps(doc))
        with self.assertRaises(ValueError): r.run(self.work, 'all', self.receipt)
        self.assertEqual(self.ap.read_bytes(), b'AP00')

    def test_receipt_must_be_new_with_existing_parent(self):
        self.receipt.write_text('preserve')
        for out in (self.receipt, self.root/'missing'/'receipt.json'):
            with self.subTest(path=str(out)):
                with self.assertRaises(ValueError): r.run(self.work, 'all', out)
        self.assertEqual(self.ap.read_bytes(), b'AP00')
        self.assertEqual(self.receipt.read_text(), 'preserve')

    def test_dangling_receipt_symlink_is_rejected(self):
        self.receipt.symlink_to(self.root/'absent')
        with self.assertRaises(ValueError): r.run(self.work, 'all', self.receipt)
        self.assertEqual(self.ap.read_bytes(), b'AP00')

    def test_path_traversal_absolute_and_symlink(self):
        for name in ('../ap.bin', '/dev/rdisk0', 'a//b', './ap.bin'):
            with self.subTest(path=name):
                with self.assertRaises(ValueError): r.path_in(self.work,name)
        (self.work/'link').symlink_to(self.ap)
        with self.assertRaises(ValueError): r.path_in(self.work,'link')

    def test_overlapping_patch_and_wrong_target_digest(self):
        for key, value in (('patches', self.rec['patches']*2), ('after_sha256', 'wrong')):
            rec=dict(self.rec);rec[key]=value
            with self.subTest(key=key):
                with self.assertRaises(ValueError): r.patch(b'AP00',rec)

    def test_partial_write_failure_is_recorded_and_not_hidden(self):
        original=r.os.replace; calls=[]
        def failing_replace(source,target):
            calls.append(target)
            if len(calls)==2: raise OSError('模拟第二次工作文件替换失败')
            return original(source,target)
        with mock_patch.object(r.os, 'replace', failing_replace):
            with self.assertRaises(OSError): r.run(self.work, 'all', self.receipt)
        report=json.loads(self.receipt.read_text())
        self.assertEqual(report['status'], 'FAILED_PARTIAL_WORKSPACE_DO_NOT_PACK')
        self.assertEqual(len(report['files']),1)
        self.assertEqual(self.ap.read_bytes(),b'AP01')
        self.assertEqual(self.wbi.read_bytes(),b'WBI2')


if __name__ == '__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ReproductionTests)
    output=io.StringIO()
    result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
    print(output.getvalue(),end='')
    raise SystemExit(0 if result.wasSuccessful() else 1)
