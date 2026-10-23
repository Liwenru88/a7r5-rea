"""新位置解析与只验收启动的边界；不访问主机或网络。"""
import json
from pathlib import Path
import plistlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import operation as op
import host
from recovery import RecoveryPending


class HostTests(unittest.TestCase):
    def test_location_rebinding_preserves_pending_identity_and_rejects_other_port(self):
        for location,pid in ((0x00100000,0x0e0a),(0x00100000,0x096f),(0x01100000,0x0e0a)):
            tree=[{'IOObjectClass':'IOUSBHostDevice','idVendor':0x054c,'idProduct':pid,'USB Product Name':'ILCE-7RM5','locationID':location,
                   'IORegistryEntryChildren':[{'IOObjectClass':'IOUSBMassStorageDriver'},{'BSD Name':'disk9','Size':100,'Whole':True}]}]
            with self.subTest(location=location,pid=pid),patch.object(host.subprocess,'run',return_value=SimpleNamespace(stdout=plistlib.dumps(tree))):
                if location!=0x00100000:
                    with self.assertRaises(ValueError):host.snapshot(0x00100000)
                elif pid==0x096f:
                    with self.assertRaises(RecoveryPending) as caught:host.snapshot(0x00100000)
                    self.assertEqual(caught.exception.snapshot['location_id'],0x00100000)
                else:
                    value=host.snapshot(0x00100000)
                    self.assertEqual(value['location_id'],0x00100000);self.assertEqual(value['media'],[(True,100)])

    def test_execute_startup_never_connects_to_network_or_authenticates_ssh(self):
        op.lab.engine()
        import device
        for phase in ('deploy','collect'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();value=dict(run_id='abcd1234'*4,location_id=0x00100000)
                report=dict(protocol_gate_passed=True,service_stop_attempts=1,ssh_startup_verified=True)
                with patch.object(op,'regular_directory',return_value=root),patch.object(op,'checked_approval',return_value=value),patch.object(op.sys,'platform','darwin'),patch.object(op.os,'geteuid',return_value=0),patch.object(host,'snapshot',return_value={}),patch.object(device,'observe_recovery',return_value={'recovered':True}),patch.object(device,'save_result'),patch.dict(sys.modules,{'system_dump.session':SimpleNamespace(run_session=lambda *a,**kw:dict(report))}),patch('socket.socket',side_effect=AssertionError('本次不能从Mac连接网络')):
                    result=op.execute(root,phase,True)
                self.assertTrue(result['execution_succeeded']);self.assertEqual(result['mac_network_connections'],0)
                self.assertFalse(result['ssh_authentication_attempted']);self.assertFalse(result['external_network_verified']);self.assertFalse(result['ssh_root_login_verified'])

    def test_readiness_requires_banner_hash_and_wildcard_binding(self):
        import hashlib
        run='abcd1234'*4;banner=b'SSH-2.0-OpenSSH_7.9p1\r\n'
        raw=f'A7R5_WILDCARD_STARTED {run} pid=404 bind=0.0.0.0:2222 listener_observed=1 banner_sha={hashlib.sha256(banner).hexdigest()}\n'.encode()
        self.assertEqual(op.startup(raw,banner,run)['sshd_pid'],404)
        for changed,data in ((raw.replace(b'0.0.0.0',b'127.0.0.1'),banner),(raw,banner+b'extra'),(raw.replace(b'pid=404',b'pid=1'),banner)):
            with self.assertRaises(ValueError):op.startup(changed,data,run)


if __name__=='__main__':unittest.main(verbosity=2)
