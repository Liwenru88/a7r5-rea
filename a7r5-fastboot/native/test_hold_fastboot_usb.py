import json
import os
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def hold_helper(tmp_path_factory):
    source = Path(__file__).with_name("hold_usb_test_harness.c")
    binary = tmp_path_factory.mktemp("hold-usb") / "read_fastboot_usb"
    subprocess.run(
        ["clang", "-Wall", "-Wextra", "-Werror", "-framework", "IOKit",
         "-framework", "CoreFoundation", str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    return binary


@pytest.mark.parametrize("scenario", ["healthy", "read_error", "protocol", "busy", "absent"])
def test_hold_survives_closed_stdin_without_device_mutation(hold_helper, tmp_path, scenario):
    status = tmp_path / "status.json"
    log = tmp_path / "session.log"
    with log.open("w") as output:
        process = subprocess.Popen(
            [str(hold_helper), "--hold", str(status)], stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT,
            env={**os.environ, "USB_TEST_SCENARIO": scenario},
        )
        try:
            deadline = time.monotonic() + 2
            observed = None
            while time.monotonic() < deadline and process.poll() is None:
                if status.exists():
                    observed = json.loads(status.read_text())
                    if ((scenario == "healthy" and observed["heartbeats"] >= 2)
                            or (scenario == "absent" and observed["state"] == "waiting_for_usb")
                            or (scenario not in {"healthy", "absent"} and observed["state"] == "blocked")):
                        break
                time.sleep(0.01)
            assert observed is not None, log.read_text()
            assert process.poll() is None
            if scenario == "healthy":
                assert observed["state"] == "connected"
                assert observed["heartbeats"] >= 2
            elif scenario == "absent":
                assert observed["state"] == "waiting_for_usb"
                assert observed["heartbeats"] == 0
                assert "FAKE_OPEN" not in log.read_text()
            else:
                assert observed["state"] == "blocked"
                assert observed["error_code"] != 0
                assert log.read_text().count("FAKE_OPEN") == 1
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=3)
    commands = [line for line in log.read_text().splitlines() if line.startswith("FAKE_WRITE")]
    assert all(line == "FAKE_WRITE getvar:version" for line in commands)
    assert json.loads(status.read_text())["state"] == "stopped"
