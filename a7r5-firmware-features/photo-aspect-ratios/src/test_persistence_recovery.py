"""画幅后台恢复与保存反馈；实际 AP 代码，文件和线程调度为显式夹具。"""
import struct

from unicorn import arm64_const as R
import pytest

from test_ap_state import ap_image, menu, disk  # noqa: F401
from test_ap import SELECTION
from test_geometry import DATA, STACK, STOP


def tick(disk, elapsed=1000):
    fixture, _, fault, _ = disk
    fault['now_ms'] = fault.get('now_ms', 0) + elapsed
    call, get = fixture[2:4]
    # 老组件仍按相同可观察契约执行，使修复前失败来自业务结果。
    return call(fixture[0].aspect_symbols.get('r5_aspect_persist_service', get))


def record(id):
    return struct.pack('<4I', 0x41533552, 1, id, ~id & 0xffffffff)


def test_target_directory_abi_preserves_config_across_save_and_restart(disk):
    fixture, files, _, restart = disk
    _, _, call, get, _, commit, _, _, _ = fixture
    files['r5_aspect10_v1.dat'] = record(9)
    restart()
    assert call(get) == 9
    call(commit, 0x1604)
    tick(disk)
    restart()
    assert call(get) == 8 and files['r5_aspect10_v1.dat'] == record(8)


def test_transient_read_recovers_and_notifies_original_property_without_overwriting_native(disk):
    fixture, files, fault, restart = disk
    cpu, base, call, get, _, _, callback, word, _ = fixture
    files['r5_aspect10_v1.dat'] = record(9)
    restart()
    fault['open'] = True
    assert call(get) == 0
    fault['open'] = False
    notices = []
    callback(base + 0x252ca34, lambda: notices.append(cpu.reg_read(R.UC_ARM64_REG_X0)) or 0)
    tick(disk)
    assert call(get) == 9, '暂态读取失败后必须可补读已保存的画幅'
    assert 0x52b in notices and files['r5_aspect10_v1.dat'] == record(9)
    assert word(base + SELECTION) & 255 == 9
    # 后台补读后的下一条原生配置必须携带私有 wire，不能只恢复菜单数字。
    source, frame = DATA + 0xa000, STACK + 0x1000
    cpu.mem_write(source, bytes(16))
    cpu.mem_write(frame, bytes(0x400))
    for index, value in ((0, 0), (20, source), (29, frame)):
        cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{index}'), value)
    cpu.reg_write(R.UC_ARM64_REG_SP, frame)
    cpu.reg_write(R.UC_ARM64_REG_LR, STOP)
    cpu.emu_start(base + 0x3565f78, base + 0x3565fac, count=10000)
    assert cpu.reg_read(R.UC_ARM64_REG_PC) == base + 0x3565fac
    assert bytes(cpu.mem_read(frame + 0x77, 1)) == b'\xe5'


def test_explicit_choice_wins_over_a_read_already_in_progress(disk):
    fixture, files, fault, restart = disk
    cpu, _, call, get, set_, _, _, _, _ = fixture
    files['r5_aspect10_v1.dat'] = record(9)
    restart()
    fault['open'] = True
    assert call(get) == 0
    fault['open'] = False
    def choose():
        context = cpu.context_save()
        call(set_, 8, stack=STACK + 0x8000)
        cpu.context_restore(context)
    fault['during_read'] = choose
    tick(disk)
    assert call(get) == 8
    assert files['r5_aspect10_v1.dat'] == record(9)


@pytest.mark.parametrize('content', [None, b'bad', record(9) + b'extra'])
def test_missing_or_invalid_file_is_not_polled_forever(disk, content):
    fixture, files, fault, restart = disk
    call, get = fixture[2:4]
    if content is not None: files['r5_aspect10_v1.dat'] = content
    restart()
    assert call(get) == 0
    count = fault.get('opens', 0)
    for _ in range(8):
        tick(disk)
        assert call(get) == 0
    assert fault.get('opens', 0) == count


def test_repeated_read_errors_are_bounded_and_explicit_choice_still_works(disk):
    fixture, files, fault, restart = disk
    call, get, set_ = fixture[2:5]
    files['r5_aspect10_v1.dat'] = record(9)
    restart()
    fault['open'] = True
    assert call(get) == 0
    for _ in range(10): tick(disk)
    assert fault.get('opens', 0) == 3
    fault['open'] = False
    call(set_, 8)
    assert call(get) == 8


@pytest.mark.parametrize('failure', ['write', 'fsync', 'rename', 'fsync_dir'])
def test_failed_save_is_visible_then_background_retry_clears_it(disk, failure):
    fixture, files, fault, restart = disk
    _, _, call, get, set_, commit, _, _, _ = fixture
    call(commit, 0x1605)
    tick(disk)
    assert files['r5_aspect10_v1.dat'] == record(9)
    fault[failure] = True
    call(set_, 8)
    call(commit, 0x1604)
    tick(disk)
    assert call(get) == 8
    assert call(0x1bd54d8, 33) == 0x0200abdf, '保存失败必须进入原生菜单可见标题'
    assert files['r5_aspect10_v1.dat'] == record(8 if failure == 'fsync_dir' else 9)
    fault[failure] = False
    tick(disk)
    assert files['r5_aspect10_v1.dat'] == record(8)
    assert call(0x1bd54d8, 33) == 0x0200a54c
    restart()
    assert call(get) == 8


def test_confirm_only_queues_and_latest_choice_wins_without_blocking_ui(disk):
    fixture, files, fault, _ = disk
    _, _, call, _, _, commit, _, _, _ = fixture
    call(commit, 0x1605)
    call(commit, 0x1604)
    assert not files and not fault.get('writes', 0)
    assert call(0x1bd54d8, 33) == 0x0200abde
    tick(disk)
    assert files['r5_aspect10_v1.dat'] == record(8)
    assert fault['threads'] == 1


def test_new_confirm_during_failed_old_write_is_not_reported_as_failed(disk):
    fixture, files, fault, _ = disk
    cpu, _, call, _, _, commit, _, _, _ = fixture
    call(commit, 0x1605)
    fault['write'] = True
    def confirm():
        context = cpu.context_save()
        call(commit, 0x1604, stack=STACK + 0x8000)
        cpu.context_restore(context)
    fault['during_write'] = confirm
    tick(disk)
    assert call(0x1bd54d8, 33) == 0x0200abde
    fault['write'] = False
    tick(disk)
    assert files['r5_aspect10_v1.dat'] == record(8)


def test_write_retry_budget_stops_io_until_another_explicit_confirm(disk):
    fixture, files, fault, _ = disk
    _, _, call, _, _, commit, _, _, _ = fixture
    fault['write'] = True
    call(commit, 0x1605)
    for _ in range(8): tick(disk)
    count = fault['writes']
    for _ in range(5): tick(disk)
    assert fault['writes'] == count
    assert call(0x1bd54d8, 33) == 0x0200abdf
    fault['write'] = False
    call(commit, 0x1604)
    tick(disk)
    assert files['r5_aspect10_v1.dat'] == record(8)


def test_worker_launch_failure_is_visible_and_a_later_query_can_retry_launch(disk):
    fixture, files, fault, _ = disk
    _, _, call, get, _, commit, _, _, _ = fixture
    fault['create'] = True
    call(commit, 0x1605)
    assert not files and call(0x1bd54d8, 33) == 0x0200abdf
    fault['create'] = False
    fault['now_ms'] = 1000
    call(get)
    tick(disk)
    assert files['r5_aspect10_v1.dat'] == record(9)
    assert fault['threads'] == 2


def test_actual_worker_drives_service_and_survives_interrupted_sleep(disk):
    fixture, files, fault, _ = disk
    cpu, base, call, _, _, commit, callback, _, put = fixture
    call(commit, 0x1605)
    sleeps = []
    def sleep():
        sleeps.append(1)
        put(DATA + 0x7f00, 4 if len(sleeps) == 1 else 22)
        return -1
    callback(DATA + 0x8028, sleep)
    call(fault['worker_entry'] - base, 0)
    assert len(sleeps) == 2 and files['r5_aspect10_v1.dat'] == record(9)
    call(commit, 0x1604)
    tick(disk)
    assert fault['threads'] == 2 and files['r5_aspect10_v1.dat'] == record(8)


def test_worker_exiting_before_create_returns_is_not_marked_alive_again(disk):
    fixture, files, _, _ = disk
    cpu, base, call, _, _, commit, callback, _, put = fixture
    def sleep():
        put(DATA + 0x7f00, 22)
        return -1
    callback(DATA + 0x8028, sleep)
    starts = []
    def create():
        entry = cpu.reg_read(R.UC_ARM64_REG_X2)
        starts.append(entry)
        context = cpu.context_save()
        call(entry - base, 0, stack=STACK + 0x8000)
        cpu.context_restore(context)
        return 0
    callback(DATA + 0x8038, create)
    call(commit, 0x1605)
    assert files['r5_aspect10_v1.dat'] == record(9)
    call(commit, 0x1604)
    assert len(starts) == 2 and files['r5_aspect10_v1.dat'] == record(8)
