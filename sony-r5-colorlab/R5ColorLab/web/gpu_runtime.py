"""Explicit per-process Metal policy; existing CPU jobs keep their environment."""
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

_CPU_REFERENCE = ContextVar('r5_cpu_reference', default=False)

@lru_cache(maxsize=1)
def _mps_available():
    try:
        import torch
        return torch.backends.mps.is_available()
    except ImportError:
        return False


def available():
    return (not _CPU_REFERENCE.get() and
        os.environ.get('R5_GPU_TRAINING', '0').lower() not in ('0', 'false', 'cpu', 'off') and
        _mps_available())


# 保留现有诊断和测试清除硬件缓存的入口。
available.cache_clear = _mps_available.cache_clear


@contextmanager
def cpu_reference():
    """只在当前调用上下文禁用GPU分派，不改变其他并发训练的环境。"""
    token = _CPU_REFERENCE.set(True)
    try:
        yield
    finally:
        _CPU_REFERENCE.reset(token)


def policy():
    from gpu_native import kernel_available
    enabled = available()
    return dict(requested=os.environ.get('R5_GPU_TRAINING', '0'),
        available=enabled, backend='Apple Metal/MPS' if enabled else 'CPU 8 threads',
        native_integer_backend='Metal' if enabled and kernel_available() else 'CPU reference')
