#!/usr/bin/env python3
"""在新目录重建远端4.36并整合本地功能；不包含设备入口。"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import struct
import zlib
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UPSTREAM_COMMIT = '47f8f022628aef8de382a613ea4d11cd51d0a965'
UPSTREAM_SNAPSHOT_SHA = 'c81e5b4681479eccf99224aae820adabaf139df3fb758a1e1927d81787e0ad95'
VERSION = '4.11'
PUBLIC_SHA = '7f65b296987df665da217de514e785f75238e686ddd18952fa425fc47e8c858a'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def regular(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), '拒绝链接路径：'+str(path))
    require(not any(path.is_relative_to(p) for p in map(Path, ('/dev', '/Volumes', '/proc', '/sys'))),
            '拒绝设备或外部介质路径')
    require(path.is_file(), '缺少普通文件：'+str(path))
    return path


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_upstream(upstream):
    snapshot = upstream/'UPSTREAM_SNAPSHOT.json'
    if snapshot.is_file():
        require(sha(regular(snapshot)) == UPSTREAM_SNAPSHOT_SHA, '上游快照清单身份不符')
        record = json.loads(snapshot.read_text())
        require(record['schema'] == 'a7r5-upstream-source-snapshot/1' and
                record['commit'] == UPSTREAM_COMMIT, '上游快照提交不符')
        names = record['files']
        actual = set()
        for path in upstream.rglob('*'):
            require(not path.is_symlink(), '上游快照不接受符号链接')
            if path.is_file() and path.name != '.DS_Store':
                actual.add(path.relative_to(upstream).as_posix())
        require(actual == set(names) | {'UPSTREAM_SNAPSHOT.json'}, '上游快照存在缺失或未登记文件')
        for name, row in names.items():
            require(not name.startswith('/') and all(p not in ('', '.', '..') for p in name.split('/')),
                    '上游快照路径不合法')
            path = regular(upstream/name)
            require(path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], '上游快照文件不符：'+name)
    else:
        identity = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
        require(identity == UPSTREAM_COMMIT, '上游提交不符')
        require(subprocess.run(['git', '-C', str(upstream), 'diff', '--quiet', 'HEAD', '--', 'firmware/r5']).returncode == 0,
                '上游构建源码有未记录修改')
    firmware = upstream/'firmware/r5'
    lock = json.loads((firmware/'sources.lock.json').read_text())
    for name, digest in lock.items():
        require(sha(regular(firmware/name)) == digest, '上游源码锁不符：'+name)
    return firmware, lock


def implementation_sources():
    """仅绑定本模块实施源，避免归档或本次构建输出递归进入来源清单。"""
    paths = [HERE/name for name in ('build.py', 'patches.py', 'integration.S', 'integration.ld', 'selection.S', 'menu_font.py', 'menu-font.c')]
    paths.extend(sorted(path for path in (HERE/'tests').iterdir()
                        if path.is_file() and path.suffix in {'.py', '.c'}))
    return {str(path.relative_to(ROOT)): sha(regular(path)) for path in paths}


def prepare_inputs(original, folder, firmware):
    """逐帧解密并提取固定原厂材料，不依赖远端未公开签名身份。"""
    sys.path.insert(0, str(ROOT/'a7r5-dat-tool'))
    sys.path.insert(0, str(firmware/'src/lib'))
    from a7r5dat import tool
    from fwtool.sony.fdat import FdatHeader, FdatFileSystemHeader
    from image_io import geometry
    import io
    lock = json.loads((firmware/'inputs.lock.json').read_text())
    def check(key, path):
        require(path.stat().st_size == lock[key]['bytes'] and sha(path) == lock[key]['sha256'],
                '原始输入不符：'+key)
    original = regular(original)
    check('original_dat', original)
    sony = regular(ROOT/'a7r5-dat-tool/keys/sony-original-public.pem')
    check('sony_public_key', sony)
    _, signature = tool.verify_key(original, sony)
    folder.mkdir(mode=0o700)
    fdat = folder/'firmware.fdat'
    print('逐帧核对并解密官方4.00', flush=True)
    with fdat.open('xb') as target:
        frame_check = tool.decrypt_to(original, target)
    check('original_fdat', fdat)
    with fdat.open('rb') as source:
        header = FdatHeader.unpack(io.BytesIO(source.read(512)))
        fs = FdatFileSystemHeader.unpack(header.fileSystemHeaders, 0)
        require((header.model, header.versionMajor, header.versionMinor) == (0x11030080, 4, 0),
                '原厂机型／版本不符')
        for key, name, offset, length in [
            ('updater', 'updater.img', fs.offset, fs.size),
            ('original_tar', 'firmware.tar', header.firmwareOffset, header.firmwareSize)]:
            source.seek(offset)
            with (folder/name).open('xb') as target:
                left = length
                while left:
                    chunk = source.read(min(left, 4 << 20))
                    require(chunk, '原始输入截短')
                    target.write(chunk)
                    left -= len(chunk)
            check(key, folder/name)
    paths = dict(original_dat=original, original_fdat=fdat, original_tar=folder/'firmware.tar',
                 updater=folder/'updater.img', sony_public_key=sony)
    with tarfile.open(paths['original_tar'], 'r:') as archive:
        for name in ('nflasha5', 'nflasha8', 'nflasha15'):
            member = archive.getmember('0700_part_image/dev/'+name)
            require(member.isfile(), '分区不是普通成员')
            with archive.extractfile(member) as source, (folder/name).open('xb') as target:
                shutil.copyfileobj(source, target, 4 << 20)
            check('stock_'+name, folder/name)
            paths['stock_'+name] = folder/name
    for key, partition, component in [('stock_ap', 'nflasha15', 'appFw.so'),
                                      ('stock_cp', 'nflasha8', 'cpapp-b.bin')]:
        raw, _, _, _ = geometry(folder/partition, component)
        (folder/component).write_bytes(raw)
        check(key, folder/component)
        paths[key] = folder/component
    save(folder/'inputs.json', {k: str(v) for k, v in paths.items()})
    save(folder/'verification.json', dict(signature=signature, frames=frame_check,
         official_inputs_matched=True, signing_identity_not_used=True, camera_io=False))
    return paths


def baseline(upstream, original, out):
    firmware, lock = check_upstream(upstream)
    paths = prepare_inputs(original, out/'inputs', firmware)
    work = out/'work'
    shutil.copytree(firmware/'src', work)
    inputs = work/'inputs'
    inputs.mkdir()
    for key, name in [('original_dat', 'original.DAT'), ('original_fdat', 'original.fdat'),
                      ('updater', 'updater.img'), ('sony_public_key', 'sony_public.pem')]:
        (inputs/name).symlink_to(paths[key])
    original_builder = load_module(firmware/'build.py', 'native12_upstream_builder')
    recipes = json.loads((work/'dependencies/baseline_recipes.json').read_text())
    for key, source, target in [('ap_baseline', 'stock_ap', 'ap_baseline.so'),
                                ('cp_baseline', 'stock_cp', 'cp_baseline.bin'),
                                ('nflasha15_layout', 'stock_nflasha15', 'nflasha15')]:
        original_builder.apply_recipe(paths[source], inputs/target, recipes[key])
    patched = out/'patched'
    patched.mkdir()
    evidence = out/'evidence'
    evidence.mkdir()
    original_builder.apply_recipe(paths['stock_nflasha5'], patched/'nflasha5', recipes['nflasha5'])
    print('实际重编远端AP、Gamma入口与CP', flush=True)
    for script, args in [('import/build_ap_image.py', ['--output', str(patched)]),
                          ('gamma/getter_gates.py', []), ('cp/build_cp.py', [])]:
        original_builder.run(work/script, *args)
    shutil.copyfile(work/'cp/cp423.NONINSTALLABLE.bin', patched/'cpapp-b.bin')
    partitions = {
        'AP': original_builder.integrate(inputs/'nflasha15', patched/'nflasha15', patched/'appFw.so', 'appFw.so'),
        'CP': original_builder.integrate(paths['stock_nflasha8'], patched/'nflasha8', patched/'cpapp-b.bin', 'cpapp-b.bin')}
    sys.path[:0] = [str(work/'lib'), str(work/'templates')]
    from prepare_templates import build_templates
    replacements, templates = build_templates(paths['original_tar'], patched/'templates',
        expected_archive_sha256=sha(paths['original_tar']))
    save(evidence/'templates.json', templates)
    expected = json.loads((firmware/'expected_outputs.json').read_text())
    actual = {'AP': sha(patched/'appFw.so'), 'CP': sha(patched/'cpapp-b.bin'),
              **{name: sha(patched/name) for name in ('nflasha15', 'nflasha8', 'nflasha5')}}
    matched = {name: value == expected[name] for name, value in actual.items()}
    report = dict(passed=all(matched.values()), upstream_commit=UPSTREAM_COMMIT,
        expected=expected, actual=actual, matched=matched, partitions=partitions,
        source_lock_entries=len(lock), source_lock_sha256=sha(firmware/'sources.lock.json'),
        original_inputs={k: str(v) for k, v in paths.items()},
        replacements={k: str(v) for k, v in replacements.items()},
        compiler=subprocess.check_output(['clang', '--version'], text=True),
        camera_io=False, complete_DAT_reproduction_claimed=False)
    save(out/'baseline.json', report)
    require(report['passed'], '原版组件未精确复现，查看baseline.json；不继续封包')
    return report


def archive_overlay(source, replacements, sums, output):
    """从原始TAR生成定长覆盖视图，完整保留所有原始归档头。"""
    from image_io import update_sum
    from overlay import Overlay
    with tarfile.open(source, 'r:') as archive:
        members = {m.name: m for m in archive.getmembers()}
        name = '0701_part_image_sum/part_image.sum'
        raw = archive.extractfile(name).read().decode('ascii')
        text, changed = update_sum(raw, sums, {k: v.stat().st_size for k,v in sums.items()})
        require(len(changed) == 3, '分区清单更新集合不符')
        output.write_text(text)
        replacements = {**replacements, name: output}
        ranges = []
        for name, path in replacements.items():
            member = members[name]
            require(member.isfile() and path.stat().st_size == member.size, '覆盖归档范围或大小不符')
            ranges.append((member.offset_data, member.offset_data+member.size, path))
    return Overlay(source, sorted(ranges)), replacements


def package_candidate(upstream, baseline_dir, out):
    """正常研究签名并用独立解包器复核后，才交付新文件。"""
    import patches
    firmware, source_lock = check_upstream(upstream)
    record = json.loads(regular(baseline_dir/'baseline.json').read_text())
    require(record['passed'] and record['upstream_commit'] == UPSTREAM_COMMIT, '基线回执不符')
    expected = json.loads((firmware/'expected_outputs.json').read_text())
    for key, name in [('AP','appFw.so'), ('CP','cpapp-b.bin'), *[(n,n) for n in ('nflasha5','nflasha8','nflasha15')]]:
        require(sha(regular(baseline_dir/'patched'/name)) == expected[key], '基线组件已变化：'+key)
    paths = {k: regular(v) for k,v in record['original_inputs'].items()}
    input_lock = json.loads((firmware/'inputs.lock.json').read_text())
    for key, path in paths.items():
        require(path.stat().st_size == input_lock[key]['bytes'] and sha(path) == input_lock[key]['sha256'],
                '原始输入已变化：'+key)
    sys.path[:0] = [str(ROOT/'a7r5-dat-tool'), str(firmware/'src/lib')]
    from a7r5dat import tool
    from image_io import geometry, digest_stream
    source_builder = load_module(firmware/'build.py', 'native12_package_upstream_builder')
    evidence, patched = out/'evidence', out/'patched'
    evidence.mkdir()
    patched.mkdir()
    replacements = {k: regular(v) for k,v in record['replacements'].items()}
    base_parts = {'0700_part_image/dev/'+n: baseline_dir/'patched'/n for n in ('nflasha5','nflasha8','nflasha15')}
    base_view, _ = archive_overlay(paths['original_tar'], {**replacements, **base_parts},
        {'dev/'+n: p for n,p in ((Path(k).name,v) for k,v in base_parts.items())}, evidence/'baseline-part_image.sum')
    with base_view.open('rb') as stream:
        base_archive_sha = digest_stream(stream)
    require(base_archive_sha == expected['archive'], '远端完整原版归档未精确复现')
    save(evidence/'baseline-archive.json', dict(passed=True, archive_sha256=base_archive_sha,
         expected_sha256=expected['archive'], signing_identity_used=False))
    print('运行真实组件集成回归', flush=True)
    environment = dict(os.environ, A7R5_NATIVE12_BASELINE=str(baseline_dir), A7R5_NATIVE12_UPSTREAM=str(upstream))
    command = [sys.executable, '-B', '-m', 'pytest', '-p', 'no:cacheprovider', str(HERE/'tests'), '-q',
               '--tb=short', '--junitxml='+str(evidence/'regression.xml')]
    checked = subprocess.run(command, env=environment, capture_output=True, text=True)
    (evidence/'regression.log').write_text(checked.stdout+checked.stderr)
    require(checked.returncode == 0, '合并回归失败，不封包')
    suites = ET.parse(evidence/'regression.xml').getroot().findall('.//testsuite')
    regression = {key: sum(int(s.attrib.get(key, 0)) for s in suites)
                  for key in ('tests', 'failures', 'errors', 'skipped')}
    require(regression['tests'] >= 17 and regression['failures'] == regression['errors'] == regression['skipped'] == 0,
            '回归证据不完整')
    ap, ap_report = patches.ap_patch((baseline_dir/'patched/appFw.so').read_bytes())
    font = load_module(HERE/'menu_font.py', 'native12_package_menu_font')
    from ext2read import Ext2
    from image_io import close_image
    usr = Ext2(str(baseline_dir/'patched/nflasha15'))
    try:
        require(hashlib.sha256(usr.read_inode(usr.walk('lib/libObj.so'))).hexdigest() == font.LIBOBJ_SHA,
                '原厂字体库与覆盖层约定不符')
    finally:
        close_image(usr)
    font_ap, font_report = font.build(ap, evidence/'menu-font')
    ap = font_ap.read_bytes()
    cp, cp_report = patches.cp_patch((baseline_dir/'patched/cpapp-b.bin').read_bytes(), patched)
    (patched/'appFw.so').write_bytes(ap)
    (patched/'cpapp-b.bin').write_bytes(cp)
    save(evidence/'AP.json', ap_report)
    save(evidence/'CP.json', cp_report)
    partitions = {}
    for key, name, component in [('AP','nflasha15','appFw.so'), ('CP','nflasha8','cpapp-b.bin')]:
        partitions[key] = source_builder.integrate(baseline_dir/'patched'/name,
            patched/name, patched/component, component)
    shutil.copyfile(baseline_dir/'patched/nflasha5', patched/'nflasha5')
    fsck = subprocess.run(['/opt/homebrew/opt/e2fsprogs/sbin/e2fsck', '-fn', str(patched/'nflasha15')],
                          capture_output=True, text=True)
    (evidence/'e2fsck.log').write_text(fsck.stdout+fsck.stderr)
    require(fsck.returncode == 0, 'USR文件系统检查失败')
    parts = {'0700_part_image/dev/'+n: patched/n for n in ('nflasha5','nflasha8','nflasha15')}
    final_view, final_replacements = archive_overlay(paths['original_tar'], {**replacements, **parts},
        {'dev/'+n: patched/n for n in ('nflasha5','nflasha8','nflasha15')}, evidence/'combined-part_image.sum')
    with final_view.open('rb') as stream:
        final_archive_sha = digest_stream(stream)
    # 完整预期明文由另一套归档视图构造，与封包器的工作目录无共享输出。
    with paths['original_fdat'].open('rb') as stream:
        prefix = bytearray(stream.read(512+paths['updater'].stat().st_size))
    prefix[32] = int(VERSION.split('.')[1], 16)
    struct.pack_into('<I', prefix, 8, zlib.crc32(prefix[12:512]))
    clear_hash = hashlib.sha256(prefix)
    with final_view.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 << 20), b''):
            clear_hash.update(chunk)
    expected_plaintext = clear_hash.hexdigest()
    print('准备独立封包工作副本', flush=True)
    workspace = out/'pack-workspace'
    tool.unpack(paths['original_dat'], workspace, paths['sony_public_key'])
    original_manifest = json.loads((workspace/'manifest.json').read_text())
    for name, source in final_replacements.items():
        if name.endswith('.sum'):
            continue  # 让本地封包器从原清单独立计算，不能直接提交预期清单。
        shutil.copyfile(source, workspace/'archive'/name)
    public = regular(ROOT/'a7r5-dat-tool/keys/research-public.pem')
    private = regular(ROOT/'a7r5-dat-tool/keys/research-signing-private.pem')
    require(sha(public) == PUBLIC_SHA, '本地研究公钥身份不符')
    packaging = out/'packaging'
    packaging.mkdir()
    candidate = packaging/'BODYDATA.DAT'
    print(f'正常研究签名{VERSION}，并逐帧回读', flush=True)
    packed = tool.pack(workspace, candidate, version=VERSION, private=private, public=public)
    require(packed['plaintext_sha256'] == expected_plaintext, '独立归档视图与封包明文不一致')
    print('独立完整解包最终候选', flush=True)
    readback = out/'readback'
    tool.unpack(candidate, readback, public)
    final_manifest = json.loads((readback/'manifest.json').read_text())
    changes = []
    require(len(original_manifest['entries']) == len(final_manifest['entries']), '归档成员数量变化')
    for old, new in zip(original_manifest['entries'], final_manifest['entries']):
        require(old.keys() == new.keys() and all(old[k] == new[k] for k in old if k not in ('sha256','crc32')),
                '归档成员身份／布局变化')
        if old != new:
            name = old['name']
            require(name in final_replacements and new['sha256'] == sha(final_replacements[name]),
                    '最终成员内容不符：'+name)
            changes.append(name)
    require(set(changes) == set(final_replacements), '改动成员集合不符')
    require((readback/'format/header.bin').read_bytes() == prefix[:512] and
            (readback/'format/updater.bin').read_bytes() == paths['updater'].read_bytes(), '头或原始updater变化')
    require(final_manifest['decryption']['plaintext_sha256'] == expected_plaintext, '解包完整明文不符')
    for name, component in [('nflasha15','appFw.so'), ('nflasha8','cpapp-b.bin')]:
        raw, _, _, _ = geometry(readback/'archive/0700_part_image/dev'/name, component)
        require(raw == (patched/component).read_bytes(), '最终内部组件回读不符：'+component)
    # 用OpenSSL再次验签，不与PyCryptodome封包器共用验签实现。
    from signature import inspect, hashes_and_signature, openssl_verify
    layout = inspect(candidate)
    signed, _, _, signature = hashes_and_signature(candidate, layout)
    (evidence/'signature.bin').write_bytes(signature)
    (evidence/'signed.sha256.bin').write_bytes(signed.digest())
    openssl = openssl_verify(public, evidence/'signed.sha256.bin', evidence/'signature.bin')
    for key, path in paths.items():
        require(sha(path) == input_lock[key]['sha256'], '执行期间原始输入变化：'+key)
    filter_source = regular(upstream/'filters/FUJ_12_v45/R5NATIVE.BIN')
    filter_sha = '19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6'
    require(sha(filter_source) == filter_sha, '十二款滤镜身份不符')
    delivery = out/'delivery'
    delivery.mkdir()
    os.link(candidate, delivery/'BODYDATA.DAT')
    shutil.copyfile(filter_source, delivery/'R5NATIVE.BIN')
    shutil.copyfile(public, delivery/'research-public.pem')
    result = dict(status='OFFLINE_PACKAGE_VERIFIED_WITH_FINDINGS_DEVICE_UNTESTED', version=VERSION,
        upstream_commit=UPSTREAM_COMMIT, upstream_baseline_exact=True,
        output=str(delivery/'BODYDATA.DAT'), bytes=candidate.stat().st_size, sha256=sha(candidate),
        filter_sha256=filter_sha, public_key_sha256=PUBLIC_SHA, signature_verified=True,
        openssl_verification=openssl, plaintext_sha256=expected_plaintext, archive_sha256=final_archive_sha,
        full_frame_validation=True, frame_count=final_manifest['decryption']['frame_count'],
        independent_unpack_verified=True, updater_byte_for_byte_original=True,
        changed_archive_members=changes, partitions=partitions, e2fsck_exit=fsck.returncode,
        features=['upstream-4.36-native12-Fn-R6ST-AWB-cold-resume', 'local-selfcontained-FL2-FL3',
                  'local-target-NTSC-skip', 'local-type1-sound-selector', 'local-photo-marker-menu',
                  'private-menu-Chinese-font'],
        menu_font_patch=font_report,
        regression=regression,
        original_inputs_unchanged=True, camera_io=False, device_acceptance_verified=False,
        photo_overlay_verified=False, sound_playback_verified=False, boot_recovery_verified=False,
        native_filter_apply_verified=False,
        known_findings=['QEMU中原生E4刷新未完成，滤镜成功应用尚未验收',
                        'Portra400左列简称仍裁切，右栏Portra400NB全名可见'],
        sources=implementation_sources())
    save(delivery/'verification.json', result)
    (delivery/'SHA256SUMS').write_text(result['sha256']+'  BODYDATA.DAT\n'+filter_sha+'  R5NATIVE.BIN\n')
    (delivery/'交付说明.md').write_text(
        f'# 研究版{VERSION}整合候选\n\n沿用远端固定4.36十二滤镜、Fn与颜色参数路线，加本地自包含FL2／FL3、指定NTSC提示关闭、电子快门声音选择器和照片标记菜单，纳入中文字体修复。'
        '\n\nBODYDATA.DAT与R5NATIVE.BIN为一组；BIN为远端v4.5十二款配方。使用本项目既有研究公钥签名，原updater不变。'
        '当前机身信任、版本准入和恢复条件未读取；不适用于仅信任远端公钥的机身。'
        '\n\n完整签名、736841帧及独立解包核对通过。声音实际播放、照片标记画面叠加、正常启动、取景／JPG、掉电恢复均未实机验收。'
        '这不是Sony官方固件，也不是远端原版4.36；离线通过不等于可以安全安装。本次没有连接相机或写卡。'
        '\n\n已知问题：QEMU中原生E4刷新未完成，页面仍提示“应用失败，请重试”，滤镜成功应用尚未验收；Portra400左列简称仍裁切，右栏全名可见。'
        '十二配置的读取、内部文件回读、CP参数封存及名称显示通过，不代表上述问题已经修复。QEMU软件介质与OSAL适配仅用于离线实验，不进入升级包。'
        '\n\n详细证据见verification.json与上级evidence目录。既有32槽工程和历史DAT未修改。\n')
    print(json.dumps({k:result[k] for k in ('status','output','bytes','sha256','frame_count')}, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, default=HERE/'upstream', help='目录内固定快照或精确Git检出')
    parser.add_argument('--original', type=Path, default=ROOT/'a7r5-firmware-images/官方升级包/BODYDATA.DAT')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--phase', choices=('baseline', 'package'), default='baseline')
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), '输出目录必须不存在')
    require(args.output.parent.is_dir(), '输出父目录不存在')
    args.output.mkdir(mode=0o700)
    try:
        if args.phase == 'baseline':
            baseline(args.upstream.absolute(), args.original, args.output.absolute())
        else:
            require(args.baseline is not None, '封包需要已有精确基线')
            package_candidate(args.upstream.absolute(), args.baseline.absolute(), args.output.absolute())
    except Exception as error:
        save(args.output/'FAILED.json', dict(error=str(error), camera_io=False, completed=False))
        raise


if __name__ == '__main__':
    main()
