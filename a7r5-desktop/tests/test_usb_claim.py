"""在内存设备上复现macOS接管失败，禁止真实USB和主机命令。"""
from types import SimpleNamespace

import pytest
from system_dump import usb_adapter


class ClaimError(Exception):
    backend_error_code = -99


class MemoryDevice:
    bus = 2
    port_numbers = [1]

    def __init__(self, cleanup_error=None):
        self.calls = []
        self.cleanup_error = cleanup_error

    def is_kernel_driver_active(self, interface):
        return True

    def detach_kernel_driver(self, interface):
        self.calls.append('detach')

    def attach_kernel_driver(self, interface):
        self.calls.append('attach')
        if self.cleanup_error:
            raise self.cleanup_error


def test_transient_claim_waits_then_succeeds_before_service(monkeypatch):
    camera = MemoryDevice()
    attempts = []
    sleeps = []
    def claim(device, interface):
        attempts.append(interface)
        if len(attempts) == 1:
            raise ClaimError('插件尚未就绪')
    monkeypatch.setattr(usb_adapter.sys, 'platform', 'darwin')
    monkeypatch.setattr(usb_adapter.time, 'sleep', sleeps.append)
    assert usb_adapter.claim_interface(camera, SimpleNamespace(claim_interface=claim), allow_settle=True)
    assert attempts == [0, 0] and sleeps == [0.25]
    assert camera.calls == ['detach']


def test_original_claim_error_survives_cleanup_failure(monkeypatch):
    camera = MemoryDevice(RuntimeError('驱动回收失败'))
    original = ClaimError('原始接管错误')
    events = []
    def claim(*args):
        raise original
    monkeypatch.setattr(usb_adapter.sys, 'platform', 'linux')
    with pytest.raises(ClaimError) as raised:
        usb_adapter.claim_interface(camera, SimpleNamespace(claim_interface=claim),
                                    lambda event, **fields: events.append((event, fields)))
    assert raised.value is original
    assert any(name == 'kernel_driver_reattach_failed' for name, _ in events)


@pytest.mark.parametrize('platform,allow_settle,code,active,move,expected_attempts', [
    ('darwin', True, -99, True, False, 3),
    ('darwin', False, -99, True, False, 1),
    ('linux', True, -99, True, False, 1),
    ('darwin', True, -6, True, False, 1),
    ('darwin', True, -99, False, False, 1),
    ('darwin', True, -99, True, True, 1),
])
def test_claim_wait_is_bounded_and_restricted(monkeypatch, platform, allow_settle, code, active, move, expected_attempts):
    camera = MemoryDevice()
    camera.is_kernel_driver_active = lambda interface: active
    attempts = []
    sleeps = []
    error = ClaimError('持续接管失败')
    error.backend_error_code = code
    def claim(*args):
        attempts.append(0)
        if move:
            camera.port_numbers = [2]
        raise error
    monkeypatch.setattr(usb_adapter.sys, 'platform', platform)
    monkeypatch.setattr(usb_adapter.time, 'sleep', sleeps.append)
    with pytest.raises((ClaimError, ValueError)):
        usb_adapter.claim_interface(camera, SimpleNamespace(claim_interface=claim), allow_settle=allow_settle)
    assert len(attempts) == expected_attempts
    assert len(sleeps) <= 2 and all(delay == 0.25 for delay in sleeps)
    assert camera.calls == (['detach'] if move else ['detach', 'attach']) if active else camera.calls == []
