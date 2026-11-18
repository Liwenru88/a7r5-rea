import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def configure_helper(tmp_path_factory):
    source = Path(__file__).with_name("configure_usb_test_harness.c")
    binary = tmp_path_factory.mktemp("mock-usb") / "configure_fastboot_usb"
    subprocess.run(
        ["clang", "-Wall", "-Wextra", "-Werror", "-framework", "IOKit",
         "-framework", "CoreFoundation", str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    return binary


def invoke(binary, scenario, *args):
    return subprocess.run(
        [str(binary), *args], env={**os.environ, "USB_TEST_SCENARIO": scenario},
        capture_output=True, text=True, timeout=3,
    )


def test_failed_configuration_read_is_unknown(configure_helper):
    result = invoke(configure_helper, "read_error")
    assert result.returncode != 0
    assert "GetConfiguration=0xe00002ed" in result.stdout
    assert "configuration=unknown" in result.stdout
    assert "configuration=0" not in result.stdout
    assert "FAKE_OPEN" not in result.stdout
    assert "FAKE_SET_CONFIGURATION" not in result.stdout


@pytest.mark.parametrize("scenario,code", [("unconfigured", 0), ("absent", 2), ("multiple", 4)])
def test_presence_check_does_not_open_usb(configure_helper, scenario, code):
    result = invoke(configure_helper, scenario, "--check")
    assert result.returncode == code
    assert "FAKE_PLUGIN" not in result.stdout
    assert "FAKE_OPEN" not in result.stdout


def test_configured_device_is_not_reconfigured(configure_helper):
    result = invoke(configure_helper, "configured")
    assert result.returncode == 0
    assert "FAKE_SET_CONFIGURATION" not in result.stdout


@pytest.mark.parametrize("scenario,error", [
    ("descriptor_error", "GetConfigurationDescriptorPtr=0xe00002ed"),
    ("open_error", "USBDeviceOpen=0xe00002d8"),
    ("set_error", "SetConfiguration(1)=0xe00002ed"),
])
def test_configuration_failure_stops_at_failed_step(configure_helper, scenario, error):
    result = invoke(configure_helper, scenario)
    assert result.returncode != 0
    assert error in result.stdout
    assert ("FAKE_SET_CONFIGURATION" in result.stdout) == (scenario == "set_error")
    assert ("FAKE_CLOSE" in result.stdout) == (scenario == "set_error")


def test_unconfigured_device_is_configured_once(configure_helper):
    result = invoke(configure_helper, "unconfigured")
    assert result.returncode == 0
    assert result.stdout.count("FAKE_SET_CONFIGURATION 1") == 1
    assert result.stdout.count("FAKE_CLOSE") == 1
