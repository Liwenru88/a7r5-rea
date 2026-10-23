"""只用替身验证单地址契约，不建立真实网络连接。"""
import errno
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import n0


class FakeSocket:
    def __init__(self, chunks=(), connect_error=None, read_error=None):
        self.chunks = list(chunks)
        self.connect_error = connect_error
        self.read_error = read_error
        self.connections = []
        self.read_sizes = []
        self.closed = False

    def settimeout(self, value):
        assert 0 < value <= 5

    def connect(self, address):
        self.connections.append(address)
        if self.connect_error:
            raise self.connect_error

    def recv(self, size):
        self.read_sizes.append(size)
        if self.read_error:
            raise self.read_error
        if not self.chunks:
            return b""
        data = self.chunks.pop(0)
        self.chunks.insert(0, data[size:]) if len(data) > size else None
        return data[:size]

    def close(self):
        self.closed = True

    def send(self, *_):
        raise AssertionError("不得发送 SSH 应用数据")

    sendall = send


class N0Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "packages"
        self.patch = patch.object(n0, "PACKAGES", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def package(self, icmp=False):
        value = n0.target("192.168.50.23", 24, "camera-screen", "access-point", "disconnected", icmp)
        return n0.prepare("unit-once", value)

    def authorize(self, directory, **changes):
        value = n0.approval(directory, True)
        value.update(changes)
        n0.save(directory / "approval.json", value)

    def run_fake(self, directory, connection, ping=None):
        factory = unittest.mock.Mock(return_value=connection)
        runner = unittest.mock.Mock(side_effect=AssertionError("未允许 ICMP")) if ping is None else ping
        result = n0.execute(directory, True, socket_factory=factory, ping_runner=runner)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(connection.connections, [("192.168.50.23", 22)])
        self.assertTrue(connection.closed)
        self.assertFalse(result["ssh_authentication_attempted"])
        self.assertFalse(result["camera_file_writes"])
        self.assertEqual(result["application_bytes_sent"], 0)
        return result

    def test_rejects_ranges_names_special_addresses_and_broadcast(self):
        for address in ("camera.local", "192.168.50.0/24", "192.168.50.1,192.168.50.2",
                        "127.0.0.1", "0.0.0.0", "224.0.0.1", "8.8.8.8", "169.254.1.2",
                        "192.168.50.0", "192.168.50.255", "192.168.050.23", "192.168.50.23\n"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                n0.target(address, 24, "camera-screen", "access-point", "disconnected")
        for prefix in (True, 0, 31, 32):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                n0.target("192.168.50.23", prefix, "camera-screen", "access-point", "disconnected")
        # 不把任意 .0 地址误当成 /24 网络地址。
        self.assertEqual(n0.target("192.168.51.0", 23, "router-lease", "access-point", "mass-storage")["address"], "192.168.51.0")

    def test_default_cli_and_unapproved_package_never_open_network(self):
        directory = self.package()
        self.assertFalse((directory / "approval.json").exists())
        with patch("socket.socket", side_effect=AssertionError("不得联网")), patch("subprocess.run", side_effect=AssertionError("不得 ping")):
            self.assertEqual(n0.check(directory)["target"]["address"], "192.168.50.23")
            with self.assertRaises(PermissionError):
                n0.execute(directory)
            with self.assertRaises(FileNotFoundError):
                n0.execute(directory, True)
            n0.save(directory / "approval.json", n0.approval(directory))
            with self.assertRaises(PermissionError):
                n0.execute(directory, True)
        cli = subprocess.run([sys.executable, "-I", "-B", str(n0.SOURCE), "check", "--operation", str(directory)], capture_output=True, timeout=5)
        self.assertNotEqual(cli.returncode, 0)  # 独立 CLI 不接受测试临时根目录。

    def test_approval_tamper_expiry_and_paths_refuse_before_attempt(self):
        for fault in ("expired", "future", "readiness", "target", "symlink"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                with patch.object(n0, "PACKAGES", Path(tmp).resolve() / "packages"):
                    directory = self.package()
                    approved = n0.approval(directory, True)
                    if fault == "expired":
                        approved["approved_at_unix"] -= 1000
                        approved["expires_at_unix"] -= 1000
                    if fault == "future":
                        approved["approved_at_unix"] += 1000
                        approved["expires_at_unix"] += 1000
                    if fault == "readiness":
                        approved["readiness"]["address_current"] = False
                    if fault == "target":
                        plan = json.loads((directory / "plan.json").read_text())
                        plan["target"]["address"] = "192.168.50.24"
                        (directory / "plan.json").write_text(json.dumps(plan))
                    n0.save(directory / "approval.json", approved)
                    if fault == "symlink":
                        (directory / "approval.json").rename(directory / "other.json")
                        (directory / "approval.json").symlink_to(directory / "other.json")
                    with patch("socket.socket", side_effect=AssertionError("不得联网")), self.assertRaises((ValueError, PermissionError)):
                        n0.execute(directory, True)
                    self.assertFalse((directory / "ATTEMPT_LOCK").exists())

    def test_single_connection_reads_split_identification_and_never_retries(self):
        directory = self.package()
        self.authorize(directory)
        connection = FakeSocket([b"SSH-2.", b"0-OpenSSH_7.9\r", b"\n"])
        result = self.run_fake(directory, connection)
        self.assertEqual(result["outcome"], "TCP_CONNECTED_SSH_IDENTIFICATION")
        self.assertTrue(result["execution_succeeded"])
        self.assertFalse(result["camera_identity_cryptographically_verified"])
        self.assertTrue((directory / "ATTEMPT_LOCK").is_dir())
        with self.assertRaises(FileExistsError):
            n0.execute(directory, True, socket_factory=lambda *_: self.fail("不能重试"))
        self.assertEqual(len(connection.connections), 1)

    def test_banner_limit_timeout_and_unexpected_protocol_stop_without_ping(self):
        cases = (([b"x" * 300], None, "UNEXPECTED_IDENTIFICATION", False),
                 ([b"HTTP/1.0 200 OK\r\n"], None, "UNEXPECTED_IDENTIFICATION", False),
                 ([b"SSH-2.0-bad\x1b\r\n"], None, "UNEXPECTED_IDENTIFICATION", False),
                 ([], TimeoutError(), "TCP_CONNECTED_NO_IDENTIFICATION", True),
                 ([], OSError(errno.ECONNRESET, "reset"), "READ_FAILED", False))
        for chunks, error, outcome, succeeded in cases:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                with patch.object(n0, "PACKAGES", Path(tmp).resolve() / "packages"):
                    directory = self.package(True)
                    self.authorize(directory)
                    connection = FakeSocket(chunks, read_error=error)
                    result = self.run_fake(directory, connection)
                    self.assertEqual(result["outcome"], outcome)
                    self.assertEqual(result["execution_succeeded"], succeeded)
                    self.assertLessEqual(len(bytes.fromhex(result["banner_raw_hex"])), 256)

    def test_optional_icmp_is_exactly_one_packet_after_expected_connect_failure(self):
        directory = self.package(True)
        self.authorize(directory)
        connection = FakeSocket(connect_error=ConnectionRefusedError(errno.ECONNREFUSED, "refused"))
        runner = unittest.mock.Mock(return_value=subprocess.CompletedProcess([], 0, b"1 packets transmitted, 1 packets received", b""))
        result = self.run_fake(directory, connection, runner)
        self.assertEqual(result["outcome"], "ICMP_REPLY_TCP_REFUSED")
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.args[0], ["/sbin/ping", "-n", "-c", "1", "-W", "1000", "-t", "2", "192.168.50.23"])
        self.assertLessEqual(runner.call_args.kwargs["timeout"], 3)

    def test_fragmented_stream_has_fixed_read_deadline(self):
        directory = self.package(True)
        self.authorize(directory)
        connection = FakeSocket([b"x"] * 100)
        ticks = iter(range(100))
        with patch.object(n0.time, "monotonic", side_effect=lambda: next(ticks)):
            result = self.run_fake(directory, connection)
        self.assertEqual(result["outcome"], "TCP_CONNECTED_NO_IDENTIFICATION")
        self.assertLess(len(connection.read_sizes), 4)
        self.assertLessEqual(result["network_elapsed_seconds"], 12)

    def test_default_no_icmp_and_transport_errors_never_trigger_fallback(self):
        for error, icmp in ((TimeoutError(), False), (OSError(errno.ENETUNREACH, "unreachable"), True), (PermissionError("denied"), True)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
                with patch.object(n0, "PACKAGES", Path(tmp).resolve() / "packages"):
                    directory = self.package(icmp)
                    self.authorize(directory)
                    result = self.run_fake(directory, FakeSocket(connect_error=error))
                    self.assertFalse(result["execution_succeeded"])
                    self.assertFalse(result["icmp_attempted"])

    def test_ping_timeout_and_interrupt_preserve_attempt_and_failure_receipt(self):
        for error in (subprocess.TimeoutExpired("ping", 3), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
                with patch.object(n0, "PACKAGES", Path(tmp).resolve() / "packages"):
                    directory = self.package(True)
                    self.authorize(directory)
                    runner = unittest.mock.Mock(side_effect=error)
                    result = self.run_fake(directory, FakeSocket(connect_error=TimeoutError()), runner)
                    self.assertFalse(result["execution_succeeded"])
                    self.assertTrue(result["icmp_attempted"])
                    self.assertTrue((directory / "result.json").is_file())
                    self.assertTrue((directory / "ATTEMPT_LOCK").is_dir())

    def test_cli_reports_failed_probe_with_nonzero_status(self):
        directory = self.package()
        self.authorize(directory)
        connection = FakeSocket(connect_error=ConnectionRefusedError(errno.ECONNREFUSED, "refused"))
        argv = [str(n0.SOURCE), "run", "--operation", str(directory), "--network-io"]
        with patch.object(sys, "argv", argv), patch("socket.socket", return_value=connection), contextlib.redirect_stdout(io.StringIO()) as output:
            status = n0.main()
        self.assertEqual(status, 3)
        self.assertEqual(json.loads(output.getvalue())["outcome"], "TCP_REFUSED")
        self.assertEqual(connection.connections, [("192.168.50.23", 22)])


if __name__ == "__main__":
    unittest.main()
