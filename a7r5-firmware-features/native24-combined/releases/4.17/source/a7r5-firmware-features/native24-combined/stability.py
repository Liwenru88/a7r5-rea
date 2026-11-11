"""稳定性源叠加与离线布局合同；不修改冻结上游。"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def replace_exact(text, before, after, count=1):
    if text.count(before) != count:
        raise ValueError(f'替换次数不符：{before!r}，预期{count}，实际{text.count(before)}')
    return text.replace(before, after)


def overlay(work, ledger):
    pins = json.loads((HERE / 'runtime-inputs.json').read_text())
    contract = json.loads((HERE / 'layout.json').read_text())
    if contract['file_max_bytes'] != contract['file_header_bytes'] + contract['slots'] * contract['file_record_bytes']:
        raise ValueError('文件容量合同不一致')
    for source in sorted((HERE / 'runtime').iterdir()):
        if source.name == 'unified-look.c':
            continue
        folder = 'cp' if source.name == 'cp_stage413_probe.c' else 'menu_research' if source.name == 'r5_filter_page425.c' else 'import'
        target = work / folder / source.name
        before = target.read_bytes() if target.exists() else b''
        expected = pins.get(source.name)
        if (expected is None and before) or (expected is not None and digest(before) != expected):
            raise ValueError('稳定性叠加前像不符：' + source.name)
        target.write_bytes(source.read_bytes())
        ledger.append({'path': str(target.relative_to(work)), 'before_sha256': digest(before),
                       'after_sha256': digest(target.read_bytes()), 'stage': 'stability-owned-source'})
    header = '#ifndef R5_NATIVE24_CONTRACT_H\n#define R5_NATIVE24_CONTRACT_H\n'
    header += ''.join(f'#define R5_N24_{key.upper()} {value}u\n' for key, value in contract.items() if isinstance(value, int))
    header += '#endif\n'
    for folder in ('import', 'cp_include'):
        target = work / folder / 'r5_native24_contract.h'
        target.write_text(header)
        ledger.append({'path': str(target.relative_to(work)), 'before_sha256': digest(b''),
                       'after_sha256': digest(target.read_bytes()), 'stage': 'generated-contract'})
        target = work / folder / 'r5_custom_filter423.h'
        before = target.read_bytes()
        text = replace_exact(before.decode(), '#include "native_gamma.h"', '#include "native_gamma.h"\n#include "r5_native24_contract.h"', 1 if folder=='import' else 0)
        text += '\n_Static_assert(R5_FILTER423_ALLOCATION==R5_N24_CP_HEAP_BYTES,"contract allocation");\n'
        text += '_Static_assert(R5_FILTER423_VIEWS==R5_N24_VIEWS_OFFSET,"contract views");\n'
        target.write_text(text)
        ledger.append({'path': str(target.relative_to(work)), 'before_sha256': digest(before),
                       'after_sha256': digest(target.read_bytes()), 'stage': 'contract-assertions'})
    rules = {
        'import/build_ap_module.py': [('RX,RW=0x8e90000,0x8ea0000','RX,RW=0x8e90000,0x8eb0000')],
        'import/build_ap_image.py': [('module.align(rxfile+len(code),65536)','module.align(rxfile+max(len(code),module.RW-module.RX),65536)'),
            ('assert at+len(code)<=65536','assert at+len(code)<=module.RW-module.RX')],
        'menu_parent423.py': [('assert new_rx_size <= 65536','assert new_rx_size <= module_audit[\'rw\']-rx')],
        'import/r5_stage413_probe.c': [('p[1]=2;', 'p[1]=R5_N24_PROBE_VERSION;'),
            ('p[1]!=2', 'p[1]!=R5_N24_PROBE_VERSION'), ('!=0x524', '!=R5_N24_CP_BUILD'), ('!=57472u', '!=R5_N24_BANK_BYTES')],
        'import/r5_stage413_transfer_core.c': [('p[1]=4;', 'p[1]=R5_N24_TRANSFER_VERSION;'), ('p[1]!=4', 'p[1]!=R5_N24_TRANSFER_VERSION')],
        'cp/cp_transfer.c': [('p[1]=4;', 'p[1]=R5_N24_TRANSFER_VERSION;'), ('p[1]!=4', 'p[1]!=R5_N24_TRANSFER_VERSION')],
        'import/r5_filter_selection423.c': [('p[1]=2;', 'p[1]=R5_N24_SELECTION_VERSION;'), ('p[1]!=2', 'p[1]!=R5_N24_SELECTION_VERSION'),
            ('put32(p+8,3);', 'put32(p+8,R5_N24_SIDECAR_VERSION);'), ('version==3', 'version==R5_N24_SIDECAR_VERSION', 2),
            ('loaded_version=3;', 'loaded_version=R5_N24_SIDECAR_VERSION;')],
        'import/r5_filter_runtime423.c': [('loaded_format==3', 'loaded_format==R5_N24_SIDECAR_VERSION', 3),
                                        ('loaded_format<3', 'loaded_format<R5_N24_SIDECAR_VERSION')],
        'import/r5_grid420_log.c': [('!=0x524', '!=R5_N24_CP_BUILD'), ('==57472u', '==R5_N24_BANK_BYTES')],
        'cp/custom_filter423.c': [('p[1]!=2', 'p[1]!=R5_N24_SELECTION_VERSION'), ('!=57472u', '!=R5_N24_BANK_BYTES')],
        'cp/cp_stage413_probe.c': [('#define BANK_BYTES 57472u', '#define BANK_BYTES R5_N24_BANK_BYTES'),
            ('put(reply,12,0x524)', 'put(reply,12,R5_N24_CP_BUILD)'), ('p[1]==4', 'p[1]==R5_N24_TRANSFER_VERSION')],
        'cp/r5_stage413_probe.h': [('VERSION 2u', 'VERSION R5_N24_PROBE_VERSION'), ('CP_BUILD 0x524u', 'CP_BUILD R5_N24_CP_BUILD'),
                                  ('BANK_BYTES 57472u', 'BANK_BYTES R5_N24_BANK_BYTES')],
    }
    for name, replacements in rules.items():
        target = work / name
        before = target.read_bytes()
        text = before.decode()
        for old, new, *count in replacements:
            text = replace_exact(text, old, new, count[0] if count else 1)
        text = '#include "r5_native24_contract.h"\n' + text
        target.write_text(text)
        ledger.append({'path': name, 'before_sha256': digest(before), 'after_sha256': digest(target.read_bytes()),
                       'stage': 'generated-protocol-contract'})
    (work / 'derive-ledger.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n')
    return contract


def unified(baseline):
    expected = json.loads((HERE / 'runtime-inputs.json').read_text())['unified-look.c']
    if digest(baseline.encode()) != expected:
        raise ValueError('稳定性统一入口前像不符')
    return (HERE / 'runtime/unified-look.c').read_text()
