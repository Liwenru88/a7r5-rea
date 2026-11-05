"""锁定CP中参数状态/快照的候选引用；静态候选不作为实时或帧寿命证据。"""
from array import array
import struct
import sys

from .access_evidence import CP_SHA, require_source
from .investigate import CP_BASE, instructions

STATE_ADDRESSES = {
    0x157aa10: 'notification_state', 0x164eef0: 'master',
    0x1653c68: 'parameter_snapshot', 0x192b070: 'context',
    0x157c278: 'installed_context',
    0x165d820: 'other_context_candidate',
    0x165d758: 'first_operation_context',
    0x192b030: 'consumer_pending_flags',
}
CALL_TARGETS = {
    0x89853e: 'notification_getter', 0xafcb5c: 'initial_master_copy',
    0xafd2da: 'context_constructor', 0x9071cc: 'context_install',
    0x898548: 'locked_runtime_snapshot',
}


def thumb_call(h1, h2, address):
    """只识别BL/BLX立即数；结果仍必须与Capstone独立核对。"""
    if h1 & 0xf800 != 0xf000:
        return None
    branch = h2 & 0xd000 == 0xd000
    exchange = h2 & 0xd001 == 0xc000
    if not (branch or exchange):
        return None
    s, j1, j2 = (h1 >> 10) & 1, (h2 >> 13) & 1, (h2 >> 11) & 1
    immediate = (s << 24 | (1 ^ j1 ^ s) << 23 | (1 ^ j2 ^ s) << 22 |
                 (h1 & 0x3ff) << 12 | (h2 & 0x7ff) << 1)
    if s:
        immediate -= 1 << 25
    return (((address + 4) & ~3) if exchange else address + 4) + immediate


def thumb_mov(h1, h2):
    if h1 & 0xfbf0 not in (0xf240, 0xf2c0) or h2 & 0x8000:
        return None
    immediate = ((h1 & 15) << 12 | ((h1 >> 10) & 1) << 11 |
                 ((h2 >> 12) & 7) << 8 | h2 & 255)
    return ('movt' if h1 & 0x80 else 'movw', (h2 >> 8) & 15, immediate)


def collect(cp):
    require_source(cp, CP_SHA, 'CP')
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    halves = array('H', cp)
    if sys.byteorder != 'little':
        halves.byteswap()
    literal_hits, call_hits, immediate_hits = [], [], []
    immediate_counts = {name: 0 for name in STATE_ADDRESSES.values()}
    immediate_sites = {name: [] for name in STATE_ADDRESSES.values()}
    for i in range(len(halves) - 1):
        h1, h2, address = halves[i], halves[i + 1], CP_BASE + 2 * i
        target = thumb_call(h1, h2, address)
        if target in CALL_TARGETS:
            insn = next(md.disasm(cp[2*i:2*i+4], address), None)
            if insn is None or insn.mnemonic not in ('bl', 'blx') or int(insn.op_str.lstrip('#'), 0) != target:
                raise ValueError('Thumb直接调用解码与独立反汇编不一致')
            call_hits.append(dict(address=hex(address), target=hex(target), name=CALL_TARGETS[target],
                                  window=instructions(md, cp[max(0,2*i-20):2*i+24], address-20)))
        literal = None
        if h1 & 0xf800 == 0x4800:
            literal = ((address + 4) & ~3) + ((h1 & 255) << 2)
        elif h1 in (0xf8df, 0xf85f):
            literal = ((address + 4) & ~3) + (1 if h1 == 0xf8df else -1) * (h2 & 4095)
        if literal is not None and CP_BASE <= literal <= CP_BASE + len(cp) - 4:
            value = struct.unpack_from('<I', cp, literal - CP_BASE)[0]
            if value in STATE_ADDRESSES:
                literal_hits.append(dict(address=hex(address), literal=hex(literal), value=hex(value),
                                         name=STATE_ADDRESSES[value],
                                         window=instructions(md, cp[max(0,2*i-16):2*i+24], address-16)))
        top = thumb_mov(h1, h2)
        if top is not None and top[0] == 'movt':
            for previous in range(i - 2, max(-1, i - 14), -1):
                low = thumb_mov(halves[previous], halves[previous+1])
                if low is None or low[0] != 'movw' or low[1] != top[1]:
                    continue
                value = low[2] | top[2] << 16
                if value not in STATE_ADDRESSES:
                    continue
                seq = list(md.disasm(cp[2*previous:2*i+4], CP_BASE + 2*previous))
                if not seq or seq[0].mnemonic != 'movw' or seq[-1].mnemonic != 'movt' or seq[-1].address != address:
                    continue
                register = seq[0].operands[0].reg
                if (seq[-1].operands[0].reg != register or seq[0].operands[1].imm != low[2] or
                        seq[-1].operands[1].imm != top[2]):
                    raise ValueError('Thumb立即数配对与独立反汇编不一致')
                if any(register in ins.regs_access()[1] or ins.mnemonic in ('bl', 'blx') for ins in seq[1:-1]):
                    continue
                start = CP_BASE + 2 * previous
                name = STATE_ADDRESSES[value]
                immediate_counts[name] += 1
                if len(immediate_sites[name]) < 512:
                    immediate_sites[name].append(hex(start))
                # 统计全量，详细窗口每类最多32份；不为真实引用数量盲目扩容。
                if immediate_counts[name] <= 32:
                    immediate_hits.append(dict(address=hex(start), completed=hex(address), value=hex(value),
                                               name=name,
                                               window=instructions(md, cp[2*previous:2*i+68], start)))
                break
    if len(call_hits) > 256 or len(literal_hits) > 256 or len(immediate_hits) > 256:
        raise ValueError('候选引用数量超出研究预算')
    return dict(schema='a7r5-cp-update-candidates/1', cp_sha256=CP_SHA,
                call_candidates=call_hits, literal_candidates=literal_hits,
                immediate_candidates=immediate_hits,
                immediate_candidate_counts=immediate_counts, immediate_window_limit_per_category=32,
                immediate_sites=immediate_sites, immediate_site_limit_per_category=512,
                immediate_windows_truncated=sum(immediate_counts.values())>len(immediate_hits),
                candidate_only=True, linear_halfword_scan_includes_data=True,
                realtime_update_proven=False, frame_reference_release_proven=False,
                live_view_or_jpg_consumption_proven=False)
