import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'passive_fastboot_monitor.py'


def test_monitor_parses_target_without_usb_opening(tmp_path):
    sample = tmp_path / 'ioreg.txt'
    sample.write_text('''+-o ILCE-7M4\n    "idVendor" = 6353\n    "idProduct" = 20192\n    "USB Product Name" = "ILCE-7M4"\n''')
    output = tmp_path / 'report.jsonl'
    result = subprocess.run([sys.executable, str(SCRIPT), '--once', '--input', str(sample), '--output', str(output)], capture_output=True, text=True)
    assert result.returncode == 0
    report = json.loads(output.read_text().splitlines()[0])
    assert report['fastboot_present'] is True
    assert report['vid'] == '18d1'
    assert report['pid'] == '4ee0'
    assert report['usb_operations'] == []


def test_monitor_reports_absence(tmp_path):
    sample = tmp_path / 'ioreg.txt'
    sample.write_text('+-o RP2040 Zero\n    "idVendor" = 11914\n    "idProduct" = 3\n')
    output = tmp_path / 'report.jsonl'
    result = subprocess.run([sys.executable, str(SCRIPT), '--once', '--input', str(sample), '--output', str(output)], capture_output=True, text=True)
    assert result.returncode == 1
    report = json.loads(output.read_text().splitlines()[0])
    assert report['fastboot_present'] is False
    assert report['usb_operations'] == []
