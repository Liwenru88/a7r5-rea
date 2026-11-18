"""Gamma同源原指令适配的执行前边界；实际CP链由同包集成回执验证。"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from a7filters.cp_gamma_source406 import execute_from_context


def test_wrong_cp_rejected_before_context_read():
    class UntrustedMachine:
        raw = b'not-the-locked-cp'

        def word(self, address):
            raise AssertionError('来源拒绝前不能读取上下文')

    with pytest.raises(ValueError):
        execute_from_context(UntrustedMachine(), 0x1214e98)
