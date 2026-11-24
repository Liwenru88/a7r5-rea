"""统一候选的双CPU验证夹具；不连接设备，不提供成像硬件模型。"""
import json
import os
from pathlib import Path
import struct
import zlib

from runtime_support import AP, CP, HERE


AP_SHA = 'e833e0290fe60207cc5d9d2b7a0a66b253f7ab0db99ed12afb2a0c47ca6f72f1'
CP_SHA = 'bb8eeaaeb9d13a4687605de6e01ccbe4adc500f595d2f8dbfe886eedd8a643d0'
U64 = (1 << 64) - 1


class UnifiedReplay:
    """真实启动、菜单调度、传输、选择及文件协议；OS和原厂UI/E4边界显式替身。"""

    def __init__(self, candidate, cp_raw, files=None, cards=None, native_selector=0):
        import hashlib
        assert hashlib.sha256(candidate[0]).hexdigest() == AP_SHA
        assert hashlib.sha256(cp_raw).hexdigest() == CP_SHA
        self.ap, self.cp = AP(candidate[0]), CP(cp_raw)
        self.ap.symbols.update(candidate[1]['symbols'])
        # 启动工作线程含约64KiB局部缓冲，使用独立、已映射的验证栈。
        self.ap.STACK = 0x60300000
        self.cp.receiver_services()
        self.files = dict(files or {})
        self.cards = dict(cards or {})
        self.handles = {}
        self.next_fd = 20
        self.ms = self.message_size = 0
        self.trace = []
        self.mid = 0x84c
        self.native = native_selector
        self.fail_refresh = False
        self.on_refresh = None
        self.manager = self.ap.DATA + 0x70000
        self.view = self.ap.DATA + 0x71000
        self.controller = self.ap.DATA + 0x72000
        self.ap.write(self.manager + 0x338, struct.pack('<Q', self.view))
        self.ap.write(self.view, struct.pack('<Q', 0x58ca670))
        self.ap.write(self.controller + 0x178, struct.pack('<I', 0xd9))
        self.ap.write(self.controller + 0x180, struct.pack('<Q', self.manager))
        self.callbacks = {}
        for name, callback in (
            ('clock_gettime', self.clock), ('nanosleep', self.sleep),
            ('sched_setscheduler', lambda a: 0), ('open', self.unexpected_open),
            ('openat', self.openat), ('read', self.read), ('write', self.write),
            ('close', self.close), ('sync', self.sync), ('renameat', self.rename),
            ('unlinkat', self.unlink), ('dup', self.duplicate),
            ('error_number', lambda a: a.DATA + 0x7f000),
        ):
            at = self.ap.DATA + 0x74000 + 16 * len(self.callbacks)
            self.callbacks[name] = at
            self.ap.stub(at, callback)
        self.ap.stub('r5_stage411_dlsym', lambda a: self.callbacks.get(a.string(a.arg(1)), 0))
        self.ap.stub('r5_osal_msg_size', lambda a: self.message_size)
        self.ap.stub('r5_native_ap_send', self.send)
        self.ap.stub('r5_native_lut_directory_api_init', self.directory_api)
        self.ap.stub('r5_lut_directory_acquire', self.acquire)
        self.ap.stub('r5_lut_directory_release', self.release)
        self.ap.stub('r5_native_fsys_open', self.card_open)
        self.ap.stub('r5_native_fsys_read', self.card_read)
        self.ap.stub('r5_native_fsys_close', self.close)
        # 不写refresh_done；通过真实所有权包装器，模拟原E4执行的外部返回。
        self.ap.stub('r5_native_creative_sequence_request', self.refresh)
        self.ap.stub('r5_native_refresh_construct425', lambda a: 0)
        self.ap.stub('r5_native_refresh_execute425', lambda a: 0)
        for name in ('r5_log420_emit', 'r5_grid420_watch', 'r5_transfer420_log', 'r5_probe420_log'):
            self.ap.stub(name, lambda a: 0)
        self.ap.stub(0x28a87e8, self.current_mid)
        self.ap.stub(0x17ffd84, lambda a: 0)
        self.ap.stub(0x28bfdcc, self.layout)
        self.ap.stub(0x1c05f18, lambda a: self.native)
        self.ap.stub('n12_stock_refresh', lambda a: 0)
        self.ap.stub('n12_stock_labels', lambda a: 0)
        self.ap.stub('n12_stock_inhibited', lambda a: 0)
        for name in ('select', 'preview', 'preview_menu'):
            self.ap.stub('n12_stock_' + name, lambda a, name=name: self.stock(a, name))

    def error(self, number):
        self.ap.write(self.ap.DATA + 0x7f000, struct.pack('<I', number))
        return U64

    def clock(self, ap):
        ap.write(ap.arg(1), struct.pack('<qq', self.ms // 1000, self.ms % 1000 * 1000000))
        return 0

    def sleep(self, ap):
        seconds, ns = struct.unpack('<qq', ap.read(ap.arg(0), 16))
        self.ms += max(1, seconds * 1000 + ns // 1000000)
        return 0

    def unexpected_open(self, ap):
        raise AssertionError('验证夹具不允许绝对路径OS访问')

    def descriptor(self, name, data, writable=False):
        fd = self.next_fd
        self.next_fd += 1
        self.handles[fd] = [name, bytearray(data), 0, writable]
        return fd

    def openat(self, ap):
        assert ap.arg(0) == 9
        name, flags = ap.string(ap.arg(1)), ap.arg(2)
        assert name in ('R5NATIVE.BIN', 'R5NATIVE.NEW', 'R5FILTER.BIN', 'R5FILTER.NEW')
        self.trace.append(['open', name, flags])
        if flags == 0x8000:
            return self.descriptor(name, self.files[name]) if name in self.files else self.error(2)
        assert flags == 0x80c1
        if name in self.files:
            return self.error(17)
        self.files[name] = b''
        return self.descriptor(name, b'', True)

    def read(self, ap):
        name, raw, pos, writable = self.handles[ap.arg(0)]
        # 配方读保持在真实适配器的64次调用预算内；24B边车仍覆盖分段读取。
        data = raw[pos:pos + min(ap.arg(2), 1024 if 'NATIVE' in name else 13)]
        ap.write(ap.arg(1), data)
        self.handles[ap.arg(0)][2] += len(data)
        return len(data)

    def write(self, ap):
        name, raw, pos, writable = self.handles[ap.arg(0)]
        assert writable
        data = ap.read(ap.arg(1), min(ap.arg(2), 1024 if 'NATIVE' in name else 11))
        raw.extend(data)
        self.files[name] = bytes(raw)
        return len(data)

    def close(self, ap):
        assert ap.arg(0) in self.handles
        del self.handles[ap.arg(0)]
        return 0

    def sync(self, ap):
        fd = ap.arg(0)
        assert fd == 9 or fd in self.handles
        self.trace.append(['sync', 'directory' if fd == 9 else self.handles[fd][0]])
        return 0

    def rename(self, ap):
        assert ap.arg(0) == ap.arg(2) == 9
        source, target = ap.string(ap.arg(1)), ap.string(ap.arg(3))
        assert (source, target) in (('R5NATIVE.NEW', 'R5NATIVE.BIN'), ('R5FILTER.NEW', 'R5FILTER.BIN'))
        self.files[target] = self.files.pop(source)
        self.trace.append(['publish', target])
        return 0

    def unlink(self, ap):
        assert ap.arg(0) == 9
        name = ap.string(ap.arg(1))
        assert name in ('R5NATIVE.NEW', 'R5FILTER.NEW')
        if name not in self.files:
            return self.error(2)
        del self.files[name]
        return 0

    def duplicate(self, ap):
        assert ap.arg(0) == 9
        return self.descriptor('directory', b'')

    def directory_api(self, ap):
        names = ('open', 'openat', 'read', 'write', 'close', 'sync', 'renameat', 'unlinkat', 'dup', 'error_number')
        ap.write(ap.arg(0), struct.pack('<10Q', *(self.callbacks[n] for n in names)))
        return 0

    def acquire(self, ap):
        ap.write(ap.arg(0), ap.read(ap.arg(1), 80) + struct.pack('<iii4xQ', 9, 2, 0, 1))
        return 0

    def release(self, ap):
        ap.write(ap.arg(0) + 84, struct.pack('<I', 3))
        return 0

    def card_open(self, ap):
        name = ap.string(ap.arg(0))
        self.trace.append(['card_open', name])
        if name not in self.cards:
            return U64
        assert ap.arg(1) == 1
        fd = self.descriptor(name, self.cards[name])
        ap.write(ap.arg(2), struct.pack('<Q', fd))
        return 0

    def card_read(self, ap):
        result = self.read(ap)
        ap.write(ap.arg(3), struct.pack('<Q', result))
        return 0

    def send(self, ap):
        packet = ap.read(ap.arg(1), ap.arg(2))
        self.trace.append(['packet', packet.hex()])
        reply = self.cp.consume(packet)
        if reply:
            ack = ap.DATA + 0x78000
            ap.write(ack, reply)
            self.message_size = len(reply)
            ap.pending.append(('r5_stage411_inbound', (ack, 0x90030001)))
        return 0

    def refresh(self, ap):
        self.trace.append(['e4_fixture', self.fail_refresh])
        if self.on_refresh:
            context = ap.cpu.context_save()
            self.on_refresh()
            ap.cpu.context_restore(context)
        if not self.fail_refresh:
            obj = ap.DATA + 0x79000
            ap.pending.extend([
                ('r5_filter_refresh_construct425', (obj, ap.arg(0) + 16)),
                ('r5_filter_refresh_execute425', (obj,)),
            ])
        return 0

    def current_mid(self, ap):
        ap.write(ap.DATA + 0x7a000, struct.pack('<I', self.mid))
        return ap.DATA + 0x7a000

    def layout(self, ap):
        ap.write(ap.DATA + 0x7a008, bytes(4))
        return ap.DATA + 0x7a008

    def stock(self, ap, name):
        # 委派前必须真实完成退出；原厂后续属性写入由已有三路测试独立覆盖。
        context = ap.cpu.context_save()
        selected = ap.call('r5_filter_selected')
        ap.cpu.context_restore(context)
        assert selected == 0
        self.trace.append(['stock_' + name, ap.arg(0)])
        if name == 'preview_menu':
            self.native = ap.words(0x3f4a280 + (self.mid - 0x84c) * 128 + 0x34, 1)[0]
        else:
            self.native = ap.arg(1) if name == 'preview' else ap.arg(0)
        return 0

    def boot(self):
        ap = self.ap
        ap.call('r5_session_cold')
        assert ap.call('r5_session_prepare') == 1
        present = [int(any(name.startswith(letter + ':/') for name in self.cards)) for letter in 'AB']
        ap.call('r5_stage411_initial', *present)
        for slot, letter in enumerate('AB'):
            ap.call('r5_stage411_completed', slot)
            ap.call('r5_stage411_media', slot, 0 if present[slot] else 1, ord(letter))
        ap.call('r5_stage411_child', ap.symbols['r5_stage411_state'], count=20000000)
        ap.call('r5_session_finish')
        assert not self.handles
        self.observe('boot')

    def choose(self, slot):
        self.mid = 0x160f + slot
        self.ap.call(0x1c956c8, self.mid)

    def native_target(self, mid):
        self.mid = mid
        self.ap.call(0x1c956c8, mid)

    def service(self):
        self.ap.call('r5_filter_service')
        self.ap.call(0x1e97a24, self.manager)
        self.observe('service')

    def observe(self, label):
        self.trace.append(['observe', {
            'label': label, 'mid': self.mid, 'selected_AP_CP_file': self.selected(),
            'command': self.ap.call('r5_filter_command_state'),
            'sequence': self.ap.call('r5_filter_command_sequence'),
            'native_selector_fixture': self.native,
        }])

    def selection_packets(self):
        return [struct.unpack_from('<I', bytes.fromhex(row[1]), 12)[0]
                for row in self.trace if row[0] == 'packet' and bytes.fromhex(row[1])[0] == 0xea]

    def selected(self):
        sidecar = self.files.get('R5FILTER.BIN', b'')
        assert len(sidecar) == 24 and sidecar[:8] == b'R5SEL4\0\0'
        assert struct.unpack_from('<I', sidecar, 20)[0] == zlib.crc32(sidecar[:20] + bytes(4))
        selected = self.cp.words(0x1a3945c + 8, 1)[0]
        view = self.cp.words(0x1a39458, 1)[0]
        assert self.cp.words(view + 8, 1)[0] == selected
        return (self.ap.call('r5_filter_selected'), selected, struct.unpack_from('<I', sidecar, 12)[0])

    def record(self, name):
        folder = os.environ.get('A7R5_UNIFIED_VERIFY_OUTPUT')
        if folder:
            target = Path(folder)
            target.mkdir(parents=True, exist_ok=True)
            (target / (name + '.json')).write_text(json.dumps({
                'AP_sha256': AP_SHA, 'CP_sha256': CP_SHA, 'trace': self.trace,
                'files': {key: value.hex() for key, value in self.files.items()},
                'selected': self.selected(), 'native_selector_fixture': self.native,
                'open_handles': len(self.handles), 'CP_allocations': self.cp.heap_allocations,
                'boundary': 'OS/目录锚定、时钟、原厂UI与E4外部执行为测试替身；非QEMU/实机验收',
            }, ensure_ascii=False, indent=2) + '\n')


def recipe():
    return (HERE / 'upstream/filters/FUJ_12_v45/R5NATIVE.BIN').read_bytes()
