"""冻结当前双启动入口的未签名USR准备清单；不生成DAT或访问签名材料。"""
from pathlib import Path
import argparse
import json
import os

from candidate_preflight import AP_SHA, require, recipe_pairing
from stage_unsigned_usr import ROOT, USR_SHA, checked_file, digest, regular, validate_manifest
from aspect_merge import validate_plan

USR = ROOT/'a7r5-firmware-features/aspect-guide406-update/build/aspect407-20261026-01/work/archive/0700_part_image/dev/nflasha15'


def entry(path, target=None):
    path = regular(path)
    result = dict(path=str(path), bytes=path.stat().st_size, sha256=digest(path))
    if target is not None:
        result['target'] = target
    return result


def freeze(preflight, software, loader, output):
    paths = [regular(p) for p in (preflight, software, loader)]
    # 摘要和JSON解析消费相同字节，随后复核来源与所有组件。
    raw = [p.read_bytes() for p in paths]
    import hashlib
    pins = [hashlib.sha256(data).hexdigest() for data in raw]
    p, s, b = [json.loads(data) for data in raw]
    markers=p['bootstrap']['includes_aspect_changes']
    require(type(markers) is bool and b.get('includes_aspect_changes',False) is markers and
            b['ap_candidate_sha256']==p['bootstrap']['memory_only_candidate_ap_sha256'],
            '照片标记选项或启动校验AP身份未配对')
    if markers:
        validate_plan(p['bootstrap']['file_patch_plan'],p['bootstrap'].get('aspect_merge'))
    recipe_enabled=recipe_pairing(p,s,b)
    startup_bound=b.get('runtime_startup_source_bound',False)
    require(type(startup_bound) is bool and (not startup_bound or recipe_enabled),
            '启动源码与配对构建不符')
    require(p['status'] == 'PASS_STATIC_BINDING_AND_COMPOSITE_PLAN_ONLY' and
            s['status'] == 'PASS_SOFTWARE_BUILD_AND_HOST_CONTRACTS' and
            b['status'] == 'PASS_BOOTSTRAP_LINK_ONLY_NOT_EXECUTED', '构建回执状态不符')
    require(p['source_ap_sha256'] == AP_SHA and p['source_unchanged'] is True and
            s.get('source_unchanged', True) and b['source_unchanged'] is True and
            len(p['bootstrap']['file_patch_plan']) == (42 if markers else 7), '源码或双入口计划不符')
    for report in (p, s, b):
        for name, pin in report['source_sha256'].items():
            require(digest(ROOT/name) == pin, '构建来源已变化：'+name)
    dsos = [entry(ROOT/b['bootstrap']['path'], '/lib/libaf_bootstrap406.so'),
            entry(p['ui_input']['path'], '/lib/libaf_ui406.so'),
            entry(ROOT/p['module']['path'], '/lib/libaf_requests406.so'),
            entry(paths[1].parent/'libaf_repository_media.so', '/lib/libaf_repository_media.so')]
    require(dsos[0]['sha256'] == b['bootstrap']['sha256'] and
            dsos[1]['sha256'] == b['ui']['sha256'] == p['ui_input']['sha256'] == s['artifacts']['dynamic/ap-ui.elf']['sha256'] and
            dsos[2]['sha256'] == b['requests']['sha256'] == p['module']['sha256'] and
            dsos[3]['sha256'] == b['repository']['sha256'] == s['artifacts']['libaf_repository_media.so']['sha256'], '模块构建身份不符')
    assets = []
    for asset in b['assets']:
        if asset['path'] == '/usr/lib/libObj.so':
            continue
        target = asset['path'].removeprefix('/usr')
        row = entry(paths[2].parent/'components'/asset['path'].lstrip('/'), target)
        require(row['sha256'] == asset['sha256'] and row['bytes'] == asset['bytes'], '资源产物变化')
        row.update(source_member=target, source_sha256=asset['source_sha256'])
        assets.append(row)
    result = dict(schema='a7r5-406-unsigned-staging-input/'+('3' if markers else '2'), status='FROZEN_PREPARE_ONLY_DEFAULT_CLOSED',
        source_usr=dict(path=str(USR), sha256=USR_SHA), dsos=dsos, resource_replacements=assets,
        ap=dict(source_sha256=AP_SHA, target_sha256=p['bootstrap']['memory_only_candidate_ap_sha256'],
                patches=p['bootstrap']['file_patch_plan'], includes_aspect_changes=markers, receipt=entry(paths[0])),
        build=entry(paths[2]), software=entry(paths[1]),
        installable_firmware=False, CP_gates_installed=False, UI_gates_installed=False)
    result['recipe_bridge_enabled']=recipe_enabled
    if markers:
        result['ap']['aspect_merge']=p['bootstrap']['aspect_merge']
    # 以上installed字段限定准备镜像的文件窗口，不声称后续启动没有驻留分流。
    result['runtime_passthrough_hooks_source_bound']=startup_bound
    result['runtime_UI_requires_verified_peer']=True
    result['target_executed']=False
    validate_manifest(result)
    for row in [*dsos, *assets]:
        checked_file(row)
    require(all(digest(path) == pin for path, pin in zip(paths, pins)), '冻结期间回执发生变化')
    output = output.resolve()
    require(output.is_relative_to(ROOT/'.local/fixed-custom-filters') and not output.exists(), '输出须为本任务全新清单')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        stream.flush()
        os.fsync(stream.fileno())
    return dict(path=str(output), sha256=digest(output), app_patch_windows=len(p['bootstrap']['file_patch_plan']),
                resource_replacements=len(assets), added_dsos=len(dsos), installable_firmware=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('preflight', 'software', 'loader', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.preflight, args.software, args.loader, args.output), ensure_ascii=False, indent=2))
