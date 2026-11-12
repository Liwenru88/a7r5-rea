import io
import os
import pty
import select
import shutil
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path

import pytest

import r5_fastboot as r5


@pytest.fixture(scope="module")
def inputs():
    return r5.preflight(r5.ROOT)


def event(code, data=b""):
    return struct.pack("<BH", code, len(data)) + data


class FakeSerial:
    def __init__(self, banner=b"uart_boot 1", failure=None):
        self.banner = banner
        self.failure = failure
        self.output = bytearray()
        self.commands = []

    def write(self, packet):
        code, size = struct.unpack_from("<BH", packet)
        assert len(packet) == size + 3
        self.commands.append((code, packet[3:]))
        if code == self.failure:
            self.output += event(0x82, b"injected failure")
        else:
            self.output += event(0x81, self.banner if code == 1 else b"")
        return len(packet)

    def read(self, size):
        if self.timeout != 0:
            size = min(size, 2)
        data = bytes(self.output[:size])
        del self.output[:size]
        return data


class UsbFixture:
    def __init__(self, table, failure=None):
        self.table = table
        self.failure = failure
        self.calls = []

    def __call__(self, executable, args, log, timeout):
        assert 0 < timeout <= 8
        self.calls.append(args)
        if executable.name == "configure_fastboot_usb":
            return 4 if self.failure == "multiple" else (2 if len(self.calls) == 1 else 0)
        if args == ["getvar:version", "oem partition"]:
            rows = r5.expected_layout(self.table)
            if self.failure == "layout":
                rows[5] = (1, 1, "wbi2")
            proto = "0.50" if self.failure == "protocol" else "0.5"
            lines = [f"COMMAND getvar:version\nREPLY OKAY{proto}", "COMMAND oem partition"]
            lines.extend(f"REPLY INFOnflasha{i:<4} {a:08x} {n:08x} {kind}"
                         for i, (a, n, kind) in rows.items())
            log.write_text("\n".join([*lines, "REPLY OKAY", ""]))
            return 0
        if args[0] == "oem partition dump nflasha 0 0x80":
            data = self.table if self.failure != "sdm2" else self.table[:-1] + bytes([self.table[-1] ^ 1])
        elif args[0] == "oem dumpbrom":
            data = bytes(49151 if self.failure == "rom" else 49152)
        else:
            pytest.fail(f"Unexpected USB command {args!r}")
        Path(args[1].removeprefix("upload:")).write_bytes(data)
        return 0


def run(tmp_path, inputs, serial=None, usb_failure=None):
    table, records = inputs
    serial = serial or FakeSerial()
    usb = UsbFixture(table, usb_failure)
    report = r5.run_probe("fake", tmp_path / "run", table, records,
                          opener=lambda *_: nullcontext(serial), launch=usb, sleep=lambda _: None)
    return report, serial.commands, usb.calls


def test_manual_trigger_waits_before_reset(tmp_path, inputs):
    table, records = inputs
    serial = FakeSerial()
    usb = UsbFixture(table)
    observed = []

    def trigger():
        observed.append([code for code, _ in serial.commands])
        assert not usb.calls

    report = r5.run_probe("fake", tmp_path / "manual", table, records,
                          opener=lambda *_: nullcontext(serial), launch=usb,
                          sleep=lambda _: None, before_reset=trigger)
    assert observed == [[1]]
    assert report["usb_transport_verified"]
    assert [code for code, _ in serial.commands].count(2) == 1


def test_manual_trigger_cancel_does_not_reset(tmp_path, inputs):
    table, records = inputs
    serial = FakeSerial()
    usb = UsbFixture(table)

    def cancel():
        raise KeyboardInterrupt

    report = r5.run_probe("fake", tmp_path / "cancel", table, records,
                          opener=lambda *_: nullcontext(serial), launch=usb,
                          sleep=lambda _: None, before_reset=cancel)
    assert report["stage"] == "cancelled"
    assert report["reset_attempted"] is False
    assert serial.commands == [(1, b"")]
    assert not usb.calls
    assert (tmp_path / "cancel" / "report.json").is_file()


def test_manual_trigger_eof_does_not_reset(tmp_path, inputs):
    table, records = inputs
    serial = FakeSerial()

    def closed_input():
        raise EOFError("stdin closed")

    report = r5.run_probe("fake", tmp_path / "eof", table, records,
                          opener=lambda *_: nullcontext(serial),
                          before_reset=closed_input)
    assert report["stage"] == "cancelled"
    assert report["reset_attempted"] is False
    assert serial.commands == [(1, b"")]


def test_full_flow_without_uart_ready_message(tmp_path, inputs):
    report, commands, usb = run(tmp_path, inputs)
    assert report["stage"] == "complete"
    assert report["usb_transport_verified"] and report["sdm2_matches_reference"]
    assert report["uart_ready_observed"] is False
    assert report["same_physical_body_verified"] is False
    assert report["persistent_write_commands_sent"] is False
    assert [c for c, _ in commands] == [1, 2, 3, *([4] * 64), 3, 5]
    assert r5.digest(b"".join(data for c, data in commands if c == 4)) == (
        "3604be189345d85deb701d22f145b8b7a28d606186ec287751a677ccbb9c2ebb")
    assert [args[0] for args in usb if args] == [
        "getvar:version", "oem partition dump nflasha 0 0x80", "oem dumpbrom"]


def run_usb_with_uart(tmp_path, inputs, chunks, usb_failure=None):
    table, records = inputs
    serial = FakeSerial()
    usb = UsbFixture(table, usb_failure)
    incoming = iter(chunks)

    def launch(executable, args, log, timeout):
        if executable.name == "configure_fastboot_usb":
            serial.output += next(incoming, b"")
        return usb(executable, args, log, timeout)

    report = r5.run_probe("fake", tmp_path, table, records,
                          opener=lambda *_: nullcontext(serial), launch=launch, sleep=lambda _: None)
    assert sum(code == 2 for code, _ in serial.commands) == 1
    return report


def test_late_ready_survives_split_frames_and_successful_usb_poll(tmp_path, inputs):
    first = event(0x83, b"[mira] fast")
    report = run_usb_with_uart(tmp_path / "run", inputs, [first[:2], first[2:] + event(0x83, b"boot ready\r\n")])
    assert report["uart_ready_observed"] is True
    assert report["usb_transport_verified"] is True
    assert (tmp_path / "run" / "uart.bin").read_bytes() == b"[mira] fastboot ready\r\n"


def test_uart_ready_is_preserved_on_usb_configuration_failure(tmp_path, inputs):
    report = run_usb_with_uart(tmp_path / "run", inputs, [event(0x83, b"[mira] fastboot ready\n")], "multiple")
    assert report["uart_ready_observed"] is True
    assert report["usb_transport_verified"] is False
    assert report["stage"] == "usb_enumeration"


def test_malformed_uart_frame_does_not_block_usb_probe(tmp_path, inputs):
    report = run_usb_with_uart(tmp_path / "run", inputs, [struct.pack("<BH", 0x83, 65535)])
    assert report["uart_capture_error"]
    assert report["usb_transport_verified"] is True


@pytest.mark.parametrize("banner,failure,expected_codes,reset", [
    (b"uart_boot 2", None, [1], False),
    (b"uart_boot 1", 2, [1, 2], True),
    (b"uart_boot 1", 4, [1, 2, 3, 4], True),
])
def test_bridge_failures_stop_before_usb(tmp_path, inputs, banner, failure, expected_codes, reset):
    report, commands, usb = run(tmp_path, inputs, FakeSerial(banner, failure))
    assert [c for c, _ in commands] == expected_codes
    assert report["reset_attempted"] is reset
    assert report["usb_transport_verified"] is False
    assert not usb and "error" in report


@pytest.mark.parametrize("failure,expected_stage,reads", [
    ("multiple", "usb_enumeration", 0),
    ("protocol", "partition_listing", 1),
    ("layout", "partition_listing", 1),
    ("sdm2", "sdm2_readback", 2),
    ("rom", "ap_bootrom_readback", 3),
])
def test_usb_failure_preserves_evidence_without_retrying_reset(tmp_path, inputs, failure, expected_stage, reads):
    report, commands, usb = run(tmp_path, inputs, usb_failure=failure)
    assert report["stage"] == expected_stage
    assert report["usb_transport_verified"] is False
    assert sum(code == 2 for code, _ in commands) == 1
    assert sum(bool(args) for args in usb) == reads
    assert "error" in report
    assert (tmp_path / "run" / "report.json").is_file()


def test_pinned_payload_rejects_changed_input(tmp_path):
    for name in (*r5.ASSET_PINS, r5.CONFIGURE, r5.READER, "host-sha256.json"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(r5.ROOT / name, path)
    p = tmp_path / r5.PAYLOAD
    old = p.read_bytes()
    p.write_bytes(bytes([old[0] ^ 1]) + old[1:])
    with pytest.raises(r5.ProbeError, match="fastboot.bin"):
        r5.preflight(tmp_path)


def test_real_pyserial_uses_pty_only_and_does_not_send_after_partial_ack():
    sys.path.insert(0, str(r5.ROOT / r5.WHEEL))
    import serial

    master, slave = pty.openpty()

    def emulator():
        ready, _, _ = select.select([master], [], [], 2)
        assert ready
        assert os.read(master, 3) == b"\x01\x00\x00"
        os.write(master, event(0x83, b"bridge output") + b"\x81\x0b")
        ready, _, _ = select.select([master], [], [], 1.2)
        assert not ready

    try:
        with serial.Serial(os.ttyname(slave), 115200, timeout=1, write_timeout=1, exclusive=True) as port:
            with ThreadPoolExecutor() as pool:
                result = pool.submit(emulator)
                uart = io.BytesIO()
                with pytest.raises(r5.ProbeError, match="超时或不完整"):
                    r5.start_ram(r5.SerialBridge(port, uart), (), {}, sleep=lambda _: None)
                assert uart.getvalue() == b"bridge output"
                result.result(timeout=3)
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize("command", ["flash:nflasha5", "erase:nflasha5", "download:00000010",
                                      "reboot", "oem poke:0x1000:0x0", "oem partition dump nflasha5"])
def test_native_helper_rejects_commands_before_usb_enumeration(command):
    result = subprocess.run([str(r5.ROOT / r5.READER), command], capture_output=True, text=True)
    assert result.returncode == 2
    assert "Rejected command" in result.stderr
