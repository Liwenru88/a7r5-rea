"""独立4.10输入的拒绝路径；不创建或启动虚拟机。"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import environment


class RuntimeContract(unittest.TestCase):
    def test_unified_receipt_rejects_forged_chain_even_with_matching_receipt_file_digest(self):
        for name in ('native12-unified-look-pending-20261102-08','native12-unified-rapid-20261103-01'):
            original=environment.LAB/'build'/name/'manifest.json'
            record=json.loads(original.read_text())
            with tempfile.TemporaryDirectory(prefix='unified-identity-contract-',dir=environment.LAB/'build') as directory:
                root=Path(directory);manifest=root/'manifest.json';vm=object.__new__(environment.MenuVM);vm.manifest_path=manifest
                manifest.write_text(json.dumps(record));self.assertEqual(len(vm.runtime_inputs()),5)
                source=environment.LAB/record['unified_look_patch']['path'];receipt=json.loads(source.read_text())
                for key,value in (('schema','unknown'),('source_sha256','0'*64),('target_sha256','0'*64),('inverse_exact',False)):
                    wrong=copy.deepcopy(receipt);wrong[key]=value
                    path=root/(key+'.json');path.write_text(json.dumps(wrong))
                    altered=copy.deepcopy(record);altered['unified_look_patch']=environment.fact(path);manifest.write_text(json.dumps(altered))
                    with self.subTest(candidate=name,field=key),self.assertRaisesRegex(ValueError,'统一入口覆盖层来源'):vm.runtime_inputs()

    def test_sampling_retries_only_in_progress_marker_and_never_accepts_corruption(self):
        import struct
        from unittest.mock import Mock
        complete=struct.pack('<III',0x4d32314e,4095,12)
        read=Mock(side_effect=[bytes(12),complete]);advance=Mock()
        self.assertEqual(environment.coherent_snapshot(read,advance),complete)
        self.assertEqual(advance.call_count,1)
        for raw,reason in ((b'x','截断'),(b'x'*12,'身份'),(bytes(12),'持续')):
            advance=Mock()
            with self.subTest(reason=reason),self.assertRaisesRegex(RuntimeError,reason):
                environment.coherent_snapshot(lambda _:raw,advance)
            self.assertEqual(advance.call_count,19 if reason=='持续' else 0)

    def test_manifest_rejects_wrong_identity_missing_files_tampering_and_paths(self):
        with tempfile.TemporaryDirectory(prefix='native410-contract-',dir=environment.LAB/'build') as directory:
            root=Path(directory);folder=root/'build';folder.mkdir();files={}
            for name in ('binary','kernel','initrd','dtb','gpe'):
                path=folder/name;raw=name.encode();path.write_bytes(raw)
                files[name]=dict(path='build/'+name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            record=dict(schema='native12-410-menu/1',model='ILCE-7RM5',AP_sha256=environment.AP_SHA,
                        CP_sha256=environment.CP_SHA,DAT_sha256=environment.DAT_SHA,files=files)
            target=folder/'manifest.json';vm=object.__new__(environment.MenuVM);vm.manifest_path=target
            def check(value):target.write_text(json.dumps(value));return vm.runtime_inputs()
            with patch.object(environment,'LAB',root):
                self.assertEqual(set(check(record)),set(files))
                for key in ('schema','model','AP_sha256','CP_sha256','DAT_sha256'):
                    wrong=copy.deepcopy(record);wrong[key]='unknown'
                    with self.subTest(key=key),self.assertRaises(ValueError):check(wrong)
                wrong=copy.deepcopy(record);wrong['files'].pop('dtb')
                with self.assertRaises(ValueError):check(wrong)
                for path in ('/tmp/outside','../../outside','build/missing'):
                    wrong=copy.deepcopy(record);wrong['files']['initrd']['path']=path
                    with self.subTest(path=path),self.assertRaises((ValueError,OSError)):check(wrong)
                for key,value in (('bytes',99),('sha256','0'*64)):
                    wrong=copy.deepcopy(record);wrong['files']['initrd'][key]=value
                    with self.subTest(key=key),self.assertRaises(ValueError):check(wrong)
                link=folder/'linked';link.symlink_to(folder/'initrd')
                wrong=copy.deepcopy(record);wrong['files']['initrd']['path']='build/linked'
                with self.assertRaises(ValueError):check(wrong)


if __name__=='__main__':unittest.main()
