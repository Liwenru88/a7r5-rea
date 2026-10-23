"""口令不进入命令参数，权限/格式错误必须在连接前拒绝。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import credentials
import operation as op


class CredentialTests(unittest.TestCase):
    def test_random_password_hash_generation_and_private_file_validation(self):
        original=subprocess.run
        def observed(args,**kwargs):
            self.assertNotIn(kwargs['input'].strip(),args)
            self.assertNotIn('shell',kwargs)
            return original(args,**kwargs)
        with patch.object(credentials.subprocess,'run',side_effect=observed):
            password,hashed=credentials.generate()
        self.assertEqual(len(password),32);self.assertTrue(credentials.valid_hash(hashed))
        self.assertNotIn(password,hashed)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();p=root/'password';p.write_text(password+'\n');p.chmod(0o600)
            self.assertEqual(credentials.load(p),password)
            p.chmod(0o644)
            with self.assertRaises(PermissionError):credentials.load(p)
            p.chmod(0o600);p.write_text('short\n')
            with self.assertRaises(ValueError):credentials.load(p)
            link=root/'link';link.symlink_to(p)
            with self.assertRaises(PermissionError):credentials.load(link)

    def test_predecessor_cleanup_and_screen_proofs_are_required(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(op,'PREDECESSOR',Path(tmp).resolve()):
            root=Path(tmp).resolve();out=root/'result-collect';out.mkdir()
            with self.assertRaises(FileNotFoundError):op.predecessor_proof()
            value=dict(run_id=op.PREDECESSOR_RUN,protocol_gate_passed=True,guest_final_cleanup_verified=True,
                       parent_account_nss_config_unchanged_receipt=True,listener_absence_verified=True,
                       preload_neutral_verified=True,host_recovery_verified=True,service_stop_attempts=1)
            screen=dict(run_id=op.PREDECESSOR_RUN,screen_normal=True,source='direct_human_reply')
            (out/'phase-result.json').write_text(json.dumps(value))
            (root/'screen-collect-confirmation.json').write_text(json.dumps(screen))
            self.assertEqual(op.predecessor_proof()['run_id'],op.PREDECESSOR_RUN)
            for fault in ('host_recovery_verified','guest_final_cleanup_verified','listener_absence_verified'):
                changed=value|{fault:False};(out/'phase-result.json').write_text(json.dumps(changed))
                with self.assertRaises(PermissionError):op.predecessor_proof()
            (out/'phase-result.json').write_text(json.dumps(value))
            (root/'screen-collect-confirmation.json').write_text(json.dumps(screen|{'screen_normal':False}))
            with self.assertRaises(PermissionError):op.predecessor_proof()


if __name__=='__main__':unittest.main()
