"""冷启动/恢复真实工作线程，内存存储与显式故障服务。"""
import ctypes as C
from pathlib import Path
import pytest
from runtime_support import HERE, SOURCE, library


@pytest.fixture
def worker(tmp_path):
    lib = library(tmp_path, 'worker', [Path(__file__).with_name('runtime_worker.c'), *[
        SOURCE/'import'/s for s in ('r5_runtime_session.c', 'r5_scan_gate.c',
        'r5_fsys_adapter.c', 'r5_stage410_codec.c', 'sd_native_store.c', 'sd_native_persist.c')]])
    lib.test_input.argtypes = [C.c_uint, C.c_void_p, C.c_size_t, C.c_int]
    return lib


def binfile():
    return (HERE/'upstream/filters/FUJ_12_v45/R5NATIVE.BIN').read_bytes()


def put(lib, which, raw, present=True):
    lib.test_input(which, raw, len(raw), present)


def values(lib):
    return [lib.test_value(i) for i in range(14)]


@pytest.mark.parametrize('scenario', ['valid', 'missing', 'corrupt', 'empty', 'fallback', 'late_second'])
def test_cold_worker_durable_choice_before_only_cp_activation(worker, scenario):
    raw = binfile()
    put(worker, 2, raw)
    if scenario == 'valid': put(worker, 0, raw)
    if scenario == 'corrupt': put(worker, 0, raw[:-1])
    if scenario == 'empty': put(worker, 0, b'')
    if scenario in ('fallback', 'late_second'): put(worker, 1, raw)
    worker.test_scan(1, 1 if scenario in ('fallback', 'late_second') else 0,
                     1 if scenario == 'late_second' else 3, 500 if scenario == 'late_second' else 0)
    assert worker.test_run(0) == 0
    v = values(worker)
    assert v[3] == 0 and v[6] == 1 and v[7] == 1 and v[13] == 1
    assert v[1] == v[2] == (0 if scenario == 'empty' else 0xfff)
    assert v[5] == (1 if scenario in ('missing', 'corrupt') else 0)
    assert v[0] == (3 if scenario == 'missing' else 2 if scenario == 'corrupt' else 0)
    if scenario == 'empty': assert v[12] == 128
    if scenario in ('fallback', 'late_second'): assert v[8] == 1
    opens, logs = v[4], v[10]
    assert worker.test_run(1) == 0
    v = values(worker)
    assert v[3] == 0 and v[4] == opens and v[10] == logs
    assert v[6] == 2 and v[1] == v[2] == (0 if scenario == 'empty' else 0xfff)


@pytest.mark.parametrize('fault', [1, 2, 4, 8, 16, 32, 64, 128, 256, 512])
def test_worker_failures_close_handles_keep_explicit_status_and_reload_active(worker, fault):
    raw = binfile()
    put(worker, 0, raw)
    # 原内部配置为空；失败时不能把SD候选误作已经持久化的数据。
    worker.test_scan(1, 0, 1, 0)
    worker.test_faults(fault)
    assert worker.test_run(0) == 0
    v = values(worker)
    assert v[3] == 0 and v[13] == 1
    assert v[0] != 0
    if fault in (1, 2, 4, 8, 16, 32): assert v[1] == v[2] == 0
    if fault in (64, 128, 256): assert v[1] == v[2] == 0xfff
    if fault == 512: assert v[6] == 0
    if fault == 64: assert v[9] == 4
    if fault == 128: assert v[9] == 5
