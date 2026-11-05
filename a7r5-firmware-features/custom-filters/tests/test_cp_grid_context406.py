"""新增原线程表入口仍须在映射/执行之前拒绝错误CP来源。"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a7filters import cp_grid_context406


def test_changed_source_rejected_before_any_thread_memory(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('来源不符时访问了原线程内存或构造了上下文')

    class UntrustedMachine:
        raw = b'not-the-locked-cp'
        map_ram = forbidden

    monkeypatch.setattr(cp_grid_context406, '_prepare', forbidden)
    for operation in (
        lambda: cp_grid_context406.execute(UntrustedMachine.raw),
        lambda: cp_grid_context406.collect(UntrustedMachine.raw),
        lambda: cp_grid_context406._initialize_thread_tables(UntrustedMachine(), 0x9010d000),
    ):
        with pytest.raises(ValueError, match='CP不是已锁定4.06'):
            operation()
