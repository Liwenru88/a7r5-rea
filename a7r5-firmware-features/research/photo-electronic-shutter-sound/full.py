"""全功能组合仅移动声音私有页与启动助手，不改色彩运算。"""

SOUND_PAGE = 0x1a3b000
SOUND_MAPPER = 0x109100
BSS_BYTES = 0x8a4000


def prepare(work, edit):
    # 取消仅含一次尾调用的私有包装，CRC 仍由同一个已验证函数执行。
    edit('cp/cp_transfer.c', [
        ('static uint32_t message_crc(',
         'static __attribute__((always_inline)) inline uint32_t message_crc('),
    ])
    # 0x1a3a000 留给 FL2/FL3 矩阵及原生曲线，0x1a3ad80 留给逐张画幅状态。
    edit('cp/r5_sound_page.S', [
        ('[r0,#0xe8]', '[r0,#0xec]'),
        ('0x1a3a63e', '0x1a3b63e'),
        ('0x1a3a000', '0x1a3b000'),
    ])
    source = (work / 'cp/build_cp.py').read_text()
    edit('cp/build_cp.py', [
        ('SOUND=0x1a3a000', 'SOUND=0x1a3b000'),
        ('old=trampoline();loader=bytearray(old[:-12]);',
         'import arm_ops\n native_mapper=trampoline();arm_ops.TRAMP=0x109100\n old=trampoline();loader=bytearray(old[:-12]);'),
        ('0x108f40+len(loader)', '0x109100+len(loader)', source.count('0x108f40+len(loader)')),
        ('raw[0xf40:0xf40+len(loader)]', 'raw[0x1100:0x1100+len(loader)]'),
        ("patch(0xf40,loader,'4.36 mapper adds immutable sound copy and reserved runtime RX page')",
         "patch(0xf40,native_mapper,'保留原有映射助手')\n patch(0x1100,loader,'全功能独立声音映射及不可变代码复制')"),
        ("branch(0x1086d0,0x108f40,True),'Final native mapping detour'",
         "branch(0x1086d0,0x109100,True),'Final native mapping detour'"),
        ('0x01a3a63e', '0x01a3b63e'),
    ])
    # 声音页使用 BSS 末端到原生 L1 页表之间的整页对齐余量。
    # 扩大 BSS 到 0x1a3c000 会使原生页表再后移 16 KiB，必须禁止。
    edit('cp/build_cp.py', [
        ("report['sound_page_guard']=", "assert SOUND==0x1a3b000 and SOUND+4096==0x1a3c000\n report['sound_page_guard']="),
    ])
