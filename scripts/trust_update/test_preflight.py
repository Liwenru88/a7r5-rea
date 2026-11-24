"""使用合成 USB 快照验证一键入口的只读兼容预检。"""

import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
LAUNCHER = '一键更新信任环境.command'


def camera(location=0x02140000, serial='test-a', *, model='ILCE-7RM5', pid=0x0e0a):
    return {
        'IOObjectClass': 'IOUSBHostDevice',
        'IORegistryEntryChildren': [{'IOObjectClass': 'IOUSBMassStorageDriver'}],
        'USB Product Name': model,
        'USB Serial Number': serial,
        'idVendor': 0x054c,
        'idProduct': pid,
        'locationID': location,
        'bcdDevice': 0x0200,
    }


class TestPreflight(unittest.TestCase):
    def invoke(self, devices, version=None):
        with tempfile.TemporaryDirectory(prefix='a7r5-preflight-') as temp:
            root = Path(temp)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            (bin_dir / 'python3').symlink_to(Path(sys.executable).absolute())
            snapshot = root / 'usb snapshot.plist'
            snapshot.write_bytes(plistlib.dumps(devices))
            args = [str(HERE / LAUNCHER), '--check-only', '--usb-snapshot', str(snapshot)]
            if version is not None:
                args += ['--firmware-version', version]
            return subprocess.run(
                args,
                cwd=root,
                env={'PATH': f'{bin_dir}:/usr/bin:/bin'},
                capture_output=True,
                text=True,
                timeout=10,
            )

    def test_supported_baseline_across_bodies_and_ports(self):
        cases = [(camera(), [1, 4]), (camera(0x03210000, 'test-b'), [2, 1])]
        for device, ports in cases:
            with self.subTest(ports=ports):
                result = self.invoke([device], '4.00')
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report['status'], 'baseline_precheck_passed')
                self.assertEqual(report['usb']['ports'], ports)
                self.assertEqual(report['firmware']['source'], 'operator')
                self.assertFalse(report['firmware']['verified_on_device'])
                self.assertNotIn(device['USB Serial Number'], result.stdout)

    def test_firmware_version_must_be_confirmed(self):
        for version, status in [(None, 'firmware_unconfirmed'), ('4.31', 'firmware_mismatch')]:
            with self.subTest(version=version):
                result = self.invoke([camera()], version)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], status)

    def test_rejects_unsupported_usb_connections(self):
        for devices in ([], [camera(), camera(0x03210000)], [camera(model='ILCE-7M4')], [camera(pid=0x0336)]):
            with self.subTest(devices=devices):
                result = self.invoke(devices, '4.00')
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'usb_unavailable')

    def test_rejects_check_flag_after_update_engine(self):
        result = subprocess.run(
            [str(HERE / LAUNCHER), 'kit', '--check-only'],
            env={'A7R5_PYTHON': '/usr/bin/false'},
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('--check-only', result.stderr)


if __name__ == '__main__':
    unittest.main()
