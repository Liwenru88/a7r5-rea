"""合并CP的实际参数消费和引导上下文，不模拟ISP或实际声音。"""
import ctypes as C
import struct
import json

import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn import arm_const as A

from runtime_support import CP, BASELINE, decoded
from test_runtime_transport import codec, upload, select


def test_real_boot_mapper_copy_metadata_clear_and_stack_boundary(images):
    raw, report = images[3], images[5]
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0x100000, 0x1b00000)
    cpu.mem_write(0x108000, raw)
    cpu.mem_map(0x3000000, 0x10000)
    # 原厂引导等待的两个MMIO字节显式设为0；不把此处当硬件就绪证明。
    cpu.mem_map(0x3e42000, 4096)
    cpu.reg_write(A.UC_ARM_REG_SP, 0x3008000)
    cpu.emu_start(0x108398, 0x108728, count=5000000)
    assert cpu.reg_read(A.UC_ARM_REG_PC) == 0x108728
    assert bytes(cpu.mem_read(0x1a3a000, 3456)) == __import__('patches').cp_payload(images[1])
    assert bytes(cpu.mem_read(0x11d4000, 3456)) == bytes(3456)
    # 原厂0x418元数据清理未覆盖新暂存目的地；共享状态/栈位置保持。
    assert bytes(cpu.mem_read(0x1197000+0x18, 0x400)) == bytes(0x400)
    root = struct.unpack('<I', bytes(cpu.mem_read(0x108f1c, 4)))[0]
    assert root == report['page_table_root']
    def page(va):
        l1 = struct.unpack('<I', bytes(cpu.mem_read(root+(va>>20)*4, 4)))[0]
        if l1 & 3 == 2: return (l1 & 0xfff00000)+(va&0xfffff), l1
        assert l1 & 3 == 1
        l2 = struct.unpack('<I', bytes(cpu.mem_read((l1&~1023)+((va>>12)&255)*4, 4)))[0]
        assert l2 & 2
        return (l2&~4095)+(va&4095), l2
    for va in (0x1a3a000, 0x1a3ad7f, 0x1a3c000):
        assert page(va)[0] == va
    for va in (0x1195000, 0x1196000):
        assert page(va)[0] == va
        assert page(va)[1]&1 == 0, '上游运行时代码页不得变为XN'


def test_published_gamma_keeps_native_tails_routes_and_all_grid_strengths(images, codec):
    cp, value = CP(images[3]), decoded(codec)
    assert upload(codec, cp, value)[0].phase == 4
    route = cp.words(0x107eefc, 44)
    native = [cp.words(0x107e968+28*n, 7) for n in range(51)]
    wires = (0, 3, 2, 1, 16, 15, 19, 20, 17, 18, 5, 13)
    order = struct.unpack('<405H', cp.read(0xe8c1d8, 810))
    assert sorted(order) == list(range(405))
    for selected in range(1, 13):
        view = cp.words(cp.BANK+50896+selected*24, 6)
        _, bank, n, table, routes, normal = view
        assert (bank, n) == (cp.BANK, selected)
        assert cp.read(table, 51*28) == cp.read(0x107e968, 51*28)
        curve = bytes(value.look[selected-1].gamma)
        for index, wire in enumerate(wires):
            for k in range(3):
                row = 51+2*index+(k==2)
                column = 6 if k else 0
                record = cp.words(table+row*28+column*4, 1)[0]
                source = native[route[wire*2+(k==2)]][6 if k else 0]
                assert cp.read(record, 516) == curve
                assert cp.read(record+516, 60) == cp.read(source+516, 60)
            assert cp.words(routes+wire*8, 2) == (51+2*index, 52+2*index)
        assert cp.words(normal, 2) == (51, 52)
        for level in range(8):
            actual = cp.words(cp.BANK+52352+8+((selected-1)*8+level)*405*4, 405)
            for point in range(405):
                packed = 0
                for channel in range(3):
                    v = value.look[selected-1].grid[channel*405+point]
                    if level<7: v = v*(level+1)>>3
                    packed |= (v&127) << (22-10*channel)
                assert actual[order[point]] == packed


def test_custom_selection_cc1_and_matrix_take_precedence_over_fl23_then_restore(images, codec):
    cp, value = CP(images[3]), decoded(codec)
    assert upload(codec, cp, value)[0].phase == 4
    cp.write(0x1a39448, struct.pack('<II', cp.BANK, 28768))
    cp.call('r5_filter423_accept', 0x1234, 1)
    root, env, work, out = 0x3120000, 0x3121000, 0x3122000, 0x3123000
    cp.write(work, struct.pack('<II', root, env))
    cp.write(env+0x1a0, struct.pack('<3H', 1000,1100,1200))
    for selected in range(1,13):
        assert select(cp, selected, selected) == 0
        for wire, actuals in ((19,(54,56)), (20,(55,57)), (0,(0,21)), (3,(6,27))):
            cp.write(root+0x2e, bytes([wire]))
            for actual in actuals:
                cp.write(env+0x25, bytes([actual]))
                assert cp.call('r5_native418_available', work, actual) == 1
                assert cp.call('r5_native418_cc1', 0xdeadbeef, work, actual) == cp.BANK+64+(selected-1)*2392+32
                for special in (0x16b1e34,0x16b1e64):
                    assert cp.call('r5_native418_cc1', special, work, actual) == special
                for hue in (0, 15, 16):
                    cp.call('r5_native418_matrix', out, hue, work, actual)
                    expected=[]
                    for endpoint in range(3):
                        at = endpoint*96+(hue if hue<16 else 0)*6
                        a,b,c,d,e,f=value.look[selected-1].matrix[at:at+6]
                        expected.extend(v&65535 for v in (1000+a+b,-a,-b,-c,1100+c+d,-d,-e,-f,1200+e+f))
                    assert cp.read(out,54) == struct.pack('<27H',*expected)
        cp.write(root+3,b'\x01')
        assert cp.call('r5_native418_available', work, actual) == 0
        assert cp.call('r5_native418_cc1', 0x123456, work, actual) == 0x123456
        cp.write(root+3,b'\0')
    assert select(cp,0,100) == 0
    for wire, actual in ((19,54),(19,56),(20,55),(20,57)):
        cp.write(root+0x2e,bytes([wire]));cp.write(env+0x25,bytes([actual]))
        assert cp.call('r5_native418_available', work, actual) == 0
        cp.call('r5_native418_matrix', out, 7, work, actual)
        from test_integration import matrix_result
        assert struct.unpack('<27H',cp.read(out,54)) == matrix_result(images[3],actual,7,__import__('patches').matrix_bytes())


def test_all_eleven_native_gamma_consumers_preserve_registers_apsr_and_exact_continuation(images,codec):
    cp,value=CP(images[3]),decoded(codec)
    assert upload(codec,cp,value)[0].phase==4
    gates=json.loads((BASELINE/'work/gamma/getter_build423/gates.json').read_text())['records']
    assert len(gates)==11
    invalid=0x3120000
    for selected in (None,-1,0,7):
        view=0 if selected is None else invalid if selected==-1 else cp.BANK+50896+selected*24
        cp.write(0x1a39458,struct.pack('<I',view))
        for gate in gates:
            wanted=int(gate['original_pointer'],16) if selected in (None,-1) else cp.words(view+gate['custom_bank_offset'],1)[0]
            for flags in (0,0xf8000000):
                saved={n:0x12340000+n for n in range(13)}
                for n,v in saved.items():cp.cpu.reg_write(getattr(A,'UC_ARM_REG_R'+str(n)),v)
                cp.cpu.reg_write(A.UC_ARM_REG_SP,cp.STACK+0x8000)
                cp.cpu.reg_write(A.UC_ARM_REG_LR,cp.STOP|1)
                cp.cpu.reg_write(A.UC_ARM_REG_CPSR,(cp.cpu.reg_read(A.UC_ARM_REG_CPSR)&~0xf8000000)|flags)
                resume=int(gate['resume'],16)
                cp.cpu.emu_start(int(gate['site'],16)|1,resume,count=1000)
                assert cp.cpu.reg_read(A.UC_ARM_REG_PC)==resume
                assert cp.cpu.reg_read(A.UC_ARM_REG_SP)==cp.STACK+0x8000
                assert cp.cpu.reg_read(A.UC_ARM_REG_LR)==cp.STOP|1
                assert cp.cpu.reg_read(A.UC_ARM_REG_CPSR)&0xf8000000==flags
                for n,v in saved.items():
                    assert cp.cpu.reg_read(getattr(A,'UC_ARM_REG_R'+str(n)))==(wanted if n==gate['register'] else v)
