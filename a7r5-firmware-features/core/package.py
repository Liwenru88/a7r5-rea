"""复用 DAT 工具写入组件并独立回读，只在校验完成后发布。"""
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

from .plan import (FEATURES, ROOT, GL, GL_DATA, configuration, digest, make_plan, merge_component,
                   read_json, require, require_base, sha)
from . import capture, native24

DAT_TOOL = ROOT / 'a7r5-dat-tool'
KEYS = DAT_TOOL / 'keys'
sys.path.insert(0, str(DAT_TOOL))
from a7r5dat import tool
from a7r5dat.codec import verify_signature


def local_path(path):
    path = path.absolute()
    local = ROOT / '.local'
    require(path.resolve().is_relative_to(local) and path != local
            and not any(p.is_symlink() for p in (path, *path.parents)),
            '输出或验证目录必须位于 .local 内，且路径无符号链接')
    return path


def source_snapshot(plan):
    paths = [FEATURES / 'compose.py', *sorted((FEATURES / 'core').glob('*.py')),
             *sorted((DAT_TOOL / 'a7r5dat').glob('*.py'))]
    if plan['template_fields']:
        paths += [GL_DATA, GL / 'templates/prepare_templates.py', GL / 'lib/sony_bk4.py']
    if plan.get('native24'):
        paths += native24.resources(plan)
    if plan.get('color_modules'):
        paths += native24.color_resources()
    if plan.get('capture_modules'):
        paths += capture.resources(plan)
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def apply_rows(raw, rows, name, *, factory_six=False):
    adjusted = []
    for row in rows:
        if 'address' in row:
            require(name == native24.AP and row['address'] == 'primary-rx-header'
                    and row['offset'] in (96, 104) and raw[:6] == b'\x7fELF\x02\x01', 'AP 活动程序头声明无效')
            at, = struct.unpack_from('<Q', raw, 32)
            size, count = struct.unpack_from('<HH', raw, 54)
            require(size == 56 and count >= 2 and 64 <= at <= len(raw) - size * count,
                    'AP 活动程序头越界')
            tag, flags, offset, va, _pa, filesz, memsz, _alignment = struct.unpack_from('<II6Q', raw, at)
            end = int.from_bytes(bytes.fromhex(row['after']), 'little')
            require((tag, flags, offset, va) == (1, 5, 0, 0) and filesz == memsz < end <= len(raw),
                    'AP 原厂 RX 映射不符')
            for i in range(1, count):
                tag, _flags, offset, va = struct.unpack_from('<II2Q', raw, at + size * i)
                require(tag != 1 or min(offset, va) >= end, 'AP 标记代码与其他映射重叠')
            row = dict(row, offset=at + row['offset'] - 64)
            if factory_six:
                require(filesz == 0x500fc10, '六款和标记的共享 RX 前像不符')
                row['before'] = struct.pack('<Q', 0x500fc10).hex()
        adjusted.append(row)
    result = bytearray(raw)
    for at, (old, new, module) in merge_component(adjusted, len(raw)).items():
        require(raw[at] == old, f'{module} 局部前像不符 {name}+{at:#x}')
        result[at] = new
    return result


def apply_components(work, manifest, plan):
    changed = {}
    for name, rows in plan['component_patches'].items():
        pin = plan['base']['components'][name]
        require(manifest['components'][name] == pin, '组件布局或原厂摘要不符 ' + name)
        path = tool.inside(work / 'components', name)
        raw = path.read_bytes()
        require(len(raw) == pin['bytes'] and sha(raw) == pin['sha256'], '原厂组件前像不符 ' + name)
        result = apply_rows(raw, rows, name)
        path.write_bytes(result)
        changed[name] = dict(pin, sha256=sha(result))
    return changed


def apply_templates(work, plan):
    if not plan['template_fields']:
        return
    sys.path.insert(0, str(GL / 'templates'))
    try:
        import prepare_templates as template
    finally:
        sys.path.remove(str(GL / 'templates'))
    pins = plan['base']['gl_templates']
    require(pins == {template.PREFIX + name: value for name, value in template.STOCK_HASHES.items()},
            '地区模板来源与基线不符')
    fields = {(f.key, f.offset, len(f.data), sha(f.data)): f for f in template.colour_fields()}
    selected = []
    for row in plan['template_fields']:
        key = tuple(row[k] for k in ('property', 'offset', 'bytes', 'value_sha256'))
        require(key in fields, f'模板字段前像或值不匹配 {row["module"]}')
        selected.append(fields[key])
    for name, pin in sorted(pins.items()):
        path = tool.inside(work / 'archive', name)
        original = path.read_bytes()
        require(sha(original) == pin, '原厂模板摘要不符 ' + name)
        result, _, _ = template.patch_template(original, original, selected)
        path.write_bytes(result)


def prepare(base, plan, scratch):
    work = scratch / 'stock'
    tool.unpack(base, work, KEYS / 'sony-original-public.pem')
    before = read_json(work / 'manifest.json')
    pin = plan['base']
    header = before['header']
    require(before['source'] == pin['dat'] and before['updater_sha256'] == pin['updater_sha256']
            and header['model'] == pin['model_code']
            and f"{header['major']:x}.{header['minor']:02x}" == pin['version'],
            '原厂工作区身份不符')
    if plan.get('native24') or plan.get('color_modules') or plan.get('capture_modules'):
        components = native24.apply(work, before, plan, scratch, apply_rows)
    else:
        components = apply_components(work, before, plan)
    apply_templates(work, plan)
    expected_dir = scratch / 'expected'
    expected_dir.mkdir()
    _, facts, _ = tool.collect(work, before, expected_dir)
    archive = {row['name']: facts[row['name']] for row in before['entries']
               if row['name'] in facts and facts[row['name']]['sha256'] != row['sha256']}
    require(set(archive) == set(plan['archive_targets']), '实际归档变化与计划不符')
    expected = dict(components=components, archive=archive)
    companion = native24.companion(plan)
    if companion:
        expected['companion'] = dict(file=companion.name, sha256=digest(companion))
    return work, before, expected


def verify_readback(dat, work, before, expected, version, scratch):
    readback = scratch / 'readback'
    public = KEYS / 'research-public.pem'
    tool.unpack(dat, readback, public)
    after = read_json(readback / 'manifest.json')
    for key in ('updater_sha256', 'outer', 'iv', 'tail'):
        require(before[key] == after[key], '容器固定内容变化 ' + key)
    original_header = bytearray((work / 'format/header.bin').read_bytes())
    major, minor = version.split('.')
    original_header[32:34] = bytes((int(minor, 16), int(major, 16)))
    struct.pack_into('<I', original_header, 8, zlib.crc32(original_header[12:]))
    require((readback / 'format/header.bin').read_bytes() == original_header, '版本之外的包头变化')
    components = expected['components'].copy()
    if avcam := components.pop(capture.AVCAM, None):
        capture.verify_avcam(readback, avcam)
    if mpr := components.pop(capture.MPR, None):
        capture.verify_mpr(readback, mpr)
    require(after['components'] == (before['components'] | components),
            '回读组件存在遗漏或未授权变化')
    for left, right in zip(before['entries'], after['entries'], strict=True):
        facts = expected['archive'].get(left['name'])
        wanted = left | {key: facts[key] for key in ('sha256', 'crc32')} if facts else left
        require(wanted == right, '回读归档成员不符 ' + left['name'])

    if tool.AP_IMAGE in expected['archive']:
        e2fsck = shutil.which('e2fsck') or '/opt/homebrew/opt/e2fsprogs/sbin/e2fsck'
        subprocess.run([e2fsck, '-fn', str(readback / 'archive' / tool.AP_IMAGE)],
                       check=True, capture_output=True)
    _, signed, signature = verify_signature(dat, public.read_bytes())
    (scratch / 'signed.sha256').write_bytes(signed.digest())
    (scratch / 'signature.bin').write_bytes(signature)
    subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(public),
                    '-sigfile', str(scratch / 'signature.bin'), '-in', str(scratch / 'signed.sha256'),
                    '-pkeyopt', 'digest:sha256'], check=True, capture_output=True)
    return dict(status='OFFLINE_VERIFIED', dat=after['source'], version=version,
                frames=after['decryption']['frame_count'], archive_entries=len(after['entries']),
                changed_archive=sorted(expected['archive']), components=expected['components'],
                independent_unpack=True, openssl_signature_verified=True,
                usr_filesystem='checked' if tool.AP_IMAGE in expected['archive'] else 'stock',
                camera_io=False, device_acceptance_verified=False)


def verify_version(version):
    require(isinstance(version, str) and re.fullmatch(r'\d{1,2}\.\d{2}', version),
            '输出版本格式应为 4.06 等两位小数')


def build(base, plan, output, version):
    verify_version(version)
    output = local_path(output)
    require(output.parent.is_dir() and not output.exists(), '输出必须是存在父目录下的新目录')
    require_base(base, plan)
    sources = source_snapshot(plan)
    with tempfile.TemporaryDirectory(prefix='.compose-', dir=output.parent) as folder:
        scratch = Path(folder)
        work, before, expected = prepare(base, plan, scratch)
        candidate = scratch / 'BODYDATA.DAT'
        packed = tool.pack(work, candidate, version)
        receipt = verify_readback(candidate, work, before, expected, version, scratch)
        require(receipt['dat']['sha256'] == packed['sha256'], 'DAT 封包与回读摘要不符')
        require(source_snapshot(plan) == sources
                and make_plan(configuration(plan)) == plan,
                '构建期间模块或源码发生变化')
        lock = dict(schema=1, plan=plan, version=version, sources=sources,
                    python=sys.version.split()[0], expected=expected, dat=receipt['dat'])
        tool.save(scratch / 'lock.json', lock)
        tool.save(scratch / 'verification.json', receipt)
        companion = native24.companion(plan)
        names = ['lock.json', 'verification.json']
        if companion:
            shutil.copyfile(companion, scratch / companion.name)
            require(digest(scratch / companion.name) == expected['companion']['sha256'], '随包配方变化')
            names.append(companion.name)
        output.mkdir(mode=0o700)
        for name in (*names, candidate.name):
            os.link(scratch / name, output / name)
        if plan.get('variants'):
            # 保留本次实际构建产物供最终 DAT 回放和 QEMU 核对，不借用旧候选。
            evidence = output / 'build-evidence'
            evidence.mkdir()
            for name in ('native24', 'capture'):
                shutil.copytree(scratch / name, evidence / name, copy_function=os.link)
    return receipt


def verify(base, bundle):
    bundle = local_path(bundle)
    lock = read_json(tool.regular(bundle / 'lock.json'))
    require(lock['schema'] == 1, '构建锁版本不支持')
    plan = make_plan(configuration(lock['plan']))
    version = lock['version']
    verify_version(version)
    require(plan == lock['plan'], '模块计划与构建锁不符')
    sources = source_snapshot(plan)
    require_base(base, plan)
    dat = tool.regular(bundle / 'BODYDATA.DAT')
    require(digest(dat) == lock['dat']['sha256'], '候选 DAT 摘要不符')
    with tempfile.TemporaryDirectory(prefix='.compose-verify-', dir=bundle.parent) as folder:
        scratch = Path(folder)
        work, before, expected = prepare(base, plan, scratch)
        require(expected == lock['expected'], '原厂重建的目标成员与构建锁不符')
        if 'companion' in expected:
            asset = expected['companion']
            require(digest(tool.regular(bundle / asset['file'])) == asset['sha256'], '随包配方摘要不符')
        result = verify_readback(dat, work, before, expected, version, scratch)
        require(result['dat'] == lock['dat'] and plan == make_plan(configuration(plan))
                and source_snapshot(plan) == sources, '验证期间输入或源码发生变化')
        if sources != lock['sources']:
            result['reverified_with_updated_builder'] = True
    return result
