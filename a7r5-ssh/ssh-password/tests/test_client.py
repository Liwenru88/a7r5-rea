"""一次密码连接的失败边界；替身隔离网络，不访问相机。"""
import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import operation as op
op.dependencies()
import paramiko


class ClientTests(unittest.TestCase):
    def test_single_connection_pins_key_before_auth_and_bounds_readonly_output(self):
        host = paramiko.ECDSAKey.generate()
        public = b'ecdsa-sha2-nistp256 ' + base64.b64encode(host.asbytes()) + b'\n'
        good = b'Name:\tcat\nUid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\n'
        for fault in ('success', 'timeout', 'host_key', 'auth', 'nonroot', 'duplicate', 'too_large', 'stderr', 'exit'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); (root/'host-public-key').write_bytes(public)
                (root/'client-password').write_text('T'*32+'\n');(root/'client-password').chmod(0o600)
                value = dict(target_ip=op.TARGET_IP, port=2222, ssh_command=op.FIXED_COMMAND, directory=str(root))
                report = dict(host_public_sha256=hashlib.sha256(public).hexdigest())
                sock = MagicMock(); transport = MagicMock(); channel = MagicMock()
                if fault == 'timeout': sock.connect.side_effect = TimeoutError('模拟单次连接超时')
                transport.get_remote_server_key.return_value = MagicMock(asbytes=lambda: b'foreign') if fault == 'host_key' else host
                if fault == 'auth': transport.auth_password.side_effect = paramiko.AuthenticationException('拒绝')
                transport.is_authenticated.return_value = True
                transport.open_session.return_value = channel
                data = good.replace(b'Uid:\t0', b'Uid:\t1') if fault == 'nonroot' else good
                if fault == 'duplicate': data += b'Uid:\t0\t0\t0\t0\n'
                if fault == 'too_large': data = b'x'*4097
                chunks = [data]; errors = [b'error'] if fault == 'stderr' else []
                channel.recv_ready.side_effect = lambda: bool(chunks)
                channel.recv.side_effect = lambda size: chunks.pop(0)
                channel.recv_stderr_ready.side_effect = lambda: bool(errors)
                channel.recv_stderr.side_effect = lambda size: errors.pop(0)
                channel.exit_status_ready.return_value = True
                channel.eof_received = True
                channel.recv_exit_status.return_value = 1 if fault == 'exit' else 0
                with patch('socket.socket', return_value=sock), patch.object(paramiko, 'Transport', return_value=transport), patch.object(transport,'auth_publickey',side_effect=AssertionError('禁止公钥认证')):
                    if fault == 'success':
                        op.client_once(value, root, report)
                        self.assertTrue(report['ssh_root_login_verified'])
                    else:
                        with self.assertRaises((ValueError, TimeoutError, paramiko.AuthenticationException)):
                            op.client_once(value, root, report)
                        self.assertFalse(report.get('ssh_root_login_verified', False))
                sock.connect.assert_called_once_with(('10.10.10.177', 2222))
                self.assertLessEqual(transport.auth_password.call_count, 1)
                self.assertLessEqual(channel.exec_command.call_count, 1)
                if fault in ('timeout', 'host_key'): transport.auth_password.assert_not_called()
                if fault == 'success':
                    channel.exec_command.assert_called_once_with(op.FIXED_COMMAND)
                    transport.auth_password.assert_called_once_with('root','T'*32,fallback=False)
                sock.close.assert_called_once()

    def test_changed_usb_key_or_target_rejected_without_opening_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'host-public-key').write_bytes(b'changed')
            with patch('socket.socket', side_effect=AssertionError('不能连接')):
                for address in (op.TARGET_IP, 'example.com', '10.10.10.118'):
                    value=dict(target_ip=address, port=2222, ssh_command=op.FIXED_COMMAND, directory=str(root))
                    with self.assertRaises(ValueError): op.client_once(value, root, dict(host_public_sha256='0'*64))


if __name__=='__main__': unittest.main(verbosity=2)
