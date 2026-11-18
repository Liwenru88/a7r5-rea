"""冻结CP的原始收包窗口探测。只替换OSAL消息与信号量。"""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import sys
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_INVALID
from unicorn import arm_const as ARM

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'a7r5-firmware-features/native24-combined/dependencies/native12-combined/tests'))
import runtime_support

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('request', type=Path, nargs='?')
parser.add_argument('--construct', action='store_true')
parser.add_argument('--imaging', action='store_true')
parser.add_argument('--notify', action='store_true')
parser.add_argument('--boot-snapshot', type=Path, help='使用本实验 QEMU 的只读调度现场')
args = parser.parse_args()
if args.boot_snapshot is not None and (not args.request or not args.construct or args.notify or args.imaging):
    parser.error('调度现场仅用于回放原厂 0x4063 并核对任务 10 的实际返回')

build = ROOT / '.local/ui-refresh-20261104/fix-02'
runtime_support.BASELINE = build
raw = (build / 'cpapp-b.bin').read_bytes()
assert hashlib.sha256(raw).hexdigest() == '35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300'
cp = runtime_support.CP(raw)
if args.boot_snapshot is not None:
    snapshot = args.boot_snapshot.resolve()
    if snapshot.parent != ROOT/'a7r5-qemu/runs' or not snapshot.name.startswith('native-native24-cp-boot-'):
        raise ValueError('CP 现场路径不符')
    boot = json.loads((snapshot/'result.json').read_text())
    state = json.loads((snapshot/'cp-boot-state.json').read_text())
    if (boot['CP_sha256'] != hashlib.sha256(raw).hexdigest()
            or boot['AP_connected'] or state['guest_memory_writes'] != 0):
        raise ValueError('CP 现场身份或观察边界不符')
    regions = {row['address']: row for row in state['regions']}
    extra = boot['task_ram']
    if isinstance(extra, dict):
        extra = [extra]
    regions.update((row['address'], row) for row in extra)
    required = [(0x1100000, 0x400000, 'cp-runtime-01100000.bin', False),
                (0x1500000, 0x500000, 'cp-runtime-01500000.bin', False),
                (0x1c00000, 0x1400000, 'cp-task-ram.bin', True)]
    optional = [(0xe0000, 0x20000, 'cp-klog-ram.bin', True),
                (0x3400000, 0x200000, 'cp-tmon-ram.bin', True)]
    for address, size, name, needs_mapping in required + [row for row in optional if row[0] in regions]:
        image = snapshot/name
        if image.is_symlink() or image.stat().st_size != size or regions[address]['bytes'] != size:
            raise ValueError('CP 现场区域不符')
        payload = image.read_bytes()
        if hashlib.sha256(payload).hexdigest() != regions[address]['sha256']:
            raise ValueError('CP 现场摘要不符')
        if needs_mapping:
            cp.cpu.mem_map(address, size)
        cp.write(address, payload)
    print('QEMU_SNAPSHOT_PCB', [hex(n) for n in cp.words(0x19e391c,4)], flush=True)
cp.cpu.reg_write(ARM.UC_ARM_REG_C1_C0_2, 0xf << 20)
cp.cpu.reg_write(ARM.UC_ARM_REG_FPEXC, 1 << 30)
slots = {}
outbox = []
locked = False
history = []

def get(n):
    return cp.cpu.reg_read(getattr(ARM, 'UC_ARM_REG_R' + str(n)))

def service(cpu, at, size, data):
    global locked
    history.append(at)
    if len(history) > 30:
        del history[0]
    result = 0
    if args.boot_snapshot and at in (0x5bd744, 0xadf9e8, 0x5c3820):
        print('NATIVE_RTOS', hex(at), 'r0', hex(get(0)), flush=True)
    if at in (0x5b8d6c, 0x5b8910):
        assert get(0) == 0x24 and locked == (at == 0x5b8910)
        locked = at == 0x5b8d6c
    elif at in (0x53c220, 0x4eb698):
        queue, target, length = get(0), get(1), get(2)
        assert queue in (0x80020002, 0x90040193, 0x90030001, 0x8f013a, 0x900302d9) and 0 < length <= 4096, (hex(queue), length)
        pointer = 0x3180000 + (1 + len(slots))*0x2000
        assert pointer < 0x3200000
        slots[pointer] = (queue, length)
        cp.write(pointer - 16, bytes(length + 16))
        cp.write(target, struct.pack('<I', pointer))
    elif at == 0x53bb54:
        queue, pointer = get(0), get(1)
        assert queue == slots[pointer][0]
        payload = cp.read(pointer, slots[pointer][1])
        src = cp.words(pointer-12, 1)[0]
        outbox.append((queue, src, payload))
        print('NATIVE_CP_TX', hex(queue), hex(src), len(payload), payload[:24].hex(), flush=True)
    elif at == 0xbaad0c:
        result = slots[get(0)][1]
    elif at == 0x53c31c:
        print('NATIVE_CP_FREE', hex(get(0)), hex(get(1)), flush=True)
    elif at == 0xb0de92:
        print('NATIVE_CP_LOG', cp.read(get(0), 100).split(b'\0', 1)[0], flush=True)
    else:
        return
    cpu.reg_write(ARM.UC_ARM_REG_R0, result)
    cpu.reg_write(ARM.UC_ARM_REG_PC, cpu.reg_read(ARM.UC_ARM_REG_LR))

cp.cpu.hook_add(UC_HOOK_CODE, service)
def invalid(cpu, kind, address, size, value, _):
    print('FAULT',kind,hex(address),size,'pc',hex(cpu.reg_read(ARM.UC_ARM_REG_PC)), 'lr',hex(cpu.reg_read(ARM.UC_ARM_REG_LR)), 'history', [hex(x) for x in history], flush=True)
    return False
cp.cpu.hook_add(UC_HOOK_MEM_INVALID, invalid)

def receive(packet):
    print('RECEIVE', len(packet), packet[:12].hex(), flush=True)
    if args.boot_snapshot:
        # 复用原 0x5cc2c4 的 System 态和 IRQ 调用约定。
        cp.cpu.reg_write(ARM.UC_ARM_REG_CPSR, 0x1f)
    pointer = cp.PACKET
    slots[pointer] = (0x90030001, len(packet))
    cp.write(pointer-12, struct.pack('<I', 0x80020002))
    cp.write(pointer, packet)
    sp = cp.STACK + 0xe000
    cp.write(sp, struct.pack('<I', pointer))
    for reg, val in [(ARM.UC_ARM_REG_SP,sp),(ARM.UC_ARM_REG_LR,cp.STOP|1),(ARM.UC_ARM_REG_R4,0x90030001),(ARM.UC_ARM_REG_R11,0x7a0020)]:
        cp.cpu.reg_write(reg,val)
    cp.cpu.emu_start(0x496019,0x49606e,count=1000000)
    assert cp.cpu.reg_read(ARM.UC_ARM_REG_PC) == 0x49606e and not locked
    print('RETURN', [hex(x) for x in cp.words(0x157aa10,12)], flush=True)

def receive_imaging_notification_request():
    queue, source, payload = next(row for row in outbox if row[2][:4] == bytes.fromhex('050018d0'))
    assert (queue, source, len(payload)) == (0x90040193, 0x90030001, 12)
    pointer = cp.PACKET
    cp.write(pointer-12, struct.pack('<I', source))
    cp.write(pointer, payload)
    slots[pointer] = (queue, len(payload))
    sp = cp.STACK + 0xe000
    cp.write(sp, struct.pack('<I', pointer))
    for reg, value in [(ARM.UC_ARM_REG_SP, sp), (ARM.UC_ARM_REG_R4, queue),
                       (ARM.UC_ARM_REG_R8, 0x18e8580), (ARM.UC_ARM_REG_R9, 0x4036),
                       (ARM.UC_ARM_REG_R10, 0x406a), (ARM.UC_ARM_REG_R11, 0x40a4)]:
        cp.cpu.reg_write(reg, value)
    assert cp.words(0x18e8580+0x2d4, 1) == (0,)
    assert cp.words(0x18e8580+0x2e0, 1) == (0,)
    before = len(outbox)
    cp.cpu.emu_start(0x44108d, 0x441076, count=100000)
    assert cp.cpu.reg_read(ARM.UC_ARM_REG_PC) == 0x441076
    assert cp.words(0x18e8580+0x2e0, 1) == (1,) and len(outbox) == before
    print('NATIVE_D018_DEFERRED', 'peer_context=0x18e8580 pending=1 prerequisite_2d4=0', flush=True)

if args.construct or args.notify:
    # 原启动 0xafcb70 将 0x157aa10 工作区复制到 0x164eef0。
    root = 0x164eef0 if args.boot_snapshot else 0x1653c68
    if args.notify:
        # 复用原启动 0xafd010..0xafd076 所使用的各子上下文 getter。
        getters = (0x70891d, 0x88715f, 0x964a89, 0x7195b1, 0xabbbf7,
                   0x9075ad, 0x88c3b7, 0x89b6b3, 0xafc061)
        pointers = [cp.call(getter) for getter in getters]
        cp.write(root+0x4b28, struct.pack('<9I', *pointers))
        print('NATIVE_GETTERS', [hex(p) for p in pointers], flush=True)
    cp.call(0xafd2db, root, 0x165d758)
    print('NATIVE_CONTEXT_POINTERS', [hex(x) for x in cp.words(0x165d758, 16)], flush=True)
if args.request:
    init_request = args.request.read_bytes()
    assert hashlib.sha256(init_request).hexdigest() == 'b3a5829f8751d224b49b64c3fa3ee7efce1aa1683d6877c0682144e0ce4702b2'
    receive(init_request)
receive(bytes.fromhex('050073400400008001000000'))
assert any(src==0x90030001 and queue==0x80020002 and p==bytes.fromhex('010073400400008000f00000') for queue,src,p in outbox)
assert any(src==0x90030001 and queue==0x90040193 and p[:4]==bytes.fromhex('050018d0') for queue,src,p in outbox)
assert not any(len(p)>=1736 for _,_,p in outbox), '下一阶段才允许出现原生通知'
if args.imaging:
    receive_imaging_notification_request()
if args.notify:
    # 只执行已定位的生产函数，缺少原 CP 调度的步骤仍未闭合。
    cp.call(0x33cd7d)
    print('NATIVE_PRODUCER_RETURN', [hex(x) for x in cp.words(0x165d758, 16)], flush=True)
