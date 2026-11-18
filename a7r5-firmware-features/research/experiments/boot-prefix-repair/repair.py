"""固定 4.19 包的 CP 引导前缀实验；不含设备访问入口。"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
CP_SHA = '745c63742b525f8700142ad310b6f3ec848015aec60044bc19b69cc458d6c441'
DAT_SHA = 'd486853533711a282c5e0794f6e98931608c1d2c581e3b25cd70da8b48ce5503'
BASE, CALL, OLD, NEW, SIZE = 0x108000, 0x1086d0, 0xbef7c0, 0x109200, 0x50


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def arm_branch(address, target, opcode=0xeb000000):
    delta = target - address - 8
    if delta & 3 or not -(1 << 25) <= delta < (1 << 25):
        raise ValueError('ARM 分支范围无效')
    return struct.pack('<I', opcode | ((delta // 4) & 0xffffff))


def repair_cp(raw):
    if sha(raw) != CP_SHA:
        raise ValueError('仅接受固定 4.19 CP 完整前像')
    helper = raw[OLD - BASE:OLD - BASE + SIZE]
    if sha(helper) != 'eb2d8194a86be065ef1eb48745ec4ef4d7554ff36bfcbad1a3563bf59e2448b1':
        raise ValueError('启动助手前像不符')
    if any(raw[NEW - BASE:NEW - BASE + SIZE]):
        raise ValueError('引导前缀目标窗口已占用')
    if raw[CALL - BASE:CALL - BASE + 4] != arm_branch(CALL, OLD):
        raise ValueError('启动调用前像不符')
    relocated = bytearray(helper)
    # 外部 BL 重新编码；内部循环的相对分支、全部其它指令逐字保留。
    for offset in (4, 0x24):
        word, = struct.unpack_from('<I', helper, offset)
        if word >> 24 != 0xeb:
            raise ValueError('助手外部调用前像不符')
        immediate = word & 0xffffff
        if immediate & 0x800000:
            immediate -= 1 << 24
        target = OLD + offset + 8 + immediate * 4
        if target != (0x109000 if offset == 4 else 0x108768):
            raise ValueError('助手映射器目标不符')
        relocated[offset:offset + 4] = arm_branch(NEW + offset, target)
    result = bytearray(raw)
    result[NEW - BASE:NEW - BASE + SIZE] = relocated
    result[CALL - BASE:CALL - BASE + 4] = arm_branch(CALL, NEW)
    return bytes(result)


def build(source, output):
    sys.path.insert(0, str(ROOT / 'a7r5-dat-tool'))
    from a7r5dat import tool
    source = tool.regular(source)
    output = Path(output).absolute()
    if (not output.resolve().is_relative_to(ROOT / '.local') or output.exists()
            or any(p.is_symlink() for p in (output, *output.parents))):
        raise ValueError('输出必须是项目 .local 内的全新目录，且路径无符号链接')
    source_facts = tool.file_facts(source)
    if source_facts['sha256'] != DAT_SHA:
        raise ValueError('升级包完整前像不符')
    output.mkdir(parents=True, mode=0o700)
    public = ROOT / 'a7r5-dat-tool/keys/research-public.pem'
    work = output / 'work'
    tool.unpack(source, work, public)
    cp = work / 'components/cpapp-b.bin'
    before = cp.read_bytes()
    candidate = repair_cp(before)
    cp.write_bytes(candidate)
    destination = output / 'BODYDATA.CP-PREFIX-EXPERIMENTAL.DAT'
    # 保持包头 4.19，避免把版本号变化混入启动对照；没有改变版本准入。
    receipt = tool.pack(work, destination)
    allowed = {'0700_part_image/dev/nflasha8', '0701_part_image_sum/part_image.sum'}
    if set(receipt['changed_archive_members']) != allowed or receipt['changed_components'] != ['/cpapp-b.bin']:
        raise ValueError('打包变化超出 CP 及关联校验清单')
    readback = output / 'readback'
    tool.unpack(destination, readback, public)
    old = json.loads((work / 'manifest.json').read_text())
    new = json.loads((readback / 'manifest.json').read_text())
    if (old['header'] != new['header'] or old['header_sha256'] != new['header_sha256']
            or old['updater_sha256'] != new['updater_sha256']):
        raise ValueError('包头或更新器出现非预期变化')
    if len(old['entries']) != len(new['entries']):
        raise ValueError('归档条目数量变化')
    for left, right in zip(old['entries'], new['entries']):
        fields = ('name', 'type', 'size', 'prefix', 'link')
        if any(left.get(k) != right.get(k) for k in fields):
            raise ValueError('归档顺序或元数据变化')
        if left['name'] not in allowed and left != right:
            raise ValueError('非 CP 归档载荷变化：' + left['name'])
    if (readback / 'components/cpapp-b.bin').read_bytes() != candidate:
        raise ValueError('最终 CP 独立解包内容不符')
    if tool.file_facts(source) != source_facts:
        raise ValueError('源包在处理期间发生变化')
    report = {
        'status': 'OFFLINE_EXPERIMENT_VERIFIED_DEVICE_UNTESTED',
        'source': source_facts, 'candidate': tool.file_facts(destination),
        'version': '4.19', 'camera_io': False, 'device_boot_verified': False,
        'root_cause_proven': False, 'NOR_failure_masking_fixed': False,
        'hypothesis': '将 MMU 启用前的画幅助手放回引导前缀，减少对后续代码装载时序的依赖；尚未证明这是此次实机故障原因。',
        'helper_before': hex(OLD), 'helper_after': hex(NEW), 'helper_bytes': SIZE,
        'original_helper_preserved': True,
        'CP_before_sha256': sha(before), 'CP_after_sha256': sha(candidate),
        'CP_changed_bytes': sum(a != b for a, b in zip(before, candidate)),
        'changed_archive_members': receipt['changed_archive_members'],
        'unchanged': ['AP', 'AVCAM', 'MPR', 'WBI', '资源与默认参数', '更新器', '版本号'],
        'independent_unpack_verified': True, 'archive_entries': len(new['entries']),
        'builder_sha256': sha(Path(__file__).read_bytes()),
        'warning': '实验候选；离线回放不等于完整 NOR 冷启动或机身启动验收。',
    }
    tool.save(output / 'verification.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dat', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source_dat, args.output), ensure_ascii=False, indent=2))
