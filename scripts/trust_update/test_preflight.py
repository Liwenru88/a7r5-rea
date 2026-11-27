"""使用合成 USB 快照验证一键入口的只读兼容预检。"""

import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LAUNCHER = '一键更新信任环境.command'
MSC_LAUNCHERS = (
    HERE / LAUNCHER,
    ROOT / 'scripts/ssh_start/一键启动SSH.command',
    ROOT / 'scripts/clean_jiritsu/一键清理Jiritsu.command',
)
RECOVERY_LAUNCHER = ROOT / 'scripts/restore-usb.command'
FASTBOOT_LAUNCHERS = tuple(ROOT / 'a7r5-fastboot' / name for name in (
    '1_enter_fastboot.sh', '2_activate_usb.sh', '3_trigger_sd_update.sh',
))


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
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='a7r5-preflight-')))
        # 此目录只保留只读入口需要的源码，不包含任何设备操作后端。
        sources = (*MSC_LAUNCHERS, RECOVERY_LAUNCHER, *FASTBOOT_LAUNCHERS,
                   ROOT / 'scripts/usb_preflight.sh', HERE / 'preflight.py', HERE / 'host_usb.py')
        for source in sources:
            path = self.root / source.relative_to(ROOT)
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, path)
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'python3').symlink_to(Path(sys.executable).absolute())
        self.env = {'PATH': f'{bin_dir}:/usr/bin:/bin'}

    def invoke(self, devices, version=None, *, launcher=HERE / LAUNCHER):
        snapshot = self.root / 'usb snapshot.plist'
        snapshot.write_bytes(plistlib.dumps(devices))
        args = ['--check-only', '--usb-snapshot', str(snapshot)]
        if version is not None:
            args += ['--firmware-version', version]
        return self.launch(launcher, *args)

    def launch(self, launcher, *args, env=None):
        return subprocess.run(
            [str(self.root / launcher.relative_to(ROOT)), *args],
            cwd=self.root,
            env=self.env if env is None else env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_supported_baseline_across_bodies_and_ports(self):
        cases = [(camera(), [1, 4]), (camera(0x03210000, 'test-b'), [2, 1])]
        for launcher in MSC_LAUNCHERS:
            for device, ports in cases:
                with self.subTest(launcher=launcher.name, ports=ports):
                    result = self.invoke([device], '4.00', launcher=launcher)
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

    def test_rejects_check_flag_after_device_engine(self):
        for launcher in MSC_LAUNCHERS[:2]:
            with self.subTest(launcher=launcher.name):
                result = self.launch(launcher, 'kit', '--check-only',
                                     env={'A7R5_PYTHON': '/usr/bin/false'})
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('--check-only', result.stderr)

    def test_trust_launcher_forwards_auto_flow_options(self):
        # 用只回显参数的解释器替身确认：默认 libjit 全自动，引擎与转存参数原样下发。
        fake_python = self.root / 'bin' / 'fake-python'
        fake_python.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@"\n')
        fake_python.chmod(0o755)
        env = {'A7R5_PYTHON': str(fake_python), 'PATH': '/usr/bin:/bin'}
        cases = (
            ([], ['--engine', 'libjit']),
            (['kit'], ['--engine', 'kit']),
            (['--capture-only'], ['--engine', 'libjit', '--capture-only']),
            (['kit', '--capture-timeout', '420'], ['--engine', 'kit', '--capture-timeout', '420']),
            (['--preimage', '/tmp/cnflasha1.img'], ['--engine', 'libjit', '--preimage', '/tmp/cnflasha1.img']),
        )
        for args, expected in cases:
            with self.subTest(args=args):
                result = self.launch(HERE / LAUNCHER, *args, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                argv = result.stdout.split()
                self.assertEqual(argv[0], '-B')
                self.assertEqual(argv[2:], expected)

    def test_usb_observation_matches_each_shortcut_target(self):
        rp2040 = dict(camera(), idVendor=0x2e8a, idProduct=0x000a)
        fastboot = dict(camera(0x03210000), idVendor=0x18d1, idProduct=0x4ee0)
        cases = (
            (RECOVERY_LAUNCHER, camera(pid=0x0336), 'service'),
            (FASTBOOT_LAUNCHERS[0], rp2040, 'rp2040'),
            (FASTBOOT_LAUNCHERS[1], fastboot, 'fastboot'),
            (FASTBOOT_LAUNCHERS[2], fastboot, 'fastboot'),
        )
        for launcher, device, kind in cases:
            with self.subTest(launcher=launcher.name):
                result = self.invoke([device], launcher=launcher)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report['status'], 'usb_observed')
                self.assertEqual(report['usb']['kind'], kind)
                self.assertNotIn('firmware', report)

    def test_fastboot_rejects_absent_or_ambiguous_targets(self):
        launcher = FASTBOOT_LAUNCHERS[1]
        fastboot = dict(camera(), idVendor=0x18d1, idProduct=0x4ee0)
        for devices in ([camera()], [fastboot, dict(fastboot, locationID=0x03210000)]):
            with self.subTest(devices=devices):
                result = self.invoke(devices, launcher=launcher)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'usb_unavailable')

    def test_fastboot_help_and_mixed_check_flag_skip_usb_configuration(self):
        launcher = FASTBOOT_LAUNCHERS[1]
        for args, code in ((['--help'], 0), (['--quick', '--check-only'], 2)):
            with self.subTest(args=args):
                result = self.launch(launcher, *args)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn(launcher.name, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
