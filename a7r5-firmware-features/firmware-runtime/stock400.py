"""在构建副本中将二十四槽运行时绑定到 ILCE-7RM5 原厂 4.00。"""
import hashlib
import json
from pathlib import Path
import shutil

from stability import replace_exact

DAT_SHA = '51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2'
AP_SHA = '41bd8f4cda1f44c7038912837737e1ce6a650065f2108061ada30e5c7f9ce7c7'
CP_SHA = '3269bf62426339791fcfbe8529698cd4accbe6c3d2ea61cd7c368a90ab7ee7c8'
UPSTREAM_AP = 'a8d5cd444bf08a03a70aedc3cc32bdd857b89b468ac10bf8365d640e8d390d75'
UPSTREAM_CP = '8e9e26bf2e4b93fa5142e961dcf21cb0f43f8871283814be2dcfb0a694cb5a32'
TABLE_VA = 0x110cfa8
ROUTE_VA = 0xdcc67c
TABLE_ROWS = 47
USR = Path('archive/0700_part_image/dev/nflasha15')


def prepare(work, stock, changes, *, fl23=False):
    if json.loads((stock / 'manifest.json').read_text())['source']['sha256'] != DAT_SHA:
        raise ValueError('需要从 ILCE-7RM5 原厂 4.00 DAT 解包得到的工作区')
    for relative, name, digest in [('usr/lib/appFw.so', 'ap_baseline.so', AP_SHA),
                                   ('cpapp-b.bin', 'cp_baseline.bin', CP_SHA)]:
        source = stock / 'components' / relative
        with source.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('原厂 4.00 组件摘要不符 ' + relative)
        shutil.copyfile(source, work / 'inputs' / name)

    if fl23:
        recipes = json.loads((work / 'dependencies/baseline_recipes.json').read_text())
        for key, filename, target in [('ap_baseline', 'ap_baseline.so', UPSTREAM_AP),
                                      ('cp_baseline', 'cp_baseline.bin', UPSTREAM_CP)]:
            path = work / 'inputs' / filename
            image = bytearray(path.read_bytes())
            for row in recipes[key]['patches']:
                offset = row['offset']
                before, after = (bytes.fromhex(row[k]) for k in ('before', 'after'))
                if len(before) != len(after) or image[offset:offset + len(before)] != before:
                    raise ValueError('FL2／FL3 派生基底前像不符')
                image[offset:offset + len(after)] = after
            if hashlib.sha256(image).hexdigest() != target:
                raise ValueError('FL2／FL3 派生基底摘要不符')
            path.write_bytes(image)
        return

    def edit(name, pairs):
        path = work / name
        before = path.read_bytes()
        source = before.decode()
        for old, new, count in pairs:
            source = replace_exact(source, old, new, count)
        after = source.encode()
        path.write_bytes(after)
        changes.append({'path': name, 'layer': 'stock400',
                        'before_sha256': hashlib.sha256(before).hexdigest(),
                        'after_sha256': hashlib.sha256(after).hexdigest()})

    edit('import/build_ap_image.py', [(UPSTREAM_AP, AP_SHA, 1)])
    edit('cp/build_cp.py', [(UPSTREAM_CP, CP_SHA, 1)])
    edit('gamma/getter_gates.py', [(UPSTREAM_CP, CP_SHA, 1), ('0x107e968', hex(TABLE_VA), 1),
        ('0x107eefc', hex(ROUTE_VA), 1), ("'3328'", "'2f28'", 2),
        ('for index,(_,at,r) in enumerate(refs):', 'for index,(low_at,at,r) in enumerate(refs):\n'
         '            if label != "normal_route":\n'
         '                assert cp[low_at:low_at+4]==mov16(r,original&0xffff)', 1)])
    # 原厂 47 行。新代际的整个堆块由 CP 清零，47～50 保留为零。
    # 自定义仍使用 51～74 ID，避免改变 AP／CP 协议和延迟请求。
    edit('cp/native_color.c', [('0x107e968u', f'{TABLE_VA:#x}u', 1),
        ('0x107eefcu', f'{ROUTE_VA:#x}u', 2),
        ('for(n=0;n<51;n++)', f'for(n=0;n<{TABLE_ROWS};n++)', 1)])
    edit('gamma/native_gamma.c', [('0x107e968u', f'{TABLE_VA:#x}u', 2),
        ('0x107efacu', f'{TABLE_VA + TABLE_ROWS * 28:#x}u', 1),
        ('0x107eefcu', f'{ROUTE_VA:#x}u', 1),
        ('cp(g->table,table,51*7*4);', f'cp(g->table,table,{TABLE_ROWS}*7*4);', 1)])
