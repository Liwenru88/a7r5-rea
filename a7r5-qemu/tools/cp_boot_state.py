"""暂停后只读导出原厂 CP 任务/队列现场；不修改寄存器或客体内存。"""
import json
import re

from runtime_manifest import digest

# 仅固定低地址 RAM；禁止把副作用寄存器或任意主机路径当作导出参数。
REGIONS = ((0x1100000, 0x400000, 'cp-runtime-01100000.bin'),
           (0x1500000, 0x500000, 'cp-runtime-01500000.bin'),
           (0x2d00000, 0x40000, 'cp-runtime-02d00000.bin'))


def export_boot_state(vm, command, cpu_count):
    if cpu_count not in (1, 4):
        raise ValueError('CP 核数不符')
    targets = [vm.out/name for _, _, name in REGIONS]
    receipt = vm.out/'cp-boot-state.json'
    if any(path.exists() or path.is_symlink() for path in (*targets, receipt)):
        raise ValueError('拒绝覆盖 CP 启动现场')
    if command(vm, {'execute': 'query-status'})['status'] != 'paused':
        raise ValueError('CP 必须暂停后才能导出一致现场')
    registers = []
    for cpu in range(cpu_count):
        # QMP 每次创建独立 HMP 上下文，前一次 cpu 命令不会保留选择。
        text = command(vm, {'execute': 'human-monitor-command',
                            'arguments': {'command-line': 'info registers', 'cpu-index': cpu}})
        if not re.search(rf'CPU#{cpu}\b', text):
            raise ValueError('CP 寄存器导出核号不符')
        registers.append(text)
    rows = []
    for (address, size, name), target in zip(REGIONS, targets):
        command(vm, {'execute': 'pmemsave', 'arguments': {'val': address, 'size': size, 'filename': str(target)}})
        if target.is_symlink() or target.stat().st_size != size:
            raise ValueError('CP 启动现场导出长度不符')
        rows.append({'address': address, 'bytes': size, 'file': name, 'sha256': digest(target)})
    # 只读定时器控制/比较/计数。不从主机读取银行化 GIC：标准模型需要 current_cpu，
    # QMP 主线程没有此上下文，会在 gic_get_current_cpu 中崩溃；不改为伪造 CPU 上下文。
    mmio = {}
    for name, address, words in [('timers'+str(n), 0xf1042000+n*0x1000, 5) for n in range(9)]:
        mmio[name] = command(vm, {'execute': 'human-monitor-command',
                                'arguments': {'command-line': f'xp /{words}wx {address:#x}'}})
    result = {'regions': rows, 'cpu_registers': registers, 'mmio': mmio,
              'snapshot_only': True, 'guest_memory_writes': 0, 'CP_service_ready_proven': False}
    with receipt.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return result
