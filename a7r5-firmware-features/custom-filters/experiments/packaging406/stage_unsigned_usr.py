"""生成明确不可安装的未签名USR准备镜像；不改输入、CP、DAT或签名材料。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tempfile

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'a7r5-dat-tool/a7r5dat').is_dir())
sys.path.insert(0, str(ROOT/'a7r5-dat-tool'))
from a7r5dat.ext2_add import AddDso, Audit, derive_usr_image, digest, identity, regular
from a7r5dat.ext2_patch import Patch
from a7r5dat.ext2_image_append import AppendImagePatch
from candidate_preflight import AP_SHA, compose, require
from aspect_merge import aspect_contract, validate_plan

USR_SHA = 'f7a23ecdc4d4848a2b4a33398313d8def642bc4a2e9e007c42fb1fa1b48097bf'
DSOS = {'/lib/libaf_bootstrap406.so', '/lib/libaf_ui406.so',
        '/lib/libaf_requests406.so', '/lib/libaf_repository_media.so'}
CAPACITY_FIELDS = set(range(4, 8)) | set(range(28, 32)) | set(range(40, 100))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def frozen_manifest(path, expected):
    # 摘要与解析必须消费同一份字节，不能校验完路径后再独立重读。
    raw = path.read_bytes()
    require(sha(raw) == expected, '输入清单摘要不符')
    return json.loads(raw)


def validate_manifest(m):
    require(m.get('schema') in ('a7r5-406-unsigned-staging-input/1', 'a7r5-406-unsigned-staging-input/2',
                              'a7r5-406-unsigned-staging-input/3') and
            m.get('status') == 'FROZEN_PREPARE_ONLY_DEFAULT_CLOSED', '清单版本或阶段不符')
    require(m.get('installable_firmware') is False and m.get('CP_gates_installed') is False and
            m.get('UI_gates_installed') is False, '禁止将发布/安装清单作为准备镜像')
    markers=m['schema'].endswith('/3')
    require(m['source_usr']['sha256'] == USR_SHA and m['ap']['source_sha256'] == AP_SHA and
            m['ap']['includes_aspect_changes'] is markers, '基线或AP范围不符')
    if markers:
        validate_plan(m['ap']['patches'],m['ap'].get('aspect_merge'))
    # 新版仅增加已定位的构造器垫片、单个数组指针及既有RELATIVE加数。
    paired = m['schema'].endswith(('/2','/3'))
    end = 0x500ff8c if paired else 0x500fdfc
    fixed = {0x500fc70: (bytes(396), None),
             0x17feac0: (bytes.fromhex('fd7bbaa9'), bytes.fromhex('6c44e014')),
             0x60: (struct.pack('<Q', 0x500fc10), struct.pack('<Q', end)),
             0x68: (struct.pack('<Q', 0x500fc10), struct.pack('<Q', end))}
    if paired:
        fixed.update({0x500fdfc: (bytes(400), None),
                      0x5010388: (struct.pack('<Q', 0x16fbfc0), struct.pack('<Q', 0x500fdfc)),
                      0x10c68: (struct.pack('<Q', 0x16fbfc0), struct.pack('<Q', 0x500fdfc))})
    if markers:
        fixed.update({row['offset']:(bytes.fromhex(row['before']),bytes.fromhex(row['after']))
                      for row in aspect_contract()})
    patches = m['ap']['patches']
    require(type(patches) is list and len(patches) == len(fixed), 'AP窗口数量不符')
    seen = set()
    for row in patches:
        at = row.get('offset')
        require(type(at) is int and at in fixed and at not in seen, 'AP窗口越界或重复')
        seen.add(at)
        before, after = fixed[at]
        require(row.get('before') == before.hex() and type(row.get('after')) is str and
                re.fullmatch('[0-9a-f]{'+str(len(before)*2)+'}', row['after']) and
                (after is None or row['after'] == after.hex()), 'AP窗口前后像或长度不符')
    dsos = m['dsos']
    require(len(dsos) == 4 and {r['target'] for r in dsos} == DSOS, '必须恰好四个已命名模块')
    assets = m['resource_replacements']
    names = [r['target'] for r in assets]
    require(len(names) == 70 and len(set(names)) == 70, '必须恰好70个独立资源')
    for row in assets:
        require(row['target'] == row['source_member'] and
                (re.fullmatch(r'/share/app/string_[a-z]+_(horizontal|vertical)\.uxc', row['target']) or
                 row['target'] in AppendImagePatch._bindings), '资源路径超出固定范围')
    require(set(AppendImagePatch._bindings) <= set(names), '缺少两份实际图标资源')
    for row in [*assets, *dsos]:
        require(type(row['bytes']) is int and 0 < row['bytes'] <= 16 << 20 and
                re.fullmatch('[0-9a-f]{64}', row['sha256']), '组件长度/摘要不符')
    return set(names)


def checked_file(row):
    p = regular(row['path'])
    require(p.stat().st_size == row['bytes'] and digest(p) == row['sha256'], '候选组件变化：'+str(p))
    return p


def inventory(path):
    audit = Audit(path)
    try:
        return audit.inventory()
    finally:
        audit.close()


def check_tree(before, after, replacements, additions=()):
    require(set(after) == set(before) | set(additions), '派生文件树出现未声明变化')
    for name, old in before.items():
        new = after[name]
        require((old['inode'], old['mode'], old['uid'], old['acl_sha256']) ==
                (new['inode'], new['mode'], new['uid'], new['acl_sha256']), '身份/属性变化：'+name)
        if name in replacements:
            wanted = replacements[name]
            require(stat.S_ISREG(new['mode']) and new['size'] == wanted['bytes'] and
                    new['sha256'] == wanted['sha256'], '替换回读失败：'+name)
        elif name != '/lib' or not additions:
            require(old == new, '无关内容或inode/映射/目录字节变化：'+name)
            continue
        require(all(a == b for i, (a, b) in enumerate(zip(old['raw'], new['raw']))
                    if i not in CAPACITY_FIELDS), '非容量元数据变化：'+name)


def stage(manifest, expected, output):
    manifest = regular(manifest)
    m = frozen_manifest(manifest, expected)
    validate_manifest(m)
    source = regular(m['source_usr']['path'])
    original_id = identity(source)
    require(digest(source) == USR_SHA, 'USR不是既有修改4.06原分区')
    for row in [*m['resource_replacements'], *m['dsos']]:
        checked_file(row)
    for entry in (m['ap']['receipt'], m['build']):
        checked_file(entry)
    output = Path(output).resolve()
    require(output.is_relative_to(ROOT/'.local/fixed-custom-filters') and not output.exists(), '输出必须是全新任务目录')
    output.mkdir(parents=True)
    before = inventory(source)
    replacements = {r['target']: r for r in m['resource_replacements']}
    replacements['/lib/appFw.so'] = {'bytes': before['/lib/appFw.so']['size'], 'sha256': m['ap']['target_sha256']}
    for row in m['resource_replacements']:
        require(before[row['target']]['sha256'] == row['source_sha256'], '资源原像不符：'+row['target'])
    # 所有写入均局限本次新临时镜像；分配失败不发布半成品。
    with tempfile.TemporaryDirectory(prefix='staging-', dir=output, ignore_cleanup_errors=True) as temp_name:
        temp = Path(temp_name)
        base = source.read_bytes()
        patch = AppendImagePatch(base)
        app = patch.fs.read_inode(patch.fs.walk('/lib/appFw.so'))
        candidate = compose(app, AP_SHA, m['ap']['patches'])
        require(sha(candidate) == m['ap']['target_sha256'], 'AP启动补丁候选摘要不符')
        Patch.replace(patch, '/lib/appFw.so', app, candidate)
        for row in m['resource_replacements']:
            name = row['target']
            old = patch.fs.read_inode(patch.fs.walk(name))
            target = checked_file(row).read_bytes()
            if name in AppendImagePatch._bindings:
                patch.replace(name, old, target)
            else:
                Patch.replace(patch, name, old, target)
        raw, patch_receipt = patch.finish()
        middle = temp/'components.ext2'
        with middle.open('xb') as stream:
            stream.write(raw)
        del patch, raw, base, app, candidate
        check_tree(before, inventory(middle), replacements)
        derived = temp/'modules.ext2'
        additions = [AddDso(checked_file(r), r['target'], r['sha256']) for r in m['dsos']]
        added = derive_usr_image(middle, derived, additions, digest(middle))
        after = inventory(derived)
        check_tree(before, after, replacements, DSOS)
        for row in m['dsos']:
            require(after[row['target']]['sha256'] == row['sha256'], '模块最终回读不符')
        fsck = subprocess.run(['/opt/homebrew/opt/e2fsprogs/sbin/e2fsck', '-f', '-n', str(derived)],
                              capture_output=True, text=True)
        (output/'e2fsck.json').write_text(json.dumps({'exit_code': fsck.returncode, 'stdout': fsck.stdout,
                                                    'stderr': fsck.stderr}, ensure_ascii=False, indent=2)+'\n')
        require(fsck.returncode == 0, '独立文件系统检查失败，不发布镜像')
        require(identity(source) == original_id and digest(source) == USR_SHA and
                digest(manifest) == expected, '原输入在staging期间变化')
        final = output/'UNINSTALLABLE-unsigned-USR.ext2'
        result = dict(status='UNSIGNED_USR_CONTENT_VERIFIED_NOT_INSTALLABLE', manifest_sha256=expected,
            source_sha256=USR_SHA, output=str(final), output_sha256=digest(derived),
            bytes=derived.stat().st_size, old_entries=len(before), resource_replacements=70,
            app_patch_windows=len(m['ap']['patches']), added_dsos=4, new_entries=len(after), source_unchanged=True,
            old_inode_and_unrelated_metadata_preserved=True, e2fsck_exit_code=0,
            patch_receipt=patch_receipt, dso_receipt=added, installable_firmware=False,
            CP_updated=False, UI_published=False, hardware_simulation=False, camera_io=False,
            private_key_accessed=False, DAT_created=False, signed=False,
            publication='须独立核对output存在且摘要匹配；本内容回执不单独宣告镜像已发布',
            blockers=['CP实际装载及安全启动准入尚未完成，不能以拟议单页链接通过替代',
                      '完整sRGB/非零网格模型与同C4四组件应用尚未接通',
                      '原注册时序/全部模式退出/持久化及媒体目录来源仍未准入'])
        with derived.open('rb') as stream:
            os.fsync(stream.fileno())
        # 完整回执先持久化，镜像最后一步无覆盖发布；回执写入失败不发布镜像。
        with (output/'verification.json').open('x') as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(derived, final)
    return dict(result, status='UNSIGNED_USR_STAGED_NOT_INSTALLABLE', image_published=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = stage(args.manifest, args.manifest_sha256, args.output)
    print(json.dumps({k: result[k] for k in ('status', 'output_sha256', 'resource_replacements', 'added_dsos',
                                            'e2fsck_exit_code', 'installable_firmware', 'image_published')}, ensure_ascii=False, indent=2))
