import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def reader(tmp_path_factory):
    source = Path(__file__).with_name("hold_usb_test_harness.c")
    binary = tmp_path_factory.mktemp("boot-reader") / "read_fastboot_usb"
    subprocess.run(
        ["clang", "-Wall", "-Wextra", "-Werror", "-framework", "IOKit",
         "-framework", "CoreFoundation", str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    return binary


@pytest.mark.parametrize("partition", ["nflasha3", "nflasha8", "nflasha15"])
def test_boot_partition_read_command_is_accepted(reader, partition):
    command = "oem partition dump " + partition
    result = subprocess.run([str(reader), command], capture_output=True, text=True, timeout=3)
    assert result.returncode == 0
    assert "FAKE_WRITE " + command in result.stdout


@pytest.mark.parametrize("scenario,created", [("large_upload", True), ("oversize_upload", False)])
def test_upload_is_bounded_by_largest_boot_partition(reader, tmp_path, scenario, created):
    destination = tmp_path / "readback.img"
    result = subprocess.run(
        [str(reader), "upload:" + str(destination)],
        env={**os.environ, "USB_TEST_SCENARIO": scenario},
        capture_output=True, text=True, timeout=3,
    )
    # 允许 715 MiB 的传输进入读取，但模拟断连；不实际生成大文件。
    assert result.returncode == 8
    assert destination.exists() is created
    if created:
        assert destination.stat().st_size == 0
    assert "SAVED" not in result.stdout


@pytest.mark.parametrize("command", ["flash:nflasha3", "flash:nflasha8", "erase:nflasha15"])
def test_boot_partition_writes_still_rejected_before_usb_open(reader, command):
    result = subprocess.run([str(reader), command], capture_output=True, text=True, timeout=3)
    assert result.returncode == 2
    assert "FAKE_OPEN" not in result.stdout


@pytest.mark.parametrize("command", ["oem cetus", "oem cetus norcmd:9f:3", "oem cetus dumpnor:0:1000"])
def test_fixed_nor_read_queries_are_accepted(reader, command):
    result = subprocess.run([str(reader), command], capture_output=True, text=True, timeout=3)
    assert result.returncode == 0
    assert "FAKE_WRITE " + command in result.stdout


@pytest.mark.parametrize("command", [
    "oem cetus reset", "oem cetus exec:108000", "oem cetus norcmd:06",
    "oem cetus norcmd:02:1:0:200000", "oem cetus dumpnor:0:4000000",
])
def test_nor_write_and_unbounded_commands_are_rejected(reader, command):
    result = subprocess.run([str(reader), command], capture_output=True, text=True, timeout=3)
    assert result.returncode == 2
    assert "FAKE_OPEN" not in result.stdout
