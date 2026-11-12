"""本地多库堆／消息夹具；不修改冻结上游的历史测试。"""
import struct

from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A


def receiver_services(cp, budget=1048576):
    if budget < 0 or budget > 16 * 947000:
        raise ValueError('CP 回放堆预算越界')
    capacity = (max(1, budget) + 4095) & ~4095
    cp.cpu.mem_map(0x4000000, capacity)
    cp.heap_used = 0
    cp.heap_allocations = []
    cp.native_acks = []
    cp.packet_size = cp.tx_size = cp.frees = 0
    cp.send_failure = False

    def service(cpu, at, size, context):
        result = 0
        if at == 0x5ef69c:
            length = cpu.reg_read(A.UC_ARM_REG_R0)
            start = (cp.heap_used + 7) & ~7
            if not length or start + length > budget:
                result = 0
            else:
                result = 0x4000000 + start
                cp.heap_allocations.append(length)
                cp.heap_used = start + length
        elif at == 0xbaad0c:
            result = cp.packet_size
        elif at == 0x53c220:
            cp.tx_size = cpu.reg_read(A.UC_ARM_REG_R2)
            cp.write(cpu.reg_read(A.UC_ARM_REG_R1), struct.pack('<I', 0x3105000))
        elif at == 0x53bb54:
            cp.native_acks.append(cp.read(cpu.reg_read(A.UC_ARM_REG_R1), cp.tx_size))
            result = int(cp.send_failure)
        elif at == 0x53c31c:
            cp.frees += 1
        elif at != 0xbaaaa0:
            return
        cpu.reg_write(A.UC_ARM_REG_R0, result)
        cpu.reg_write(A.UC_ARM_REG_PC, cpu.reg_read(A.UC_ARM_REG_LR))

    cp.cpu.hook_add(UC_HOOK_CODE, service)
