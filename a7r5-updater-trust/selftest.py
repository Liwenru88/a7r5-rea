#!/usr/bin/env python3
"""仅在本机验证源身份、差异分类及输出拒绝条件，不读取设备。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import trust_tool as tool
from trust_recipe import verified_library, compress_exact
from sector_plan import make_plan, classify


class OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old=SOURCE.read_bytes()
        cls.new=CANDIDATE.read_bytes()
        cls.plan=make_plan(cls.old,cls.new)

    def test_exact_old_new_and_known_mixture(self):
        for raw,state in ((self.old,'EXACT_ORIGINAL'),(self.new,'EXACT_CANDIDATE')):
            self.assertEqual(classify(raw,self.old,self.new,self.plan['rows'])['state'],state)
        mixed=bytearray(self.old);row=self.plan['rows'][0];at=row['offset']
        mixed[at:at+512]=self.new[at:at+512]
        self.assertEqual(classify(bytes(mixed),self.old,self.new,self.plan['rows'])['state'],'KNOWN_OLD_NEW_MIXTURE')

    def test_unknown_byte_outside_or_inside_changed_sector_rejected(self):
        first=self.plan['rows'][0]['offset']
        for at in (0,first):
            with self.subTest(offset=at):
                bad=bytearray(self.old)
                bad[at]=next(v for v in range(256)if v not in (self.old[at],self.new[at]))
                with self.assertRaises(ValueError):classify(bytes(bad),self.old,self.new,self.plan['rows'])
        with self.assertRaises(ValueError):classify(self.new[:-1],self.old,self.new,self.plan['rows'])

    def test_logical_sector_scope_and_inverse(self):
        self.assertEqual((self.plan['changed_bytes'],self.plan['changed_sectors']), (128469,258))
        self.assertEqual([r['phase']for r in self.plan['rows']], ['initrd']*257+['checksum'])
        self.assertEqual(self.plan['rows'][-1]['offset'],15843840)
        reverse=bytearray(self.new)
        for row in self.plan['rows']:
            at=row['offset'];reverse[at:at+512]=self.old[at:at+512]
        self.assertEqual(bytes(reverse),self.old)

    def test_library_patch_and_original_RSA_preserved(self):
        oldsq=tool.SquashImage(tool.FatImage(self.old).read('/boot/initrd.img'))
        newsq=tool.SquashImage(tool.FatImage(self.new).read('/boot/initrd.img'))
        for name in ('libupdaterapi.so','libsdfileinputupdaterapi.so','libseninputupdaterapi.so','libuudfileinputupdaterapi.so'):
            with self.subTest(library=name):
                before=oldsq.read('/usr/lib/'+name)
                after,record=verified_library(before,name)
                self.assertEqual(after,newsq.read('/usr/lib/'+name))
                self.assertTrue(record['VerifySignature_372_bytes_unchanged'])
                bad=bytearray(before);bad[0]^=1
                with self.assertRaises(ValueError):verified_library(bytes(bad),name)

    def test_compressed_length_must_be_exact(self):
        import zlib
        raw=b'A7R5-test-fragment'*64
        self.assertEqual(zlib.decompress(compress_exact(raw,len(zlib.compress(raw,9)))),raw)
        with self.assertRaises(ValueError):compress_exact(raw,1)

    def test_device_symlink_and_existing_output_rejected(self):
        with tempfile.TemporaryDirectory(prefix='a7r5-trust-test-') as temp:
            parent=Path(temp).resolve();link=parent/'link';link.symlink_to(SOURCE)
            for value in ('/dev/rdisk0',link):
                with self.subTest(path=str(value)):
                    with self.assertRaises(ValueError):tool.read_regular(value)
            bad=parent/'bad.img';bad.write_bytes(b'bad')
            with self.assertRaises(ValueError):tool.fixed_source(bad)
            with self.assertRaises(ValueError):tool.build(SOURCE,KEY,parent)
            wrong=parent/'wrong.pem';wrong.write_bytes(b'wrong')
            with self.assertRaises(ValueError):tool.build(SOURCE,wrong,parent/'new')
            self.assertFalse((parent/'new').exists())


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--candidate',required=True,type=Path)
    parser.add_argument('--public-key',required=True,type=Path)
    args=parser.parse_args()
    SOURCE=args.source.resolve();CANDIDATE=args.candidate.resolve();KEY=args.public_key.resolve()
    tool.fixed_source(SOURCE)
    _,candidate=tool.read_regular(CANDIDATE)
    tool.require(tool.sha(candidate)==tool.TARGET_SHA,'测试候选不匹配')
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OfflineTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
