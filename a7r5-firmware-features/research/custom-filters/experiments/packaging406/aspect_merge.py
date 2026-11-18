"""严格组合固定4.06的照片标记与滤镜启动窗口；不执行目标或访问设备。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'a7r5-dat-tool').is_dir())
AP_SHA = 'd15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9'
START, END, COMBINED_END = 0x500fc10, 0x500fc70, 0x500ff8c
SOURCE_SHA256 = {
    'a7r5-firmware-features/aspect-guide406/patch-plan.json': 'c063df73ed7370091e05b13438401b117d29357b383afbf91e952d333783fb30',
    'a7r5-firmware-features/aspect-guide406-update/ap_patch.py': 'd01551981ebb7b546ebb8b73d3700252a20a85734b047aa7271414984cb7a9c7',
    'a7r5-firmware-features/aspect-guide406/tools/inspect_ap.py': 'a3bc8497e75685deafda1659004707aa62b17144b495f6dde97a87dabe510030',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def source_pins():
    for name, wanted in SOURCE_SHA256.items():
        path = ROOT/name
        require(not any(p.is_symlink() for p in (path, *path.parents)), '标记来源不能是链接')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == wanted, '标记来源发生变化：'+name)
    return dict(SOURCE_SHA256)


def aspect_contract():
    """从固定摘要的原计划独立生成35个标记窗口，不调用补丁生成器。"""
    source_pins()
    plan = json.loads((ROOT/'a7r5-firmware-features/aspect-guide406/patch-plan.json').read_text())
    require(plan['baseline']['AP_sha256'] == AP_SHA and len(plan['support_writes']) == 28 and
            len(plan['registrations']) == 3, '标记固定计划不完整')
    rows, block = [], bytearray(END-START)
    def row(at, before, after):
        rows.append(dict(offset=at, before=before.hex(), after=after.hex()))
    for i, registration in enumerate(plan['registrations']):
        entry = START + 32*i
        delta = 0x29051dc-(entry+4)
        code = struct.pack('<II', 0x10000041, 0x14000000 | ((delta//4) & 0x3ffffff))
        payload = code + struct.pack('<iii', *registration['range'])
        block[32*i:32*i+len(payload)] = payload
        row(registration['file_offset'], struct.pack('<Q', 0x2905250), struct.pack('<Q', entry))
        row(registration['existing_validator_relocation']['entry_file_offset']+16,
            struct.pack('<Q', 0x2905250), struct.pack('<Q', entry))
    row(START, bytes(END-START), bytes(block))
    for item in plan['support_writes']:
        row(item['file_offset'], bytes.fromhex(item['before_hex']), bytes.fromhex(item['after_hex']))
    source_pins()
    return sorted(rows, key=lambda r: r['offset'])


def aspect_metadata():
    rows = aspect_contract()
    return dict(schema='a7r5-406-aspect-merge/1', source_sha256=source_pins(),
                source_ap_sha256=AP_SHA, aspect_patch_windows=35, combined_patch_windows=42,
                support_writes=28, registrations=3, reserved_file_range=[START, END],
                combined_rx_end=COMBINED_END,
                aspect_contract_sha256=hashlib.sha256(canonical(rows).encode()).hexdigest(),
                photo_overlay_verified=False, device_tested=False, camera_io=False,
                hardware_simulation=False, target_executed=False)


def bootstrap_contract():
    """启动代码由其编译回执核身份；此处同时严格限制七个窗口和其固定字段。"""
    return {
        0x500fc70: (bytes(396), None),
        0x17feac0: (bytes.fromhex('fd7bbaa9'), bytes.fromhex('6c44e014')),
        0x500fdfc: (bytes(400), None),
        0x5010388: (struct.pack('<Q', 0x16fbfc0), struct.pack('<Q', 0x500fdfc)),
        0x10c68: (struct.pack('<Q', 0x16fbfc0), struct.pack('<Q', 0x500fdfc)),
        0x60: (struct.pack('<Q', START), struct.pack('<Q', COMBINED_END)),
        0x68: (struct.pack('<Q', START), struct.pack('<Q', COMBINED_END)),
    }


def _validate(patches, expected):
    require(type(patches) is list and len(patches) == len(expected), '合并窗口数量不符')
    seen, spans = set(), []
    for item in patches:
        at = item.get('offset')
        require(type(at) is int and at in expected and at not in seen, '合并窗口越界或重复')
        seen.add(at)
        before, after = expected[at]
        wanted = item.get('after')
        require(item.get('before') == before.hex() and type(wanted) is str and
                re.fullmatch('[0-9a-f]{'+str(2*len(before))+'}', wanted) is not None and
                (after is None or wanted == after.hex()), '合并窗口前后像或长度不符')
        require('bytes' not in item or (type(item['bytes']) is int and item['bytes'] == len(before)),
                '合并窗口bytes不符')
        require(all(at+len(before) <= a or b <= at for a, b in spans), '合并窗口重叠')
        spans.append((at, at+len(before)))


def validate_plan(patches, metadata):
    # 规范JSON比较区分False和0，禁止元数据把未执行伪装为已通过。
    require(canonical(metadata) == canonical(aspect_metadata()), '标记合并元数据不符')
    fixed = bootstrap_contract()
    for item in aspect_contract():
        at = item['offset']
        require(at not in fixed, '标记与启动窗口冲突')
        fixed[at] = (bytes.fromhex(item['before']), bytes.fromhex(item['after']))
    _validate(patches, fixed)
    return True


def compose_plan(raw, bootstrap_patches):
    """以原AP生成并交叉核验标记窗口，只舍弃两个较短的RX长度写入。"""
    _validate(bootstrap_patches, bootstrap_contract())
    require(hashlib.sha256(raw).hexdigest() == AP_SHA and len(raw) == 97368304,
            '合并需要固定原4.06 AP')
    source_pins()
    path = ROOT/'a7r5-firmware-features/aspect-guide406-update/ap_patch.py'
    spec = importlib.util.spec_from_file_location('aspect_merge_fixed_builder', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, receipt = module.build(raw)
    require(len(receipt['patches']) == 37, '标记生成器窗口数变化')
    aspect = [{k: r[k] for k in ('offset', 'before', 'after')} for r in receipt['patches'] if r['offset'] not in (0x60, 0x68)]
    require(canonical(sorted(aspect, key=lambda r:r['offset'])) == canonical(aspect_contract()),
            '标记生成器与独立契约不一致')
    rows = sorted([*bootstrap_patches, *aspect], key=lambda r:r['offset'])
    meta = aspect_metadata()
    validate_plan(rows, meta)
    for item in rows:
        at, before = item['offset'], bytes.fromhex(item['before'])
        require(raw[at:at+len(before)] == before, '合并AP前像不符')
    source_pins()
    return rows, meta
