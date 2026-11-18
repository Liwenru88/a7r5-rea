"""组合当前AP/USR与CP候选，正常研究签名并独立回读；没有设备或模拟入口。"""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import struct
import sys
import zlib

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'a7r5-dat-tool/a7r5dat').is_dir())
sys.path.insert(0, str(ROOT/'a7r5-dat-tool'))
from a7r5dat import tool
from a7r5dat.ext2_patch import reader
from stage_cp import CP_SHA, IMAGE_SHA, independent_cp
from aspect_merge import validate_plan, source_pins

DAT_SHA = '3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2'
# 来自本任务对上述原DAT正常验签／完整解包的确定性清单，拒绝工作区自报身份。
SOURCE_MANIFEST_SHA = 'd53d7cd416a3e418a2f19f71b44e6ec39c11e5e70455d861ffbad9c61615a651'
USR_SHA = 'f7a23ecdc4d4848a2b4a33398313d8def642bc4a2e9e007c42fb1fa1b48097bf'
AP_SHA = 'd15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9'
SUM = '0701_part_image_sum/part_image.sum'
ALLOWED = {tool.AP_IMAGE, tool.CP_IMAGE, SUM}
# 4.12由用户明确要求，仅用于同载荷版本封装，不代表integration58入口故障已修复。
RESEARCH_VERSIONS = {False: ('4.08',), True: ('4.09', '4.10', '4.12')}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def regular(path):
    p = Path(path).absolute()
    require('..' not in p.parts and not any(a.is_symlink() for a in (p, *p.parents)), '拒绝非规范或链接路径')
    require(not any(p.is_relative_to(a) for a in map(Path, ('/dev', '/Volumes', '/proc', '/sys'))), '拒绝设备和外部介质路径')
    require(p.is_file(), '缺少普通文件：'+str(p))
    return p


def digest(path):
    with regular(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def frozen_json(path):
    p = regular(path)
    raw = p.read_bytes()
    return json.loads(raw), dict(path=str(p), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def check_entry(row):
    p = regular(row['path'])
    require(p.stat().st_size == row['bytes'] and digest(p) == row['sha256'], '冻结组件已变化：'+str(p))
    return p


def check_sources(report):
    sources = report.get('source_sha256')
    require(isinstance(sources, dict) and sources, '缺少非空构建来源')
    for name, expected in sources.items():
        p = Path(name)
        require(digest(p if p.is_absolute() else ROOT/p) == expected, '构建来源已变化：'+name)


def check_native_contract(report):
    # full_recipe_negotiable/installed描述未运行的回执，不是必须伪造为true的发布开关。
    require(report.get('native_integration') is True and report.get('native_consumer_bound') is True and
            report.get('native_consumers_source_bound') is True and report.get('native_asset_schema') == 3 and
            report.get('module_symbols', {}).get('af_cp_components406_matrix9_target', 0) > 0,
            '需要当前完整原生消费者和单色矩阵入口')
    require(all(report.get(name) is False for name in ('target_executed', 'hardware_simulation', 'camera_io')),
            '本构建仅接受未执行目标／设备的离线来源')


def check_usr_scope(manifest, version):
    """组合包必须显式选择新schema与版本，旧滤镜包的范围保持不变。"""
    markers=manifest['ap'].get('includes_aspect_changes')
    require(type(markers) is bool, '缺少明确照片标记范围')
    # 4.10用于资源／启动修复后的独立研究候选；不复用已发生现场故障的4.09标记。
    versions=RESEARCH_VERSIONS[markers]
    require(manifest['schema'] == 'a7r5-406-unsigned-staging-input/'+('3' if markers else '2') and
            version in versions, '清单／标记范围与研究版本不配对')
    if markers:
        validate_plan(manifest['ap']['patches'],manifest['ap'].get('aspect_merge'))
    return markers


def reverse_cp(source, candidate, plan):
    """独立核对精确补丁集合；不调用构建器或执行目标。"""
    require(hashlib.sha256(source).hexdigest() == CP_SHA and len(source) == len(candidate), 'CP原像或长度错误')
    require(plan['source_sha256'] == CP_SHA and plan['candidate_sha256'] == hashlib.sha256(candidate).hexdigest(), 'CP计划身份不符')
    expected, reverse, ranges = bytearray(source), bytearray(candidate), []
    for row in plan['patches']:
        at = row['offset']
        before, after = bytes.fromhex(row['before']), bytes.fromhex(row['after'])
        require(type(at) is int and 0 <= at < at+len(before) <= len(source) and
                len(before) == len(after) == row['bytes'], 'CP补丁范围错误')
        require(all(at+len(before) <= a or b <= at for a, b in ranges), 'CP补丁重叠')
        require(source[at:at+len(before)] == before and candidate[at:at+len(after)] == after, 'CP补丁前后像错误')
        ranges.append((at, at+len(before)))
        expected[at:at+len(after)] = after
        reverse[at:at+len(before)] = before
    require(bytes(expected) == candidate and bytes(reverse) == source, 'CP有计划外改动或不能精确逆还原')


def verify_archive(before, after, usr_sha, fat_sha):
    """外层重解包后独立检查成员集合、全部布局元数据和非目标内容。"""
    old, new = before['entries'], after['entries']
    require([r['name'] for r in old] == [r['name'] for r in new], '归档成员集合或顺序变化')
    changes = []
    for a, b in zip(old, new):
        require(a.keys() == b.keys(), '归档清单字段变化')
        require(all(a[k] == b[k] for k in a if k not in ('sha256', 'crc32')), '归档长度、身份或布局变化：'+a['name'])
        if a != b:
            require(a['name'] in ALLOWED, '非目标归档成员变化：'+a['name'])
            changes.append(a['name'])
    require(set(changes) == ALLOWED, '缺少预期CP／USR／校验清单改动')
    entries = {r['name']: r for r in new}
    require(entries[tool.AP_IMAGE]['sha256'] == usr_sha and entries[tool.CP_IMAGE]['sha256'] == fat_sha, '分区回读摘要不符')
    require(after['updater_sha256'] == before['updater_sha256'] and after['outer'] == before['outer'] and
            after['iv'] == before['iv'] and after['tail'] == before['tail'] and
            after['decryption']['plaintext_bytes'] == before['decryption']['plaintext_bytes'],
            '更新器、外层身份、IV、归档尾或明文长度变化')
    require(before['components'].keys() == after['components'].keys(), '原组件集合变化')
    for name, row in before['components'].items():
        if name == 'cpapp-b.bin' or name.startswith('usr/'):
            continue
        require(after['components'][name] == row, '非目标内部组件变化：'+name)
    return changes


def expected_usr(manifest):
    rows = {r['target']: r for r in [*manifest['dsos'], *manifest['resource_replacements']]}
    require(len(rows) == 74 and len(manifest['dsos']) == 4 and len(manifest['resource_replacements']) == 70, 'USR组件集合错误')
    require({r['target'] for r in manifest['dsos']} == {'/lib/libaf_bootstrap406.so', '/lib/libaf_ui406.so',
            '/lib/libaf_requests406.so', '/lib/libaf_repository_media.so'}, 'USR模块路径越界')
    icons = {'/share/app/image_00_23_IPSX.uxc', '/share/app/image_00_32_IPSX.uxc'}
    names = {r['target'] for r in manifest['resource_replacements']}
    require(icons <= names and all(p in icons or re.fullmatch(r'/share/app/string_[a-z]+_(horizontal|vertical)\.uxc', p)
                                  for p in names), 'USR资源路径越界')
    rows['/lib/appFw.so'] = dict(bytes=97368304, sha256=manifest['ap']['target_sha256'])
    return rows


def verify_usr(image, expected):
    fs = reader(regular(image).read_bytes())
    result = {}
    for name, row in expected.items():
        raw = fs.read_inode(fs.walk(name))
        require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], 'USR最终组件不符：'+name)
        result[name] = dict(bytes=len(raw), sha256=row['sha256'])
    return result


def verify_format(source, final, version):
    old_header = (source/'format/header.bin').read_bytes()
    header = bytearray(old_header)
    major, minor = version.split('.')
    header[33], header[32] = int(major, 16), int(minor, 16)
    struct.pack_into('<I', header, 8, zlib.crc32(header[12:]))
    require((final/'format/header.bin').read_bytes() == header, '头版本／CRC以外的格式变化')
    require((final/'format/updater.bin').read_bytes() == (source/'format/updater.bin').read_bytes(), '原更新器内容变化')


def write_json(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_package(candidate, output, result):
    """只发布已完成内容验证的私有候选；链接失败不发布成功回执。"""
    target = output/'BODYDATA.DAT'
    require(not any((output/n).exists() for n in ('BODYDATA.DAT', 'verification.json', 'COMPLETED.json')), '发布目标已存在')
    require(digest(candidate) == result['sha256'], '发布前DAT发生变化')
    pending = output/'CONTENT_VERIFIED.pending.json'
    write_json(pending, result)
    with regular(candidate).open('rb') as stream:
        os.fsync(stream.fileno())
    os.link(candidate, target)
    target.chmod(0o600)
    require(digest(target) == result['sha256'], '发布文件摘要不符')
    sync_directory(output)
    os.link(pending, output/'verification.json')
    with (output/'BODYDATA.DAT.sha256').open('x') as stream:
        stream.write(result['sha256']+'  BODYDATA.DAT\n')
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(output)
    write_json(output/'COMPLETED.json', dict(status=result['status'], output=str(target), sha256=result['sha256']))
    sync_directory(output)


def build(source_dat, source_workspace, usr_manifest, usr_receipt, cp_receipt, output, version='4.08'):
    require(version in RESEARCH_VERSIONS[False]+RESEARCH_VERSIONS[True],
            '研究版本必须与已批准的范围表匹配')
    source_dat = regular(source_dat)
    require(digest(source_dat) == DAT_SHA, '原DAT不是固定修改版4.06')
    packaging_paths = [Path(__file__), Path(__file__).with_name('stage_cp.py'),
                       Path(__file__).with_name('aspect_merge.py'),
                       ROOT/'a7r5-dat-tool/dattool.py', *sorted((ROOT/'a7r5-dat-tool/a7r5dat').glob('*.py'))]
    packaging_sources = {str(p.relative_to(ROOT)): digest(p) for p in packaging_paths}
    source = regular(Path(source_workspace)/'manifest.json').parent
    before, source_pin = frozen_json(source/'manifest.json')
    require(source_pin['sha256'] == SOURCE_MANIFEST_SHA, '原解包清单不是已完整验签读取的固定来源')
    require(before['source']['sha256'] == DAT_SHA and before['source']['bytes'] == 754525608 and
            (before['header']['major'], before['header']['minor']) == (4, 6), '必须使用原修改版4.06新解包目录')
    require(not (source/'INCOMPLETE.json').exists(), '源解包未完成')
    m, mpin = frozen_json(usr_manifest)
    markers=check_usr_scope(m,version)
    if markers:
        packaging_sources.update(source_pins())
        packaging_paths += [ROOT/name for name in source_pins()]
    u, upin = frozen_json(usr_receipt)
    c, cpin = frozen_json(cp_receipt)
    require(m['recipe_bridge_enabled'] is True and
            m['runtime_passthrough_hooks_source_bound'] is True, '需要真实启动绑定的配对USR清单')
    require(u['status'] == 'UNSIGNED_USR_CONTENT_VERIFIED_NOT_INSTALLABLE' and u['manifest_sha256'] == mpin['sha256'] and
            u['source_sha256'] == USR_SHA and u['source_unchanged'] is True and u['e2fsck_exit_code'] == 0 and
            u['old_inode_and_unrelated_metadata_preserved'] is True, '缺少同源完整USR检查')
    usr = check_entry(dict(path=u['output'], bytes=u['bytes'], sha256=u['output_sha256']))
    require(c['status'] == 'CP_FAT_STAGED_REVERSED_NOT_INSTALLABLE' and c['source_cp_sha256'] == CP_SHA and
            c['source_image_sha256'] == IMAGE_SHA and c['sources_unchanged'] is True and
            c['cp_reverse_equal'] is True and c['whole_partition_reverse_equal'] is True and
            c['unrelated_files_and_metadata_preserved'] is True, '缺少完整CP/FAT检查')
    cp = check_entry(c['files']['cpapp-b.bin'])
    fat = check_entry(c['files']['nflasha8'])
    plan, plan_pin = frozen_json(Path(cp_receipt).parent/'memory-plan.json')
    require(hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest() == c['memory_plan_sha256'], 'CP计划被修改')
    native, npin = frozen_json(plan['build_receipt'])
    require(npin['sha256'] == c['build_receipt_sha256'] == plan['build_receipt_sha256'], '原生构建回执身份不符')
    check_native_contract(native)
    pins = [source_pin, mpin, upin, cpin, plan_pin, npin]
    reports = [native]
    for entry, expected_status in zip((m['software'], m['build'], m['ap']['receipt']),
            ('PASS_SOFTWARE_BUILD_AND_HOST_CONTRACTS', 'PASS_BOOTSTRAP_LINK_ONLY_NOT_EXECUTED',
             'PASS_STATIC_BINDING_AND_COMPOSITE_PLAN_ONLY')):
        report, pin = frozen_json(check_entry(entry))
        require(report['status'] == expected_status and report['recipe_bridge_enabled'] is True, '构建回执阶段或协议不符')
        check_sources(report)
        reports.append(report)
        pins.append(pin)
    check_sources(native)
    for name, wanted in native['generated_sha256'].items():
        p = Path(name)
        require(digest(p if p.is_absolute() else ROOT/p) == wanted, '原生构建产物变化')
    for row in [*m['dsos'], *m['resource_replacements']]:
        check_entry(row)
    require(before['components']['cpapp-b.bin']['sha256'] == CP_SHA and
            before['components']['usr/lib/appFw.so']['sha256'] == AP_SHA, '源AP／CP前像不符')
    for row in before['entries']:
        if row['type'] in ('0', '\x00'):
            require(digest(source/'archive'/row['name']) == row['sha256'], '源归档已经变化：'+row['name'])
    for name, row in before['components'].items():
        require(digest(source/'components'/name) == row['sha256'], '源组件已经变化：'+name)
    require(digest(source/'archive'/tool.AP_IMAGE) == USR_SHA and digest(source/'archive'/tool.CP_IMAGE) == IMAGE_SHA, '源分区错误')
    reverse_cp((source/'components/cpapp-b.bin').read_bytes(), cp.read_bytes(), plan)
    require(independent_cp(fat.read_bytes())[0] == cp.read_bytes(), '冻结CP分区与raw文件不一致')
    original_snapshot = tool.workspace_snapshot(source)
    out = Path(output).absolute()
    require(out.is_relative_to(ROOT/'.local/fixed-custom-filters') and '..' not in out.parts and
            not out.exists() and not any(p.is_symlink() for p in (out, *out.parents)), '必须使用本任务全新本地输出目录')
    out.mkdir(mode=0o700, parents=True)
    write_json(out/'BUILDING.json', dict(status='BUILDING_RESEARCH_UPGRADE', source=before['source'], receipts=pins))
    work = out/'work'
    shutil.copytree(source, work, symlinks=False)
    # 修改的只是全新派生工作副本：USR整分区、CP内部组件，避免同分区双改。
    shutil.copyfile(usr, work/'archive'/tool.AP_IMAGE)
    shutil.copyfile(cp, work/'components/cpapp-b.bin')
    require(digest(work/'archive'/tool.AP_IMAGE) == u['output_sha256'] and
            digest(work/'components/cpapp-b.bin') == c['files']['cpapp-b.bin']['sha256'], '工作副本写入回读不符')
    pending = out/'verification-work'
    pending.mkdir(mode=0o700)
    dat = pending/'BODYDATA.DAT'
    # 正常工具消费项目已有公开研究身份；不读取/输出密钥文本，不修改更新器。
    packed = tool.pack(work, dat, version=version)
    write_json(out/'pack-receipt.json', packed)
    require(packed['source'] == before['source'] and packed['signature_verified'] is True and
            packed['independent_decryption_exact'] is True and
            set(packed['changed_archive_members']) == ALLOWED and packed['changed_components'] == ['/cpapp-b.bin'], '正常封装回执范围错误')
    final = out/'readback'
    unpacked = tool.unpack(dat, final)
    write_json(out/'readback-unpack.json', unpacked)
    after, _ = frozen_json(final/'manifest.json')
    require(after['source']['sha256'] == digest(dat) == packed['sha256'] and
            after['signature_verified'] is True and
            after['public_key_sha256'] == before['public_key_sha256'] == packed['public_key_sha256'], '最终重解包签名／身份不符')
    changed = verify_archive(before, after, u['output_sha256'], c['files']['nflasha8']['sha256'])
    verify_format(source, final, version)
    actual_cp = (final/'components/cpapp-b.bin').read_bytes()
    require(actual_cp == cp.read_bytes() and independent_cp((final/'archive'/tool.CP_IMAGE).read_bytes())[0] == actual_cp, '最终DAT不是冻结CP')
    reverse_cp((source/'components/cpapp-b.bin').read_bytes(), actual_cp, plan)
    require((final/'archive'/tool.AP_IMAGE).read_bytes() == usr.read_bytes(), '最终DAT不是完整冻结USR')
    components = verify_usr(final/'archive'/tool.AP_IMAGE, expected_usr(m))
    require(tool.workspace_snapshot(source) == original_snapshot, '原解包输入被修改')
    for pin in pins:
        check_entry(pin)
    for report in reports:
        check_sources(report)
    for row in [*m['dsos'], *m['resource_replacements'], *c['files'].values()]:
        check_entry(row)
    check_entry(dict(path=u['output'], bytes=u['bytes'], sha256=u['output_sha256']))
    require(digest(source_dat) == DAT_SHA, '原DAT变化')
    require(packaging_sources == {str(p.relative_to(ROOT)): digest(p) for p in packaging_paths}, '封装器源码在构建期间变化')
    target = out/'BODYDATA.DAT'
    facts = tool.file_facts(dat)
    require(facts['sha256'] == packed['sha256'], '发布前DAT发生变化')
    result = dict(schema='a7r5-406-research-upgrade/1', status='RESEARCH_UPGRADE_PACKAGED_AND_INDEPENDENTLY_READ_BACK',
        baseline=before['source'], version=version, output=str(target), **facts,
        receipts=pins, changed_archive_members=changed, verified_usr_components=components,
        packaging_source_sha256=packaging_sources, python_runtime=sys.version,
        crypto_runtime={name: importlib.metadata.version(name) for name in ('cryptography', 'pycryptodomex')},
        CP_sha256=hashlib.sha256(actual_cp).hexdigest(), USR_sha256=u['output_sha256'],
        public_key_sha256=packed['public_key_sha256'], research_signature=True, official_signature=False,
        signature_verified=True, independent_decryption_exact=True, full_archive_readback_verified=True,
        source_workspace_unchanged=True, CP_reverse_equal=True, gamma_format_changed=False,
        photo_markers_included=markers,photo_overlay_verified=False,
        photo_marker_contract=m['ap'].get('aspect_merge') if markers else None,
        camera_io=False, hardware_simulation=False, target_executed=False,
        device_acceptance_verified=False, device_installation_approved=False,
        runtime_negotiation_verified=False,
        release_scope='原厂12外观＋20用户槽；机内ST/context4近似CUBE及电脑配方双入口；'+
                      ('照片标记扩展已合并，实际叠加未验证；' if markers else '')+'研究候选，未实机验收',
        limitations=['机内CUBE模型误差属于固定ST/context4参考域，不是机身色差',
                     '特殊请求、原snapshot恢复及原后处理保持其条件，不提供整配方逐帧原子保证',
                     '机身信任环境、升级接纳、取景/JPG、SD与掉电未验收',
                     '照片标记仅证明原登记和支持位已打包，不证明预览叠加通过'])
    publish_package(dat, out, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-dat', 'source-workspace', 'usr-manifest', 'usr-receipt', 'cp-receipt', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--version', default='4.08')
    args = parser.parse_args()
    result = build(args.source_dat, args.source_workspace, args.usr_manifest, args.usr_receipt, args.cp_receipt, args.output, args.version)
    print(json.dumps({k: result[k] for k in ('status', 'output', 'version', 'bytes', 'sha256', 'signature_verified', 'full_archive_readback_verified', 'device_acceptance_verified')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
