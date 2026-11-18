"""执行菜单私有状态、原生取消入口和文件服务边界，不连接设备。"""

import io
import struct

import pytest
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_HOOK_CODE, UC_MODE_ARM
from unicorn import arm64_const as R

from build_ap import DESCRIPTOR
from test_ap import SELECTION, ap_image  # noqa: F401
from test_geometry import DATA, STACK, STOP


@pytest.fixture
def menu(ap_image):
    base = 0x10000000
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.aspect_symbols = ap_image.symbols
    cpu.mem_map(base, 0x9000000)
    cpu.mem_map(DATA, 0x30000)
    for segment in ELFFile(io.BytesIO(ap_image)).iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_filesz']:
            cpu.mem_write(base + segment['p_vaddr'], segment.data())

    def word(at):
        return struct.unpack('<I', cpu.mem_read(at, 4))[0]

    def put(at, value):
        cpu.mem_write(at, struct.pack('<I', value))

    handles = {}
    def callback(at, function):
        if at in handles:
            cpu.hook_del(handles[at])
        def service(core, *_):
            result = function()
            if result is not None:
                core.reg_write(R.UC_ARM64_REG_X0, result)
            core.reg_write(R.UC_ARM64_REG_PC, core.reg_read(R.UC_ARM64_REG_LR))
        handles[at] = cpu.hook_add(UC_HOOK_CODE, service, begin=at, end=at)

    def set_native():
        value = cpu.reg_read(R.UC_ARM64_REG_X0)
        assert value < 4
        put(DATA, value)
        put(DATA + 4, value)

    callback(base + 0x1c448dc, lambda: word(DATA))
    callback(base + 0x1c61d14, set_native)
    callback(base + 0x28aacfc, lambda: DATA)
    callback(base + 0x28aace8, lambda: DATA + 4)
    callback(base + 0x16dac90, lambda: 0)
    callback(base + 0x1c93d88, lambda: None)
    callback(base + 0x1bd9410, lambda: None)

    def call(address, *args, stack=STACK):
        for index, value in enumerate(args):
            cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{index}'), value)
        cpu.reg_write(R.UC_ARM64_REG_SP, stack)
        cpu.reg_write(R.UC_ARM64_REG_LR, STOP)
        cpu.emu_start(base + address, STOP, count=100000)
        assert cpu.reg_read(R.UC_ARM64_REG_PC) == STOP
        assert cpu.reg_read(R.UC_ARM64_REG_SP) == stack
        return cpu.reg_read(R.UC_ARM64_REG_X0)

    get, set_, commit = [struct.unpack('<Q', cpu.mem_read(base + DESCRIPTOR + off, 8))[0]
                         for off in (0x78, 0x80, 0x88)]
    return cpu, base, call, get, set_, commit, callback, word, put


@pytest.mark.parametrize('before,browsed', [(9, 8), (8, 9), (0, 9), (9, 0), (1, 9), (2, 4), (9, 1)])
def test_native_fn_cancel_restores_private_choice_without_old_epoch(menu, before, browsed):
    cpu, base, call, get, set_, _, _, word, _ = menu
    call(set_, before)
    call(0x2adfd3c)
    call(set_, browsed)
    token = word(base + SELECTION)
    call(0x2adfd5c)
    assert call(get) == before
    assert word(base + SELECTION) != token
    assert word(DATA) == (0 if before >= 4 else before)


@pytest.mark.parametrize('allowed', [0, 1])
def test_custom_rows_delegate_original_mode_gate(menu, allowed):
    cpu, base, call, _, _, _, callback, _, _ = menu
    seen = []

    def native_gate():
        seen.append(cpu.reg_read(R.UC_ARM64_REG_X0))
        # 原生入口已执行 0x20 字节压栈；本夹具仅替代后续模式服务。
        sp = cpu.reg_read(R.UC_ARM64_REG_SP)
        x29, lr = struct.unpack('<QQ', cpu.mem_read(sp, 16))
        cpu.reg_write(R.UC_ARM64_REG_X29, x29)
        cpu.reg_write(R.UC_ARM64_REG_LR, lr)
        cpu.reg_write(R.UC_ARM64_REG_SP, sp + 0x20)
        return allowed

    callback(base + 0x1bd5418, native_gate)
    for row in range(0x1600, 0x1606):
        assert call(0x1bd5414, row) == allowed
    assert seen == [126] * 6


@pytest.fixture
def disk(menu):
    cpu, base, call, get, set_, commit, callback, word, put = menu
    files, descriptors, fault = {}, {}, {}
    functions = ['open', 'openat', 'read', 'write', 'close', 'fsync', 'renameat', 'unlinkat',
                 '__errno_location', 'clock_gettime', 'nanosleep', 'pthread_attr_init',
                 'pthread_attr_setdetachstate', 'pthread_attr_setstacksize',
                 'pthread_create', 'pthread_attr_destroy']
    def reg(i): return cpu.reg_read(getattr(R, f'UC_ARM64_REG_X{i}'))
    def string(at):
        return bytes(cpu.mem_read(at, 128)).split(b'\0')[0].decode()
    def resolve():
        return DATA + 0x8000 + 4 * functions.index(string(reg(1)))
    callback(base + 0x16dac90, resolve)
    def open_dir():
        # 使用机端 AArch64 UAPI；不能把宿主机的目录位当成目标 ABI。
        assert string(reg(0)) == '/setting'
        assert reg(1) & 0x4000 and reg(1) & 0x8000 and not reg(1) & 0x10000, \
            'AArch64 目录必须使用 O_DIRECTORY，禁止误带 O_DIRECT'
        fault['opens'] = fault.get('opens', 0) + 1
        if fault.get('open'):
            put(DATA + 0x7f00, 5)
            return -1
        return 100
    def open_file():
        name, flags = string(reg(1)), reg(2)
        assert reg(0) == 100 and flags & 0x8000 and not flags & 0x10000
        if flags & 1:
            assert flags & 0x80 and reg(3) == 0o600
            files[name] = b''
        elif name not in files:
            put(DATA + 0x7f00, 2)
            return -1
        fd = 101 + len(descriptors)
        descriptors[fd] = [name, 0]
        return fd
    def read():
        name, offset = descriptors[reg(0)]
        if action := fault.pop('during_read', None): action()
        data = files[name][offset:offset + min(reg(2), 3)]
        cpu.mem_write(reg(1), data)
        descriptors[reg(0)][1] += len(data)
        return len(data)
    def write():
        name, offset = descriptors[reg(0)]
        fault['writes'] = fault.get('writes', 0) + 1
        if action := fault.pop('during_write', None): action()
        if 'queue_id' in fault:
            requested = word(base + SELECTION + 0x1b0)
            put(base + SELECTION + 0x1b0, ((requested & ~255) + 256) | fault.pop('queue_id'))
        if fault.get('write') and offset >= 5: return -1
        data = bytes(cpu.mem_read(reg(1), min(reg(2), 5)))
        files[name] += data
        descriptors[reg(0)][1] += len(data)
        return len(data)
    def rename():
        if fault.get('rename'): return -1
        files[string(reg(3))] = files.pop(string(reg(1)))
        return 0
    def unlink():
        files.pop(string(reg(1)), None)
        return 0
    for index, function in enumerate([open_dir, open_file, read, write, lambda: 0,
                                       lambda: -1 if fault.get('fsync') or
                                       fault.get('fsync_dir') and reg(0) == 100 else 0, rename, unlink]):
        callback(DATA + 0x8000 + index * 4, function)
    def clock():
        ms = fault.get('now_ms', 0)
        cpu.mem_write(reg(1), struct.pack('<qq', ms // 1000, ms % 1000 * 1000000))
        return 0
    def create():
        fault['threads'] = fault.get('threads', 0) + 1
        fault['worker_entry'] = reg(2)
        return -1 if fault.get('create') else 0
    for name, function in [('__errno_location', lambda: DATA + 0x7f00),
                           ('clock_gettime', clock), ('nanosleep', lambda: 0),
                           ('pthread_attr_init', lambda: 0),
                           ('pthread_attr_setdetachstate', lambda: 0),
                           ('pthread_attr_setstacksize', lambda: 0),
                           ('pthread_create', create), ('pthread_attr_destroy', lambda: 0)]:
        callback(DATA + 0x8000 + functions.index(name) * 4, function)
    for address in (0x2e7d208, 0x2e7cee4, 0x252ca34, 0x252d80c):
        callback(base + address, lambda: 0)
    callback(base + 0x1bceddc, lambda: 0x0200a54c)
    def restart():
        cpu.mem_write(base + SELECTION + 0x1a0, bytes(256))
        put(base + SELECTION, 0)
        put(DATA, 0)
        put(DATA + 4, 0)
    return menu, files, fault, restart


def flush(disk, count=1):
    fixture, _, fault, _ = disk
    for _ in range(count):
        fault['now_ms'] = fault.get('now_ms', 0) + 1000
        fixture[2](fixture[0].aspect_symbols['r5_aspect_persist_service'])


def test_confirm_persists_cancel_does_not_and_fresh_process_restores(disk):
    menu, files, _, restart = disk
    _, _, call, get, set_, commit, _, _, _ = menu
    call(set_, 9)
    call(commit, 0x1605)
    flush(disk)
    saved = files['r5_aspect10_v1.dat']
    assert struct.unpack('<4I', saved) == (0x41533552, 1, 9, 0xfffffff6)
    call(0x2adfd3c)
    call(set_, 8)
    call(0x2adfd5c)
    assert call(get) == 9 and files['r5_aspect10_v1.dat'] == saved
    restart()
    assert call(get) == 9
    call(commit, 126)
    flush(disk)
    restart()
    assert call(get) == 0


@pytest.mark.parametrize('broken', [b'', b'bad', struct.pack('<4I', 0x41533552, 1, 10, 0xfffffff5),
                                  struct.pack('<4I', 0x41533552, 1, 9, 0) + b'extra'])
def test_corrupt_setting_uses_native_and_explicit_choice_wins(disk, broken):
    menu, files, _, restart = disk
    _, _, call, get, set_, _, _, _, _ = menu
    files['r5_aspect10_v1.dat'] = broken
    restart()
    assert call(get) == 0
    restart()
    files['r5_aspect10_v1.dat'] = struct.pack('<4I', 0x41533552, 1, 9, 0xfffffff6)
    call(set_, 8)
    assert call(get) == 8


@pytest.mark.parametrize('failure', ['write', 'fsync', 'rename'])
def test_failed_save_keeps_previous_complete_record(disk, failure):
    menu, files, fault, restart = disk
    _, _, call, get, set_, commit, _, _, _ = menu
    call(commit, 0x1605)
    flush(disk)
    saved = files['r5_aspect10_v1.dat']
    fault[failure] = True
    call(set_, 8)
    call(commit, 0x1604)
    flush(disk)
    assert files['r5_aspect10_v1.dat'] == saved and call(get) == 8
    fault.clear()
    restart()
    assert call(get) == 9


def test_save_drains_newest_pending_choice_and_directory_sync_failure_keeps_complete_file(disk):
    menu, files, fault, restart = disk
    _, _, call, get, _, commit, _, _, _ = menu
    fault['queue_id'] = 8
    call(commit, 0x1605)
    flush(disk, 2)
    assert struct.unpack('<4I', files['r5_aspect10_v1.dat'])[2] == 8
    fault['fsync_dir'] = True
    call(commit, 0x1605)
    flush(disk)
    assert files['r5_aspect10_v1.dat'] == struct.pack('<4I', 0x41533552, 1, 9, 0xfffffff6)
    fault.clear()
    restart()
    assert call(get) == 9


def test_first_boot_wire_restores_without_opening_menu_and_preserves_inline_abi(disk):
    menu, files, _, restart = disk
    cpu, base, _, _, _, _, callback, _, _ = menu
    files['r5_aspect10_v1.dat'] = struct.pack('<4I', 0x41533552, 1, 9, 0xfffffff6)
    restart()
    functions = ['open', 'openat', 'read', 'write', 'close', 'fsync', 'renameat', 'unlinkat',
                 '__errno_location', 'clock_gettime']
    def noisy_resolver():
        pointer = cpu.reg_read(R.UC_ARM64_REG_X1)
        name = bytes(cpu.mem_read(pointer, 32)).split(b'\0')[0].decode()
        cpu.reg_write(R.UC_ARM64_REG_Q0, 0xabcdef)
        cpu.reg_write(R.UC_ARM64_REG_Q31, 0xfedcba)
        cpu.reg_write(R.UC_ARM64_REG_X18, 0x1234)
        cpu.reg_write(R.UC_ARM64_REG_FPSR, 0)
        return DATA + 0x8000 + functions.index(name) * 4
    callback(base + 0x16dac90, noisy_resolver)
    frame, source = STACK + 0x1000, DATA + 0x9000
    cpu.mem_write(source, bytes(16))
    cpu.mem_write(frame, bytes(0x300))
    vectors = {i: (0x5678 << 64) | i for i in range(32)}
    for i, value in vectors.items(): cpu.reg_write(getattr(R, f'UC_ARM64_REG_Q{i}'), value)
    for i, value in ((16, 0x1616), (17, 0x1717), (18, 0x1818), (20, source), (29, frame)):
        cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{i}'), value)
    cpu.reg_write(R.UC_ARM64_REG_FPSR, 1)
    cpu.reg_write(R.UC_ARM64_REG_SP, frame)
    cpu.emu_start(base + 0x3565f78, base + 0x3565fac, count=10000)
    assert cpu.reg_read(R.UC_ARM64_REG_PC) == base + 0x3565fac
    assert cpu.reg_read(R.UC_ARM64_REG_SP) == frame
    assert bytes(cpu.mem_read(frame + 0x77, 1)) == b'\xe5'
    assert cpu.reg_read(R.UC_ARM64_REG_X18) == 0x1818
    assert cpu.reg_read(R.UC_ARM64_REG_FPSR) == 1
    assert all(cpu.reg_read(getattr(R, f'UC_ARM64_REG_Q{i}')) == value for i, value in vectors.items())
