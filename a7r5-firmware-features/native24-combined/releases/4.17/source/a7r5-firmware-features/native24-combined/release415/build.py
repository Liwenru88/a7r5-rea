"""固定017图标分块修复载荷的4.15离线研究封包；无设备入口，未知输入失败即停止。"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FEATURE = HERE.parent
PARENT = FEATURE.parent/'native12-combined'
ARCHIVE = FEATURE/'verification/2026-11-04-icon-pages-01'
ARCHIVE_SHA = 'a276d71ac8526ea6817275d93e4cec7d0a4b7f9eb757c3bf4bff3ea523c20b06'
BASELINE = ROOT/'.local/native12-combined-baseline-01'
VERSION = '4.15'
RUNTIME = ROOT/'.local/native24-pages-20261104-02'
CPU = ROOT/'.local/native24-update414-runtime-cpu-20261104-01'
CPU_TESTS = 82
REQUIRED_TESTS = {
    'test_synchronous_native_index_query_during_tab_publication_uses_group_index',
    'test_added_icons_use_native_f0_blocks_instead_of_hardware_rejected_raw_blocks',
}
sys.path.insert(0, str(ROOT/'a7r5-dat-tool'))
from a7r5dat import tool
from a7r5dat.codec import digest, require, verify_signature
from a7r5dat.ext2_add import Audit
from a7r5dat.ext2_image_append import AppendImagePatch, ImageBinding
from a7r5dat.ext2_patch import reader
from a7r5dat.fat import FatImage

COMPONENTS = {
    'appFw.so': '1f7fda3baf1afbe2badaee5007383839c5843b67023e546c10edbc70d28da58e',
    'cpapp-b.bin': '35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300',
    'image_00_23_IPSX.uxc': '6e8c09e8e8a302aa05e7d8dd56f68bdb3675c486ca54a88ba81375b5c02a3bb7',
    'image_00_32_IPSX.uxc': '7e598d75a997c37cea6204e8e35773e9b9ee5e4ce67b0c0ab569011563af3356',
}
USR_SHA = 'bfaf6c1e27ba7130883103e43c6d124a7364e62b18fc8044f08895a78f1ab2df'
FILTER_SHA = '19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6'
PUBLIC_SHA = '7f65b296987df665da217de514e785f75238e686ddd18952fa425fc47e8c858a'


class CandidatePatch(AppendImagePatch):
    # 只对本轮三个固定文件生效，通用工具及旧图标绑定保持。
    _bindings = {
        '/lib/appFw.so': ImageBinding(14597, 97452032, 97583104,
            'bc766baaf1cd617479993afbec526bbc4dd5f6fc62a0f79bf2682abbd1adc222', COMPONENTS['appFw.so']),
        '/share/app/image_00_23_IPSX.uxc': ImageBinding(84194, 9598260, 9611836,
            '80637a7bb69ccf2ddc6308a148847d1f14a88aa2001e4fc7de04b3e4c83ef061', COMPONENTS['image_00_23_IPSX.uxc']),
        '/share/app/image_00_32_IPSX.uxc': ImageBinding(84053, 9949936, 9963512,
            'd5ec718d642fa8b813cf05c45bb0bc53f68b9bc4152fe003f01cdc39efc8a9db', COMPONENTS['image_00_32_IPSX.uxc']),
    }


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_candidate(c):
    require(c.get('spec') == 'a7r5-firmware-features/specs/017-icon-page-boundary' and
            c.get('status') == 'NOT_VERIFIED', '分块修复来源或状态不符')
    repair = c.get('page_boundary_fix', {})
    require(repair.get('status') == 'OFFLINE_REPAIR_VERIFIED_DEVICE_NOT_VERIFIED' and
            {k:v.get('sha256') for k,v in repair.get('components', {}).items()} == COMPONENTS and
            c.get('bundle_sha256') == ARCHIVE_SHA and repair.get('output_blocks') == [4096,1504] and
            repair.get('hardware_LDEC_verified') is False, '分块组件或审查来源不符')


def validate_cpu(c):
    require(c.get('status') == 'PASS' and c.get('full_related_suite') is True and
            c.get('sources_unchanged') is True and c.get('exit_code') == 0 and
            len(c.get('tests', [])) == len(set(c.get('tests', []))) == CPU_TESTS, '完整相关回归不符')
    require(REQUIRED_TESTS <= {n.rsplit('::', 1)[-1] for n in c['tests']}, '缺少本次故障回归')
    require(c.get('AP_sha256') == COMPONENTS['appFw.so'] and c.get('CP_sha256') == COMPONENTS['cpapp-b.bin'],
            '回归组件不符')


def check_members(old, new, expected):
    require(len(old) == len(new), '归档成员数量变化')
    changes = []
    for a, b in zip(old, new):
        require(a.keys() == b.keys() and all(a[k] == b[k] for k in a if k not in ('sha256', 'crc32')),
                '归档成员元数据／布局变化')
        if a != b:
            require(b['name'] in expected and b['sha256'] == expected[b['name']], '归档出现未授权变化')
            changes.append(b['name'])
    require(set(changes) == set(expected), '归档变化集合不符')
    return changes


def sources():
    paths = list(HERE.glob('*.py')) + list(HERE.glob('*.json')) + list(HERE.glob('*.md')) + list((ROOT/'a7r5-dat-tool/a7r5dat').glob('*.py'))
    paths += [ROOT/'a7r5-qemu/source/guest'/name for name in ('sony-lz77.c','sony-lz77.h','menu-observe-a7r5-baseline.c')]
    paths += [PARENT/'build.py', ROOT/'a7r5-dat-tool/tests/test_ext2_image_append.py',
              ROOT/'a7r5-dat-tool/tests/test_tool.py']
    for directory in (FEATURE, FEATURE/'runtime', FEATURE/'tests', PARENT/'tests',
                      ROOT/'a7r5-qemu/experiments/native24-tabs-pages'):
        paths += [p for p in directory.iterdir() if p.is_file() and p.suffix in ('.py','.c','.h','.S','.ld','.json')
                  and p.name != 'current-candidate.json']
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))}


def reuse_evidence(out):
    gate = load(HERE/'evidence_gate.py', 'native24_415_evidence_gate')
    gate.verify(globals(), out)


def inventory(path):
    audit = Audit(path)
    try:
        return audit.geometry, audit.inventory()
    finally:
        audit.close()


def prepare_usr(source, output, out, components_dir=ARCHIVE/'components', patch_type=CandidatePatch):
    require(digest(source) == USR_SHA, 'USR不是冻结上游基线')
    before_geometry, before = inventory(source)
    raw = source.read_bytes()
    patch = patch_type(raw)
    for path in patch_type._bindings:
        original = patch.fs.read_inode(patch.fs.walk(path))
        patch.replace(path, original, (components_dir/Path(path).name).read_bytes())
    data, report = patch.finish()
    with output.open('xb') as stream:
        stream.write(data)
    del patch, raw, data
    after_geometry, after = inventory(output)
    require(before_geometry == after_geometry and set(before) == set(after), 'USR几何／文件树变化')
    capacity = set(range(4, 8)) | set(range(28, 32)) | set(range(40, 100))
    for name, row in before.items():
        if name not in patch_type._bindings:
            require(row == after[name], 'USR无关文件／映射变化：'+name)
            continue
        target = after[name]
        binding = patch_type._bindings[name]
        require(target['inode'] == row['inode'] == binding.inode and target['size'] == binding.target_bytes and
                target['sha256'] == binding.target_sha256 and target['acl_sha256'] == row['acl_sha256'],
                'USR目标身份／内容变化')
        require(all(a == b for i, (a, b) in enumerate(zip(row['raw'], target['raw'])) if i not in capacity),
                'USR非容量inode属性变化')
    report.update(status='PASS', source_sha256=USR_SHA, target_sha256=digest(output),
                  audited_paths=len(before), unrelated_paths_exact=True, geometry_unchanged=True)
    save(out/'USR.json', report)
    result = subprocess.run(['/opt/homebrew/opt/e2fsprogs/sbin/e2fsck', '-fn', str(output)], capture_output=True, text=True)
    (out/'e2fsck.log').write_text(result.stdout+result.stderr)
    require(result.returncode == 0, 'USR文件系统检查失败')
    return report


def prepare_cp(source, output, out, component=ARCHIVE/'components/cpapp-b.bin',
               component_sha=COMPONENTS['cpapp-b.bin']):
    raw = source.read_bytes()
    target = bytearray(raw)
    fs = FatImage(raw)
    expected = component.read_bytes()
    require(sha(expected) == component_sha, 'CP候选组件摘要不符')
    used = fs.patch(target, '/cpapp-b.bin', expected)
    require(FatImage(target).read('/cpapp-b.bin') == expected, 'CP回读不符')
    cursor = 0
    for start, size in sorted(used):
        require(target[cursor:start] == raw[cursor:start], 'CP无关字节变化')
        cursor = start+size
    require(target[cursor:] == raw[cursor:], 'CP尾部无关字节变化')
    with output.open('xb') as stream:
        stream.write(target)
    save(out/'CP.json', dict(status='PASS', component_sha256=component_sha,
         source_sha256=sha(raw), target_sha256=digest(output), unrelated_bytes_exact=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package(args.output.absolute(), baseline=BASELINE, components_dir=ARCHIVE/'components',
            components=COMPONENTS, patch_type=CandidatePatch, version=VERSION,
            release_dir=HERE, evidence_check=reuse_evidence,
            reused=dict(reused_CPU_tests=CPU_TESTS, reused_targeted_tests=23, reused_QEMU_frames=103))


def package(out, *, baseline, components_dir, components, patch_type, version, release_dir,
            evidence_check, reused):
    require(out.is_relative_to(ROOT/'.local') and not out.exists(), '输出必须是.local内新目录')
    require(not any(p.is_symlink() for p in (out, *out.parents)), '输出路径不可含符号链接')
    out.mkdir(mode=0o700)
    evidence = out/'evidence'; evidence.mkdir()
    (out/'INCOMPLETE.json').write_text('{"status":"INCOMPLETE","camera_io":false}\n')
    def package_sources():
        release_sources = {str(p.relative_to(ROOT)): digest(p) for p in release_dir.iterdir()
                           if p.is_file() and p.suffix in ('.py', '.json', '.md')}
        return sources() | release_sources

    source_before = package_sources()
    parent = load(PARENT/'build.py', 'native24_415_parent')
    firmware, _ = parent.check_upstream(PARENT/'upstream')
    sys.path.insert(0, str(firmware/'src/lib'))
    evidence_check(evidence)
    print(f'{version} 固定候选和离线证据通过', flush=True)
    base = json.loads(parent.regular(baseline/'baseline.json').read_text())
    expected_base = json.loads((firmware/'expected_outputs.json').read_text())
    require(base['passed'] and base['actual'] == {k: expected_base[k] for k in base['actual']}, '上游基线回执不符')
    inputs = {k: parent.regular(v) for k, v in base['original_inputs'].items()}
    lock = json.loads((firmware/'inputs.lock.json').read_text())
    for name, path in inputs.items():
        require(digest(path) == lock[name]['sha256'] and path.stat().st_size == lock[name]['bytes'], '原始输入不符：'+name)
    for name in ('nflasha15', 'nflasha8', 'nflasha5'):
        require(digest(parent.regular(baseline/'patched'/name)) == expected_base[name], '上游分区基线漂移')
    tests = [str(HERE/'test_release.py'), str(ROOT/'a7r5-dat-tool/tests/test_ext2_image_append.py'),
             str(ROOT/'a7r5-dat-tool/tests/test_tool.py')]
    command = [sys.executable, '-B', '-m', 'pytest', '-q', *tests, '--tb=short', '--junitxml='+str(evidence/'packaging-tests.xml')]
    checked = subprocess.run(command, capture_output=True, text=True)
    (evidence/'packaging-tests.log').write_text(checked.stdout+checked.stderr)
    require(checked.returncode == 0, '封装层回归失败')
    test_cases = list(ET.parse(evidence/'packaging-tests.xml').getroot().iter('testcase'))
    require(test_cases and not any(c.find(k) is not None for c in test_cases for k in ('failure', 'error', 'skipped')),
            '封装回归有失败／跳过')
    print('封装层回归通过，扩展固定USR文件', flush=True)
    patched = out/'patched'; patched.mkdir()
    usr_report = prepare_usr(baseline/'patched/nflasha15', patched/'nflasha15', evidence,
                             components_dir, patch_type)
    prepare_cp(baseline/'patched/nflasha8', patched/'nflasha8', evidence,
               components_dir/'cpapp-b.bin', components['cpapp-b.bin'])
    shutil.copyfile(baseline/'patched/nflasha5', patched/'nflasha5')
    templates = load(firmware/'src/templates/prepare_templates.py', 'native24_415_templates')
    replacements, template_report = templates.build_templates(inputs['original_tar'], patched/'templates',
        expected_archive_sha256=lock['original_tar']['sha256'])
    for name, path in replacements.items():
        require(path.read_bytes() == Path(base['replacements'][name]).read_bytes(), '参数模板与原基线不符')
    save(evidence/'templates.json', template_report)
    parts = {'0700_part_image/dev/'+n: patched/n for n in ('nflasha5', 'nflasha8', 'nflasha15')}
    view, final = parent.archive_overlay(inputs['original_tar'], {**replacements, **parts},
        {'dev/'+n: patched/n for n in ('nflasha5', 'nflasha8', 'nflasha15')}, evidence/'part_image.sum')
    with inputs['original_fdat'].open('rb') as stream:
        prefix = bytearray(stream.read(512+inputs['updater'].stat().st_size))
    major, minor = version.split('.')
    prefix[32:34] = bytes((int(minor, 16), int(major, 16)))
    struct.pack_into('<I', prefix, 8, zlib.crc32(prefix[12:512]))
    expected_clear = hashlib.sha256(prefix)
    with view.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 << 20), b''):
            expected_clear.update(chunk)
    print('准备官方包独立工作副本', flush=True)
    workspace = out/'workspace'
    tool.unpack(inputs['original_dat'], workspace, inputs['sony_public_key'])
    original_manifest = json.loads((workspace/'manifest.json').read_text())
    for name, path in final.items():
        if not name.endswith('.sum'):
            shutil.copyfile(path, workspace/'archive'/name)
    public = parent.regular(ROOT/'a7r5-dat-tool/keys/research-public.pem')
    private = parent.regular(ROOT/'a7r5-dat-tool/keys/research-signing-private.pem')
    require(digest(public) == PUBLIC_SHA, '研究签名公钥不符')
    print(f'研究签名 {version}，并独立逐帧验证', flush=True)
    packed = tool.pack(workspace, out/'BODYDATA.DAT', version=version, private=private, public=public)
    require(packed['plaintext_sha256'] == expected_clear.hexdigest(), '完整预期明文与封包结果不符')
    save(evidence/'dat-pack.json', packed)
    readback = out/'readback'
    print('独立解包，核对完整归档与四组件', flush=True)
    tool.unpack(out/'BODYDATA.DAT', readback, public)
    manifest = json.loads((readback/'manifest.json').read_text())
    changes = check_members(original_manifest['entries'], manifest['entries'], {n: digest(p) for n, p in final.items()})
    require(manifest['decryption']['plaintext_sha256'] == expected_clear.hexdigest(), '最终回读明文不符')
    require((readback/'format/header.bin').read_bytes() == prefix[:512] and
            (readback/'format/updater.bin').read_bytes() == inputs['updater'].read_bytes(), '版本头或原升级器不符')
    for name in ('nflasha5', 'nflasha8', 'nflasha15'):
        require(digest(readback/'archive/0700_part_image/dev'/name) == digest(patched/name), '分区回读不符')
    fs = reader((readback/'archive/0700_part_image/dev/nflasha15').read_bytes())
    for path, binding in patch_type._bindings.items():
        require(sha(fs.read_inode(fs.walk(path))) == binding.target_sha256, 'USR组件最终回读不符')
    require(sha(FatImage((readback/'archive/0700_part_image/dev/nflasha8').read_bytes()).read('/cpapp-b.bin')) == components['cpapp-b.bin'], 'CP最终回读不符')
    _, signed, signature = verify_signature(out/'BODYDATA.DAT', public.read_bytes())
    (evidence/'signed.sha256.bin').write_bytes(signed.digest())
    (evidence/'signature.bin').write_bytes(signature)
    openssl = subprocess.run(['/usr/bin/openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(public),
        '-sigfile', str(evidence/'signature.bin'), '-in', str(evidence/'signed.sha256.bin'), '-pkeyopt', 'digest:sha256'],
        capture_output=True, text=True)
    require(openssl.returncode == 0, 'OpenSSL独立验签失败')
    require(package_sources() == source_before, '封包期间源码发生变化')
    for name, path in inputs.items():
        require(digest(path) == lock[name]['sha256'], '封包期间原始输入变化')
    parent.check_upstream(PARENT/'upstream')
    filter_path = parent.regular(PARENT/'upstream/filters/FUJ_12_v45/R5NATIVE.BIN')
    require(digest(filter_path) == FILTER_SHA, '正式十二款配方不符')
    delivery = out/'delivery'; delivery.mkdir()
    shutil.copyfile(out/'BODYDATA.DAT', delivery/'BODYDATA.DAT')
    shutil.copyfile(filter_path, delivery/'R5NATIVE.BIN')
    shutil.copyfile(public, delivery/'research-public.pem')
    known = json.loads((release_dir/'KNOWN-ISSUES.json').read_text())
    save(delivery/'KNOWN-ISSUES.json', known)
    receipt = dict(schema='native24-update-package/1', version=version,
        status='OFFLINE_PACKAGE_VERIFIED_DEVICE_RETEST_REQUIRED',
        runtime_status='NOT_VERIFIED', bytes=(delivery/'BODYDATA.DAT').stat().st_size,
        sha256=digest(delivery/'BODYDATA.DAT'), components=components,
        filter_sha256=FILTER_SHA, public_key_sha256=PUBLIC_SHA,
        full_frame_validation=manifest['decryption'], signature_verified=True,
        openssl_verification=openssl.stdout.strip(), complete_plaintext_exact=True,
        independent_unpack_verified=True, plaintext_sha256=expected_clear.hexdigest(),
        updater_byte_for_byte_original=True, templates_equal_to_upstream_baseline=True,
        changed_archive_members=changes, USR_audit=usr_report,
        packaging_tests=len(test_cases), **reused,
        hardware_LDEC_verified=False,
        sources=source_before, original_inputs_unchanged=True,
        camera_io=False, device_acceptance_verified=False, imaging_verified=False,
        installability_confirmed=False, build_directory=str(out))
    save(delivery/'verification.json', receipt)
    shutil.copytree(evidence, delivery/'evidence')
    for name in source_before:
        target = delivery/'source'/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    shutil.copyfile(release_dir/'PACKAGE-README.md', delivery/'README.md')
    names = ('BODYDATA.DAT', 'R5NATIVE.BIN', 'research-public.pem')
    (delivery/'SHA256SUMS').write_text(''.join(digest(delivery/n)+'  '+n+'\n' for n in names))
    files = sorted(p for p in delivery.rglob('*') if p.is_file())
    require(not any('private' in str(p.relative_to(delivery)).lower() and p.suffix == '.pem' for p in files), '交付中出现私钥')
    (delivery/'CONTENTS.sha256').write_text(''.join(digest(p)+'  '+str(p.relative_to(delivery))+'\n' for p in files))
    (out/'INCOMPLETE.json').unlink()
    save(out/'COMPLETED.json', dict(status=receipt['status'], version=version, sha256=receipt['sha256'], camera_io=False))
    print(json.dumps({k: receipt[k] for k in ('status', 'version', 'bytes', 'sha256', 'packaging_tests')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
