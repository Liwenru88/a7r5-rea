"""从原厂升级包和当前稳定版编译产物组装容器，完成独立回读与校验。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FEATURE = HERE.parent
PARENT = FEATURE / 'dependencies/native12-combined'
ASPECT_SRC = HERE / 'source-tree/a7r5-firmware-features/photo-aspect-ratios/src'

sys.path.insert(0, str(ROOT / 'a7r5-dat-tool'))
sys.path.insert(0, str(ASPECT_SRC))

from a7r5dat import tool
from a7r5dat.codec import digest, require, verify_signature
from a7r5dat.ext2_add import Audit
from a7r5dat.ext2_image_append import AppendImagePatch, ImageBinding
from a7r5dat.ext2_patch import reader
from a7r5dat.fat import FatImage
from fat_avcam import replace as replace_avcam

USR_SHA = 'bfaf6c1e27ba7130883103e43c6d124a7364e62b18fc8044f08895a78f1ab2df'
PUBLIC_SHA = '7f65b296987df665da217de514e785f75238e686ddd18952fa425fc47e8c858a'
OUTPUT_ROOTS = ('.local', 'a7r5-firmware-features/builds')

USR_FILES = (
    '/lib/appFw.so',
    '/lib/libmpr.so',
    '/share/app/image_00_23_IPSX.uxc',
    '/share/app/image_00_32_IPSX.uxc',
)


def output_allowed(out):
    out = Path(out)
    return any(out.is_relative_to(ROOT / r) for r in OUTPUT_ROOTS)


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


def compile_default_filters():
    filters = HERE / 'filters'
    compiler_path = ROOT / 'sony-r5-colorlab/R5ColorLab/compilers/custom_filter_v4.py'
    compiler = load(compiler_path, 'stable_filter_compiler')
    config = compiler.load(filters / 'native_config.json')
    audit = json.loads((filters / 'export_audit.json').read_text(encoding='utf-8'))
    payload = compiler.pack(config)
    require(sha(payload) == audit['binary_sha256'], '精选默认滤镜包摘要与审计不符')
    return payload


def check_members(old, new, expected):
    require(len(old) == len(new), '归档成员数量变化')
    changes = []
    for a, b in zip(old, new):
        require(
            a.keys() == b.keys() and all(a[k] == b[k] for k in a if k not in ('sha256', 'crc32')),
            '归档成员元数据／布局变化',
        )
        if a != b:
            require(b['name'] in expected and b['sha256'] == expected[b['name']], '归档出现未授权变化')
            changes.append(b['name'])
    require(set(changes) == set(expected), '归档变化集合不符')
    return changes


def inventory(path):
    audit = Audit(path)
    try:
        return audit.geometry, audit.inventory()
    finally:
        audit.close()


def build_usr_bindings(usr_raw, components_dir):
    """基于锁定 USR 基线镜像与本次 4.31 编译组件动态生成 4 文件绑定表。"""
    fs = reader(usr_raw)
    bindings = {}
    for path in USR_FILES:
        inode = fs.walk(path)
        original = fs.read_inode(inode)
        candidate = (components_dir / Path(path).name).read_bytes()
        bindings[path] = ImageBinding(inode, len(original), len(candidate), sha(original), sha(candidate))
    return bindings


def prepare_usr(source, output, out, components_dir, *, source_sha=USR_SHA):
    require(digest(source) == source_sha, 'USR不匹配锁定的基线')
    before_geometry, before = inventory(source)
    raw = source.read_bytes()
    bindings = build_usr_bindings(raw, components_dir)
    patch_type = type('CandidatePatch431', (AppendImagePatch,), {'_bindings': bindings})
    patch = patch_type(raw)
    for path in bindings:
        original = patch.fs.read_inode(patch.fs.walk(path))
        patch.replace(path, original, (components_dir / Path(path).name).read_bytes())
    data, report = patch.finish()
    with output.open('xb') as stream:
        stream.write(data)
    del patch, raw, data
    after_geometry, after = inventory(output)
    require(before_geometry == after_geometry and set(before) == set(after), 'USR几何／文件树变化')
    capacity = set(range(4, 8)) | set(range(28, 32)) | set(range(40, 100))
    for name, row in before.items():
        if name not in bindings:
            require(row == after[name], 'USR无关文件／映射变化：' + name)
            continue
        target = after[name]
        binding = bindings[name]
        require(
            target['inode'] == row['inode'] == binding.inode
            and target['size'] == binding.target_bytes
            and target['sha256'] == binding.target_sha256
            and target['acl_sha256'] == row['acl_sha256'],
            'USR目标身份／内容变化',
        )
        require(
            all(a == b for i, (a, b) in enumerate(zip(row['raw'], target['raw'])) if i not in capacity),
            'USR非容量inode属性变化',
        )
    report.update(
        status='PASS',
        source_sha256=source_sha,
        target_sha256=digest(output),
        audited_paths=len(before),
        unrelated_paths_exact=True,
        geometry_unchanged=True,
    )
    save(out / 'USR.json', report)
    result = subprocess.run(
        ['/opt/homebrew/opt/e2fsprogs/sbin/e2fsck', '-fn', str(output)],
        capture_output=True,
        text=True,
    )
    (out / 'e2fsck.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, 'USR文件系统检查失败')
    return report, bindings


def prepare_cp(source, output, out, component):
    raw = source.read_bytes()
    target = bytearray(raw)
    fs = FatImage(raw)
    expected = component.read_bytes()
    component_sha = sha(expected)
    used = fs.patch(target, '/cpapp-b.bin', expected)
    require(FatImage(target).read('/cpapp-b.bin') == expected, 'FAT组件回读不符：cpapp-b.bin')
    cursor = 0
    for start, size in sorted(used):
        require(target[cursor:start] == raw[cursor:start], 'FAT分区无关字节变化：cpapp-b.bin')
        cursor = start + size
    require(target[cursor:] == raw[cursor:], 'FAT分区尾部无关字节变化：cpapp-b.bin')
    with output.open('xb') as stream:
        stream.write(target)
    save(
        out / 'CP.json',
        dict(
            status='PASS',
            component_sha256=component_sha,
            source_sha256=sha(raw),
            target_sha256=digest(output),
            unrelated_bytes_exact=True,
        ),
    )
    return component_sha


def prepare_avcam(source_nflasha3, output, out, avcam_component):
    raw = source_nflasha3.read_bytes()
    content = avcam_component.read_bytes()
    updated, report = replace_avcam(raw, content)
    with output.open('xb') as stream:
        stream.write(updated)
    require(FatImage(updated).read('/av-cam.bin') == content, 'AV-CAM.BIN FAT回读不符')
    save(out / 'AVCAM.json', report)
    return sha(content), report


def verify_dual_build(runtime_dir, rebuild_dir):
    """核对双次确定性构建（runtime 与 rebuild）全部输出组件逐字节一致。"""
    names = ('appFw.so', 'cpapp-b.bin', 'libmpr.so', 'image_00_23_IPSX.uxc', 'image_00_32_IPSX.uxc')
    if (runtime_dir / 'AV-CAM.BIN').is_file():
        names = (*names, 'AV-CAM.BIN')
    hashes = {}
    for name in names:
        a = digest(runtime_dir / name)
        b = digest(rebuild_dir / name)
        require(a == b, f'双次确定性构建不一致：{name} ({a} != {b})')
        hashes[name] = a
    return hashes


def package_stable(
    out,
    *,
    baseline,
    runtime_dir,
    rebuild_dir,
    release,
    filter_payload,
    stock_nflasha3=None,
):
    version = release['version']
    require(
        output_allowed(out) and not out.exists(),
        '输出必须是.local或a7r5-firmware-features/builds内新目录',
    )
    require(not any(p.is_symlink() for p in (out, *out.parents)), '输出路径不可含符号链接')
    out.mkdir(mode=0o700)
    evidence = out / 'evidence'
    evidence.mkdir()
    (out / 'INCOMPLETE.json').write_text('{"status":"INCOMPLETE","camera_io":false}\n')

    component_hashes = verify_dual_build(runtime_dir, rebuild_dir)
    save(evidence / 'dual-build.json', dict(status='PASS', components=component_hashes))
    print(f'{version} 双次确定性构建组件一致（共 {len(component_hashes)} 项）', flush=True)

    parent = load(PARENT / 'build.py', 'native24_431_parent')
    firmware, _ = parent.check_upstream(PARENT / 'upstream')
    sys.path.insert(0, str(firmware / 'src/lib'))

    base = json.loads(parent.regular(baseline / 'baseline.json').read_text())
    expected_base = json.loads((firmware / 'expected_outputs.json').read_text())
    require(base['passed'] and base['actual'] == {k: expected_base[k] for k in base['actual']}, '上游基线回执不符')
    inputs = {k: parent.regular(v) for k, v in base['original_inputs'].items()}
    lock = json.loads((firmware / 'inputs.lock.json').read_text())
    for name, path in inputs.items():
        require(digest(path) == lock[name]['sha256'] and path.stat().st_size == lock[name]['bytes'], '原始输入不符：' + name)
    for name in ('nflasha15', 'nflasha8', 'nflasha5'):
        require(digest(parent.regular(baseline / 'patched' / name)) == expected_base[name], '上游分区基线漂移')

    patched = out / 'patched'
    patched.mkdir()
    usr_report, usr_bindings = prepare_usr(
        baseline / 'patched/nflasha15',
        patched / 'nflasha15',
        evidence,
        runtime_dir,
    )
    cp_sha = prepare_cp(
        baseline / 'patched/nflasha8',
        patched / 'nflasha8',
        evidence,
        runtime_dir / 'cpapp-b.bin',
    )
    shutil.copyfile(baseline / 'patched/nflasha5', patched / 'nflasha5')

    partition_names = ['nflasha5', 'nflasha8', 'nflasha15']
    avcam_report = None
    if stock_nflasha3 is not None and (runtime_dir / 'AV-CAM.BIN').is_file():
        _, avcam_report = prepare_avcam(stock_nflasha3, patched / 'nflasha3', evidence, runtime_dir / 'AV-CAM.BIN')
        partition_names.insert(0, 'nflasha3')

    templates = load(firmware / 'src/templates/prepare_templates.py', 'native24_431_templates')
    replacements, template_report = templates.build_templates(
        inputs['original_tar'],
        patched / 'templates',
        expected_archive_sha256=lock['original_tar']['sha256'],
    )
    for name, path in replacements.items():
        require(path.read_bytes() == Path(base['replacements'][name]).read_bytes(), '参数模板与原基线不符')
    save(evidence / 'templates.json', template_report)

    parts = {'0700_part_image/dev/' + n: patched / n for n in partition_names}
    view, final = parent.archive_overlay(
        inputs['original_tar'],
        {**replacements, **parts},
        {'dev/' + n: patched / n for n in partition_names},
        evidence / 'part_image.sum',
    )
    with inputs['original_fdat'].open('rb') as stream:
        prefix = bytearray(stream.read(512 + inputs['updater'].stat().st_size))
    major, minor = version.split('.')
    prefix[32:34] = bytes((int(minor, 16), int(major, 16)))
    struct.pack_into('<I', prefix, 8, zlib.crc32(prefix[12:512]))
    expected_clear = hashlib.sha256(prefix)
    with view.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 << 20), b''):
            expected_clear.update(chunk)

    print('准备官方包独立工作副本', flush=True)
    workspace = out / 'workspace'
    tool.unpack(inputs['original_dat'], workspace, inputs['sony_public_key'])
    original_manifest = json.loads((workspace / 'manifest.json').read_text())
    for name, path in final.items():
        if not name.endswith('.sum'):
            shutil.copyfile(path, workspace / 'archive' / name)

    public = parent.regular(ROOT / 'a7r5-dat-tool/keys/research-public.pem')
    private = parent.regular(ROOT / 'a7r5-dat-tool/keys/research-signing-private.pem')
    require(digest(public) == PUBLIC_SHA, '研究签名公钥不符')
    print(f'研究签名 {version}，并独立逐帧验证', flush=True)
    packed = tool.pack(workspace, out / 'BODYDATA.DAT', version=version, private=private, public=public)
    require(packed['plaintext_sha256'] == expected_clear.hexdigest(), '完整预期明文与封包结果不符')
    save(evidence / 'dat-pack.json', packed)

    readback = out / 'readback'
    print('独立解包，核对完整归档与全部候选组件', flush=True)
    tool.unpack(out / 'BODYDATA.DAT', readback, public)
    manifest = json.loads((readback / 'manifest.json').read_text())
    changes = check_members(
        original_manifest['entries'],
        manifest['entries'],
        {n: digest(p) for n, p in final.items()},
    )
    require(manifest['decryption']['plaintext_sha256'] == expected_clear.hexdigest(), '最终回读明文不符')
    require(
        (readback / 'format/header.bin').read_bytes() == prefix[:512]
        and (readback / 'format/updater.bin').read_bytes() == inputs['updater'].read_bytes(),
        '版本头或原升级器不符',
    )
    for name in partition_names:
        require(digest(readback / 'archive/0700_part_image/dev' / name) == digest(patched / name), '分区回读不符：' + name)

    fs = reader((readback / 'archive/0700_part_image/dev/nflasha15').read_bytes())
    for path, binding in usr_bindings.items():
        require(sha(fs.read_inode(fs.walk(path))) == binding.target_sha256, 'USR组件最终回读不符：' + path)
    require(
        sha(FatImage((readback / 'archive/0700_part_image/dev/nflasha8').read_bytes()).read('/cpapp-b.bin')) == cp_sha,
        'CP最终回读不符',
    )
    if avcam_report is not None:
        require(
            sha(FatImage((readback / 'archive/0700_part_image/dev/nflasha3').read_bytes()).read('/av-cam.bin'))
            == component_hashes['AV-CAM.BIN'],
            'AV-CAM.BIN 最终回读不符',
        )

    _, signed, signature = verify_signature(out / 'BODYDATA.DAT', public.read_bytes())
    (evidence / 'signed.sha256.bin').write_bytes(signed.digest())
    (evidence / 'signature.bin').write_bytes(signature)
    openssl = subprocess.run(
        [
            '/usr/bin/openssl',
            'pkeyutl',
            '-verify',
            '-pubin',
            '-inkey',
            str(public),
            '-sigfile',
            str(evidence / 'signature.bin'),
            '-in',
            str(evidence / 'signed.sha256.bin'),
            '-pkeyopt',
            'digest:sha256',
        ],
        capture_output=True,
        text=True,
    )
    require(openssl.returncode == 0, 'OpenSSL独立验签失败')

    delivery = out / 'delivery'
    delivery.mkdir()
    shutil.copyfile(out / 'BODYDATA.DAT', delivery / 'BODYDATA.DAT')
    (delivery / 'R5NATIVE.BIN').write_bytes(filter_payload)
    shutil.copyfile(public, delivery / 'research-public.pem')
    save(delivery / 'KNOWN-ISSUES.json', release)

    receipt = dict(
        schema='native24-update-package/1',
        version=version,
        status='OFFLINE_PACKAGE_VERIFIED_DEVICE_RETEST_REQUIRED',
        base_version=release['base_version'],
        bytes=(delivery / 'BODYDATA.DAT').stat().st_size,
        sha256=digest(delivery / 'BODYDATA.DAT'),
        components=component_hashes,
        filter_sha256=sha(filter_payload),
        public_key_sha256=PUBLIC_SHA,
        full_frame_validation=manifest['decryption'],
        signature_verified=True,
        openssl_verification=openssl.stdout.strip(),
        complete_plaintext_exact=True,
        independent_unpack_verified=True,
        plaintext_sha256=expected_clear.hexdigest(),
        updater_byte_for_byte_original=True,
        changed_archive_members=changes,
        USR_audit=usr_report,
        AVCAM_audit=avcam_report,
        wbi_marker='WBI3',
        usr_modified_files=len(USR_FILES),
        camera_io=False,
        device_acceptance_verified=False,
        installability_confirmed=False,
        build_directory=str(out),
    )
    save(delivery / 'verification.json', receipt)
    shutil.copytree(evidence, delivery / 'evidence')
    shutil.copyfile(HERE / 'PACKAGE-README.md', delivery / 'README.md')
    names = ('BODYDATA.DAT', 'R5NATIVE.BIN', 'research-public.pem')
    (delivery / 'SHA256SUMS').write_text(''.join(digest(delivery / n) + '  ' + n + '\n' for n in names))
    (out / 'INCOMPLETE.json').unlink()
    save(out / 'COMPLETED.json', dict(status=receipt['status'], version=version, sha256=receipt['sha256'], camera_io=False))
    print(
        json.dumps(
            {k: receipt[k] for k in ('status', 'version', 'bytes', 'sha256')},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return receipt
