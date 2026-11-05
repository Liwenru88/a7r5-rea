"""只读复核第三十三批准备产物及输入；不生成DAT、不签名、不操作设备。"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import re
import subprocess

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'a7r5-dat-tool/a7r5dat').is_dir())
LOCAL = ROOT/'.local/fixed-custom-filters'
FEATURE = ROOT/'a7r5-firmware-features/custom-filters'
SPEC = ROOT/'a7r5-firmware-features/specs/001-fixed-custom-filters'


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(relative):
    return json.loads((LOCAL/relative).read_text())


def verify(output):
    output = output.resolve()
    require(output.is_relative_to(LOCAL) and not output.exists(), '只写全新本任务JSON')
    core = read('continuation33-software/verification.json')
    require(core['status'] == 'PASS_SOFTWARE_BUILD_AND_HOST_CONTRACTS' and
            '202 passed' in core['commands'][-1]['stdout'], '缺少核心行为证据')
    for name, expected in core['source_sha256'].items():
        require(digest(ROOT/name) == expected, '核心源码漂移：'+name)
    for name, row in core['artifacts'].items():
        require(digest(LOCAL/'continuation33-software'/name) == row['sha256'], '核心产物变化')
    staging = read('continuation33-full-unsigned-usr-v2/verification.json')
    require(staging['status'] == 'UNSIGNED_USR_CONTENT_VERIFIED_NOT_INSTALLABLE' and
            staging['source_unchanged'] and staging['new_entries'] == 1047 and
            staging['resource_replacements'] == 70 and staging['added_dsos'] == 4 and
            not staging['installable_firmware'] and not staging['CP_updated'] and not staging['UI_published'], 'staging越界')
    image = Path(staging['output'])
    require(image.is_file() and not image.is_symlink() and image.stat().st_size == 410652672 and
            digest(image) == staging['output_sha256'], '内容回执没有对应的真实输出')
    require(read('continuation33-full-unsigned-usr-v2/e2fsck.json')['exit_code'] == 0, '缺少独立文件系统绿灯')
    manifest = LOCAL/'continuation33-package/loader-staging-input-v1.json'
    require(digest(manifest) == staging['manifest_sha256'], 'staging清单变化')
    m = json.loads(manifest.read_text())
    for row in [*m['dsos'], *m['resource_replacements'], m['ap']['receipt'], m['build']]:
        p = Path(row['path'])
        require(p.is_file() and p.stat().st_size == row['bytes'] and digest(p) == row['sha256'], '冻结组件变化：'+str(p))
    loader_source = FEATURE/'experiments/packaging406/loader'
    for name, expected in m['source_files'].items():
        require(digest(loader_source/name) == expected, '装载准备源码漂移：'+name)
    review = read('continuation33-staging-review/review-final.json')
    source = FEATURE/'experiments/packaging406/stage_unsigned_usr.py'
    require(digest(source) == review['source_sha256'] and review['status'] == 'NO_REMAINING_SUBSTANTIVE_FINDING', '审查源码不匹配')
    tail = read('continuation33-staging-review/publication-tail-fixed.json')
    require(tail['source_sha256'] == digest(source) and tail['status'] == 'PASS' and len(tail['cases']) == 4,
            '缺少当前发布故障验证')
    placement = read('continuation33-placement-integrated/placement.json')
    require(placement['status'] == 'BLOCKED_NO_COMPLETE_CP_EXECUTABLE_PLACEMENT' and
            placement['modules'][0]['sha256'] == core['artifacts']['cp-requests/cp-requests.elf']['sha256'] and
            placement['modules'][0]['initialized_readonly_bytes'] == 4348 and
            placement['verified_reclaimed_tail']['bytes'] == 408, '当前CP门槛不符')
    require(read('continuation33-placement-integrated/bounded-link.json')['expected_rejection'], '未核实际有界链接拒绝')
    inputs = [(Path('/Users/wenruli/Desktop/索尼/BODYDATA.DAT'), '3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2'),
              (Path(m['source_usr']['path']), m['source_usr']['sha256']),
              (ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio', 'c01948220e1cced7f4e1d6a6dd28221c587050214d32cc405291cc00d2f1ed80')]
    for p, expected in inputs:
        require(digest(p) == expected, '原输入变化：'+str(p))
    sources = sorted((FEATURE/'native').glob('*.[chS]')) + sorted((FEATURE/'native').glob('*.ld'))
    sources += sorted((FEATURE/'experiments/packaging406').rglob('*.py'))
    sources += sorted((FEATURE/'experiments/packaging406/loader').glob('*.[ch]'))
    sources += [ROOT/'a7r5-dat-tool/a7r5dat'/n for n in ('ext2_add.py', 'ext2_image_append.py', 'ext2_patch.py', 'ext2read.py')]
    sources += [FEATURE/'a7filters'/n for n in ('ui_resources.py', 'ui_icons.py', 'ap_ui_hooks.py')]
    for path in sources:
        if path.suffix == '.py':
            ast.parse(path.read_text(), filename=str(path))
    documents = [SPEC/n for n in ('integration-33-packaging.md', 'mainline-progress.md', 'tasks.md', 'design.md', 'verification.md')]
    for document in documents:
        for target in re.findall(r'\]\(([^)\n]+)\)', document.read_text()):
            if target.startswith(('http', '#')):
                continue
            require((document.parent/target.split('#', 1)[0]).resolve().exists(), '文档引用不存在：'+target)
    index = subprocess.run(['git', 'diff', '--cached', '--name-only'], cwd=ROOT, capture_output=True, text=True)
    require(index.returncode == 0 and not index.stdout.strip(), '本任务未授权修改暂存区')
    result = dict(status='VERIFIED_UNSIGNED_STAGING_ONLY', overall='NOT_VERIFIED',
        current_core_sources_unchanged=True, core_tests='202 passed in 28.02s',
        source_sha256={str(p.relative_to(ROOT)): digest(p) for p in [*sources, *documents]},
        original_inputs={str(p): digest(p) for p, _ in inputs},
        staged_image=dict(path=str(image), bytes=image.stat().st_size, sha256=digest(image)),
        stage_receipt_sha256=digest(LOCAL/'continuation33-full-unsigned-usr-v2/verification.json'),
        index_unchanged_empty=True, CP_executable_placement='BLOCKED_4348_VS_408',
        installable_firmware=False, signed=False, DAT_created=False,
        target_executed=False, hardware_simulation=False, camera_io=False, private_key_accessed=False)
    with output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: result[k] for k in ('status', 'overall', 'core_tests', 'staged_image', 'installable_firmware')},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    verify(parser.parse_args().output)
