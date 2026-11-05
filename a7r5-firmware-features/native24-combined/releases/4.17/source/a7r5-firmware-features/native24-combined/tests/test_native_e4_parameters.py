"""执行原E4九次分派与逐项打包；队列/时钟/存储为明确夹具。"""
import struct

from test_parameters import ParameterReplay, BASE, IDS, display_custom


class NativeE4Replay(ParameterReplay):
    def __init__(self):
        self.native_packets = []
        self.native_errors = []
        self.reject_property = 0
        super().__init__()
        self.ap.stubs.pop(self.ap.symbols['r5_native_refresh_execute425'])
        self.ap.stubs.pop(0x355882c)
        self.native_heap=self.ap.DATA+0xb0000
        self.ap.stub(0x16dc130,lambda a:self.allocate(a.arg(0)))
        self.ap.stub(0x16dc740,self.allocate_message)
        self.ap.stub(0x16d9770,self.copy_native)
        self.ap.stub(0x16d99c0,lambda a:0)
        self.ap.stub(0x352be50,self.empty_future)
        for at in (0x16dcc90,0x30bf16c,0x352132c,0x17fc5d4,0x17fc630,0x30bedb0):
            self.ap.stub(at,lambda a:0)
        # 故障注入时让原厂错误处理返回，仅验证私有回退，不承诺实机错误处理不终止。
        self.ap.stub(0x35b858c,lambda a:self.native_errors.append(tuple(a.arg(i) for i in range(3))) or 0)
        self.ap.stub(0x352a7e8,lambda a:0x1c0ffee)
        # 原生分派器的日志/临界区服务不属于本测试的硬件边界。
        for at in (0x36951e0, 0x36952a0, 0x369448c):
            self.ap.stub(at, lambda a: 0)

    def allocate(self,size):
        pointer=self.native_heap;self.native_heap+=(size+15)&~15
        assert self.native_heap<self.ap.DATA+0xf0000
        return pointer

    def allocate_message(self,ap):
        pointer=self.allocate(ap.arg(2));self.native_message_sizes[pointer]=ap.arg(2)
        ap.write(ap.arg(1),struct.pack('<Q',pointer));return 0

    def copy_native(self,ap):
        ap.write(ap.arg(0),ap.read(ap.arg(1),ap.arg(2)));return ap.arg(0)

    def empty_future(self,ap):
        ap.write(ap.arg(0),bytes(24));ap.write(ap.arg(2),bytes(16));return 0

    def native_transport(self, ap):
        assert ap.arg(0) == 0x90030001 and self.native_message_sizes[ap.arg(1)]==12
        packet = ap.read(ap.arg(1), 12)
        prop = struct.unpack_from('<H', packet, 2)[0]
        self.native_packets.append(packet)
        if prop == self.reject_property:return 0xffffffff
        return super().native_transport(ap) if prop in IDS else 0

    def refresh(self, ap):
        obj = ap.DATA + 0x79000
        # ST照片布局的已验证E4对象字段；构造与队列本身仍为夹具。
        data = bytearray(0x38)
        struct.pack_into('<III', data, 0x14, 0, 0, 0)
        data[0x20:0x28] = bytes(BASE)
        struct.pack_into('<I', data, 0x30, 0)
        ap.write(obj, data)
        ap.pending.extend([
            ('r5_filter_refresh_construct425', (obj, ap.arg(0)+16)),
            ('r5_filter_refresh_execute425', (obj,)),
        ])
        return 0

def test_native_e4_individual_messages_apply_all_eight_values_without_full_packet():
    r = NativeE4Replay()
    r.boot()
    display_custom(r, 13)
    desired = (2, 3, 4, 2, -2, 7, 5, 4)
    for i, value in enumerate(desired):
        assert r.ap.call('r5_tune_edit', 13, i, value) == 0
    before=len(r.native_packets)
    r.choose(13)
    for _ in range(3):
        r.service()
    r.record('native-e4-individual-before-result')
    assert r.ap.call('r5_filter_command_state') == 2, '真实逐项E4不能被误判为等待整包或应用失败'
    assert r.selected() == (13, 13, 13)
    assert not r.native_errors
    assert len(r.native_packets[before:])==9, '只运行原E4九次分派，不能额外重发参数'
    delivered = {}
    for packet in r.native_packets:
        prop = struct.unpack_from('<H', packet, 2)[0]
        delivered[prop] = struct.unpack_from('b', packet, 8)[0]
    assert tuple(delivered[prop] for prop in IDS) == desired
    assert r.cp_values() == desired
    assert 'R5RECOV.BIN' not in r.files
    r.record('native-e4-individual-parameters')
    r.native_target(0x84c)
    for _ in range(3):r.service()
    assert r.selected()==(0,0,0)
    assert r.cp_values()==BASE, '退出自定义滤镜必须恢复原生八项，不能残留自定义对比度'
    r.record('native-e4-factory-parameters-restored')


def test_native_parameter_send_failure_rolls_back_and_idle_does_not_retry():
    r = NativeE4Replay();r.boot();display_custom(r,13)
    r.reject_property=IDS[0]
    r.choose(13)
    for _ in range(3):r.service()
    assert r.selected()==(0,0,0)
    assert r.ap.call('r5_filter_command_state')==3
    assert r.native_errors
    count=len(r.native_packets)
    r.ap.stub('n12_stock_dispatch',lambda a:0)
    for _ in range(3):
        r.ap.call('n12_dispatch',r.controller,0,0x20f0001)
        r.ap.call('r5_filter_service')
    assert len(r.native_packets)==count
    assert r.selected()==(0,0,0)
    r.record('native-e4-send-failure-rollback')


def test_parameter_observation_requires_all_distinct_fields_and_current_generation():
    r=NativeE4Replay();r.boot();display_custom(r,13)
    assert r.ap.call('r5_tune_prepare',13,0)==0
    generation=r.ap.call('r5_tune_generation425')
    for _ in range(8):r.ap.call('r5_tune_sent425',generation,1,0)
    assert r.ap.call('r5_tune_verify')!=0
    for bit in range(1,7):r.ap.call('r5_tune_sent425',generation,1<<bit,0)
    assert r.ap.call('r5_tune_verify')!=0
    r.ap.call('r5_tune_sent425',generation,128,0)
    assert r.ap.call('r5_tune_verify')==0
    assert r.ap.call('r5_tune_prepare',13,0)==0
    r.ap.call('r5_tune_sent425',generation,255,0)
    assert r.ap.call('r5_tune_verify')!=0


def test_receipt_cannot_cross_prepare_after_generation_check():
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    from unicorn import UC_HOOK_CODE

    r=NativeE4Replay();r.boot();display_custom(r,13);ap=r.ap
    assert ap.call('r5_tune_prepare',13,0)==0
    generation=ap.call('r5_tune_generation425')
    start=ap.symbols['r5_tune_sent425']
    instructions=Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(ap.read(start,512),start)
    point=next(i.address for i in instructions if i.mnemonic in ('ldxr','ldaxr'))
    armed=[True]

    def switch_snapshot(cpu,at,size,_):
        if armed[0] and at==point:
            armed[0]=False
            # 精确插在回执检查与原子写之间，模拟另一线程发布下一事务。
            ap.pending.append(('r5_tune_prepare',(13,0)))
            cpu.emu_stop()

    handle=ap.cpu.hook_add(UC_HOOK_CODE,switch_snapshot)
    ap.call('r5_tune_sent425',generation,255,0)
    ap.cpu.hook_del(handle)
    assert not armed[0]
    assert ap.call('r5_tune_generation425')!=generation
    assert ap.call('r5_tune_verify')!=0, '旧回执不能在新事务尚未发送时将其标记完成'
    r.record('late-receipt-interleaves-prepare')
    generation=r.ap.call('r5_tune_generation425')
    r.ap.call('r5_tune_sent425',generation,255,0xffffffff)
    r.ap.call('r5_tune_sent425',generation,255,0)
    assert r.ap.call('r5_tune_verify')!=0
