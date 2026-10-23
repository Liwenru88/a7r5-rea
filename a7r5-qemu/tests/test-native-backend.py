"""独立项目输入契约、原生派发及真实 macOS 沙箱回归。"""
import importlib.util
import json
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/'tools'))
from native_vm import dtb_properties,sandbox_profile
from runtime_manifest import verified_inputs
spec=importlib.util.spec_from_file_location('menu_ui',LAB/'tools/menu-ui.py')
ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)

class NativeContract(unittest.TestCase):
    def test_active_guest_matches_device_tree(self):
        inputs=verified_inputs();props=dtb_properties(inputs['dtb'].read_bytes())
        start=int.from_bytes(props[('/chosen','linux,initrd-start')],'big')
        end=int.from_bytes(props[('/chosen','linux,initrd-end')],'big')
        self.assertEqual(start,0x440000000)
        self.assertEqual(end-start,inputs['initrd'].stat().st_size)
        for raw in (b'not a tree',bytes(40)):
            with self.assertRaises((ValueError,struct.error)):dtb_properties(raw)

    def test_native_dispatch_uses_project_python_and_paths(self):
        with patch.object(ui.subprocess,'Popen') as popen:
            session=ui.Session();command=popen.call_args.args[0]
            self.assertEqual(command[0],sys.executable)
            self.assertEqual(command[2],str(LAB/'tools/probe-app.py'))
            self.assertIn('--apply-menu',command)
            self.assertEqual(Path(command[-1]).parent,LAB/'runs')
            session.log.close()

    def test_missing_image_dependency_stops_before_vm_creation(self):
        spec=importlib.util.spec_from_file_location('probe_app',LAB/'tools/probe_app.py')
        probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
        argv=['probe-app.py','--without-bluetooth','--software-gpe','--capid','--boot-services','--gui-trace','--apply-menu']
        with patch.object(sys,'argv',argv),patch.dict(sys.modules,{'PIL':None}),patch.object(probe,'NativeVM') as vm:
            with self.assertRaises(ModuleNotFoundError):probe.main()
            vm.assert_not_called()

    def test_manifest_rejects_tampering_and_external_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=json.loads((LAB/'runtime/manifest.json').read_text())
            for key,record in manifest['files'].items():
                path=root/record['path'];path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(b'pinned');record.update(bytes=6,sha256=hashlib.sha256(b'pinned').hexdigest())
            target=root/'runtime/manifest.json';target.write_text(json.dumps(manifest));verified_inputs(root)
            original=dict(manifest['files']['kernel'])
            for invalid in ('../../outside','/tmp/outside'):
                manifest['files']['kernel']['path']=invalid;target.write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):verified_inputs(root)
            manifest['files']['kernel']=original;target.write_text(json.dumps(manifest))
            path=root/original['path'];path.write_bytes(b'edited')
            with self.assertRaisesRegex(ValueError,'摘要或长度'):verified_inputs(root)
            path.unlink();path.symlink_to(LAB/'runtime/vmlinux.bin')
            with self.assertRaisesRegex(ValueError,'符号链接'):verified_inputs(root)

    def test_real_macos_policy_enforces_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='policy-',dir=LAB/'build') as directory,tempfile.TemporaryDirectory(prefix='a7r5-test-',dir='/private/tmp') as controls:
            root=Path(directory);control=Path(controls);output=root/'out';output.mkdir()
            binary=root/'policy-test'
            subprocess.run(['/usr/bin/clang','-O2',str(LAB/'tools/test-native-sandbox.c'),'-o',str(binary)],check=True)
            source=root/'input';source.write_bytes(b'unchanged')
            private=root/'private';private.write_bytes(b'not allowed')
            outside=root/'outside';inside=output/'owned'
            profile=root/'native.sb';profile.write_text(sandbox_profile(binary,source,source,source,output,control))
            result=subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),str(binary),str(source),str(private),str(outside),str(inside),str(control/'qmp.sock')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(source.read_bytes(),b'unchanged');self.assertFalse(outside.exists())
            self.assertEqual(inside.read_bytes(),b'ok');print(result.stdout.strip())

if __name__=='__main__':unittest.main()
