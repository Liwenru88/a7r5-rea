"""与风险对应的本机拒绝路径；不导入USB、不联网、不读取原卡。"""
import base64
import json
import hashlib
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build
import mac_client
import package


class MaterialTests(unittest.TestCase):
    def test_fixed_configuration_policy_and_target_render(self):
        # 使用真实构建产物检查会失效的接口边界：无强制命令、TTY和SFTP开启、禁止转发。
        path=Path(__file__).resolve().parents[1]/'verification'
        candidates=sorted(path.glob('service-qemu-*/candidate/build.json'),key=lambda p:p.stat().st_mtime)
        self.assertTrue(candidates)
        config=(candidates[-1].parent/'config.h').read_text()
        self.assertIn('PermitTTY yes\\n',config)
        self.assertIn('Subsystem sftp internal-sftp\\n',config)
        self.assertIn('#define SSH_SECONDS 0',config)
        self.assertNotIn('ForceCommand ',config)
        self.assertIn('AllowTcpForwarding no\\n',config)

    def test_material_tampering_and_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();artifact=root/'helper';artifact.write_bytes(b'original')
            manifest=dict(schema='a7r5-ssh-service-materials-v1',run_id='a'*32,camera_installation_approved=False,autostart_enabled=False,
                          execution_state='OFFLINE_MATERIALS_ONLY',install_directory='/tmp/jiritsu/a7r5-ssh-service-'+'a'*32,ttl_seconds=0,port=2222,
                          files={'helper':dict(bytes=8,sha256=build.sha(artifact))})
            (root/'manifest.json').write_text(json.dumps(manifest));package.check(root)
            artifact.write_bytes(b'changed!')
            with self.assertRaises(ValueError):package.check(root)
            artifact.unlink();artifact.symlink_to(root/'manifest.json')
            with self.assertRaises(ValueError):package.check(root)

    def test_missing_trusted_key_blocks_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'manifest.json').write_text(json.dumps(dict(run_id='a'*32)))
            with patch.object(mac_client,'ROOT',root),patch.object(sys,'argv',['mac_client.py','ssh']),patch('subprocess.call') as network:
                with self.assertRaises(ValueError):mac_client.main()
                network.assert_not_called()

    def test_non_target_addresses_blocked_before_network(self):
        for ip in ('0.0.0.0','127.0.0.1','224.0.0.1','8.8.8.8','not-an-ip'):
            with self.subTest(ip=ip),patch.object(sys,'argv',['mac_client.py','ssh','--ip',ip]),patch('subprocess.call') as network:
                with self.assertRaises(ValueError):mac_client.main()
                network.assert_not_called()

    def test_untrusted_or_other_key_types_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'key'
            for raw in ('ssh-ed25519 AAAA','ecdsa-sha2-nistp256 '+base64.b64encode(b'bad blob').decode(),'ecdsa-sha2-nistp256 !!!'):
                path.write_text(raw)
                with self.assertRaises(ValueError):mac_client.trusted_key(path)

    def test_control_refusal_preserves_files(self):
        for condition in ('unknown_preload','retired_package'):
            with self.subTest(condition=condition),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve();install=root/'install';install.mkdir();run='b'*32
                for name,raw in (('ssh-service.arm64',b'helper'),('boot-hook.so',b'hook'),('preload.backup',b'\n'*512)):
                    (install/name).write_bytes(raw)
                preload=root/'preload';preload.write_bytes(b'\n'*(511 if condition=='unknown_preload' else 512))
                if condition=='retired_package':(install/('disabled-marker-'+run)).write_text(run+'\n')
                sha=lambda raw:hashlib.sha256(raw).hexdigest()
                values=dict(INSTALL=str(install),RUN=run,NEUTRAL_SHA=sha(b'\n'*512),HOOK_LINE_SHA=sha((str(install)+'/boot-hook.so\n').encode()),
                            HELPER_SHA=sha(b'helper'),HOOK_SHA=sha(b'hook'),MARKER_SHA=sha((run+'\n').encode()))
                script=package.render('control.sh',values).replace("P='/etc/ld.so.preload'","P="+__import__('shlex').quote(str(preload)))
                before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
                result=subprocess.run(['/bin/sh','-s','--','enable-autostart','ENABLE_AUTOSTART_'+run],input=script,text=True,capture_output=True)
                self.assertEqual(result.returncode,1);self.assertIn(condition,result.stderr)
                self.assertEqual(before,{str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})


if __name__=='__main__':unittest.main()
