"""独立清单的拒绝路径；不创建或启动虚拟机。"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import environment
from build_guest import identity_fixture


class RuntimeContract(unittest.TestCase):
    def test_manifest_rejects_invalid_inputs_before_launch(self):
        with tempfile.TemporaryDirectory(dir=environment.LAB/'build',prefix='aspect-contract-') as directory:
            root=Path(directory);build=root/'build';build.mkdir()
            records={}
            for name in ('binary','kernel','initrd','dtb','gpe'):
                path=build/name;path.write_bytes(name.encode())
                records[name]={'path':'build/'+name,'bytes':len(name),
                               'sha256':hashlib.sha256(name.encode()).hexdigest()}
            manifest={'schema':'a7r5-aspect406-runtime/1','model':'ILCE-7RM5',
                      'AP_sha256':environment.AP_SHA,'files':records}
            target=build/'manifest.json'
            vm=object.__new__(environment.AspectVM);vm.manifest_path=target
            with patch.object(environment,'LAB',root):
                target.write_text(json.dumps(manifest))
                self.assertEqual(set(vm.runtime_inputs()),set(records))
                mutations=[('schema','unknown'),('AP_sha256','0'*64)]
                for key,value in mutations:
                    candidate=copy.deepcopy(manifest);candidate[key]=value
                    target.write_text(json.dumps(candidate))
                    with self.subTest(key=key),self.assertRaises(ValueError):vm.runtime_inputs()
                for value in ('/tmp/outside','../../outside','build/missing'):
                    candidate=copy.deepcopy(manifest);candidate['files']['initrd']['path']=value
                    target.write_text(json.dumps(candidate))
                    with self.subTest(path=value),self.assertRaises((ValueError,OSError)):vm.runtime_inputs()
                for field,value in (('bytes',99),('sha256','0'*64)):
                    candidate=copy.deepcopy(manifest);candidate['files']['initrd'][field]=value
                    target.write_text(json.dumps(candidate))
                    with self.subTest(field=field),self.assertRaises(ValueError):vm.runtime_inputs()
                candidate=copy.deepcopy(manifest);candidate['files'].pop('dtb')
                target.write_text(json.dumps(candidate))
                with self.assertRaises(ValueError):vm.runtime_inputs()
                link=build/'linked';link.symlink_to(build/'initrd')
                candidate=copy.deepcopy(manifest);candidate['files']['initrd']['path']='build/linked'
                target.write_text(json.dumps(candidate))
                with self.assertRaises(ValueError):vm.runtime_inputs()

    def test_identity_uses_verified_header_and_rejects_other_model(self):
        header={'major':4,'minor':6,'model':0x11030080,'region':0}
        raw,version=identity_fixture(header)
        self.assertEqual(len(raw),4194304)
        self.assertEqual(version,b'\x06\x04')
        with self.assertRaises(ValueError):identity_fixture(dict(header,model=0))


if __name__=='__main__':unittest.main()
