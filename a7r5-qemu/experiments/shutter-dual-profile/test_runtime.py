"""固定输入失败路径；不启动虚拟机或修改已有清单。"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sound_runtime_guard',HERE/'environment.py')
env=importlib.util.module_from_spec(spec)
spec.loader.exec_module(env)


class RuntimeGuards(unittest.TestCase):
    def reject(self,kind):
        original=json.loads((env.LAB/'build/shutter-dual-20261111-06/manifest.json').read_text())
        record=copy.deepcopy(original)
        if kind=='unknown-candidate':record['AP_sha256']='0'*64
        else:record['files']['binary']['sha256']='0'*64
        with tempfile.TemporaryDirectory(prefix='r5-sound-guard-') as tmp:
            root=Path(tmp).resolve()
            path=root/'build/test/manifest.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(record))
            vm=env.MenuVM.__new__(env.MenuVM)
            vm.manifest_path=path
            expected='固定组件' if kind=='unknown-candidate' else '客体材料'
            with patch.object(env,'LAB',root),self.assertRaisesRegex(ValueError,expected):
                vm.runtime_inputs()

    def test_unknown_candidate(self):self.reject('unknown-candidate')
    def test_corrupt_binary_hash(self):self.reject('corrupt-binary-hash')


if __name__=='__main__':unittest.main()
