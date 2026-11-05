"""绑定完整旧运行时证据与新分块证据；各自保持原验证范围。"""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import xml.etree.ElementTree as ET

from a7r5dat.codec import digest, require

PAGE_TESTS = {
    'test_added_icons_have_independent_4k_blocks',
    'test_original_resources_establish_page_profile',
    'test_qemu_page_gate_rejects_both_released_long_blocks',
    'test_qemu_page_gate_accepts_original_and_fixed_resources',
    'test_added_icons_use_native_f0_blocks_instead_of_hardware_rejected_raw_blocks',
    'test_all48_icons_decode_with_fwtool_software_decoder',
}
ALLOWED_OLD_SOURCE_CHANGES = {
    'a7r5-firmware-features/native24-combined/build.py',
    'a7r5-firmware-features/native24-combined/icon_codec.py',
}


def cases(path, count):
    result = list(ET.parse(path).getroot().iter('testcase'))
    require(len(result) == count and len({x.get('name') for x in result}) == count and
            not any(x.find(k) is not None for x in result for k in ('failure','error','skipped')),
            '原始测试XML有缺失、重复、失败或跳过')
    return {x.get('name') for x in result}


def validate_page_tests(names):
    require(len(names) == 7 and {n.split('[',1)[0] for n in names} == PAGE_TESTS and
            sum(n.startswith('test_qemu_page_gate_rejects_both_released_long_blocks[') for n in names) == 2,
            '分块回归集合不符')


def inside(root, name):
    p = Path(name)
    require(not p.is_absolute() and '..' not in p.parts and bool(p.parts), '证据路径越界')
    return root/p


def verify(c, out):
    root, feature, archive = c['ROOT'], c['FEATURE'], c['ARCHIVE']
    expected = c['COMPONENTS']
    candidate = json.loads((feature/'current-candidate.json').read_text())
    c['validate_candidate'](candidate)
    require(digest(archive.with_suffix('.tar.gz')) == c['ARCHIVE_SHA'], '017审查归档身份不符')
    manifest = archive/'CONTENTS.SHA256SUMS'
    with tarfile.open(archive.with_suffix('.tar.gz')) as packed:
        require(packed.extractfile(archive.name+'/CONTENTS.SHA256SUMS').read() == manifest.read_bytes(),
                '017目录清单与固定归档不符')
    sums = {}
    for line in manifest.read_text().splitlines():
        h, name = line.split('  ',1)
        p = inside(archive,name)
        require(name not in sums and digest(p) == h, '017文件重复或漂移：'+name)
        sums[name] = h
    actual = {str(p.relative_to(archive)) for p in archive.rglob('*') if p.is_file()}
    require(len(sums) == 535 and actual == set(sums)|{'CONTENTS.SHA256SUMS'}, '017归档文件集合不符')
    for p in (archive/'source').rglob('*'):
        if p.is_file():
            require(digest(p) == digest(inside(root,str(p.relative_to(archive/'source')))),
                    '017快照源码漂移：'+str(p))
    runtime = json.loads((c['RUNTIME']/'build.json').read_text())
    for name,h in expected.items():
        require(digest(archive/'components'/name) == digest(c['RUNTIME']/name) ==
                runtime['components'][name]['sha256'] == h, '017实际组件不符：'+name)
    for name,h in runtime['owned_sources'].items():
        require(digest(inside(feature,name)) == h, '新构建源码漂移：'+name)

    # 完整82项仅按相同AP/CP复用；不把旧图标或旧构建当作新图标验收。
    cpu = json.loads((c['CPU']/'session-result.json').read_text())
    c['validate_cpu'](cpu)
    require(cases(c['CPU']/'regression.xml',82) == {n.rsplit('::',1)[-1] for n in cpu['tests']},
            '完整CPU回归XML与回执不符')
    old_build = root/'.local/native24-tabs-incident413-fix-20261103-02/build.json'
    require(cpu['build_receipt_sha256'] == digest(old_build), '原完整回归构建身份不符')
    old = json.loads(old_build.read_text())
    require(old['AP_sha256'] == runtime['AP_sha256'] == expected['appFw.so'] and
            old['CP_sha256'] == runtime['CP_sha256'] == expected['cpapp-b.bin'], '完整回归AP/CP无法复用')
    changes = {name for name,h in cpu['sources'].items() if digest(inside(root,name)) != h}
    require(changes == ALLOWED_OLD_SOURCE_CHANGES, '旧完整回归存在额外源码变化')
    previous = feature/'releases/4.14'
    require((previous/'evidence/runtime-cpu-session.json').read_bytes() == (c['CPU']/'session-result.json').read_bytes() and
            (previous/'evidence/runtime-regression.xml').read_bytes() == (c['CPU']/'regression.xml').read_bytes(),
            '完整回归与已交付原证据不符')

    new_ev = archive/'evidence'
    targeted = json.loads((new_ev/'cpu/session-result.json').read_text())
    require(targeted.get('status') == 'PASS' and targeted.get('sources_unchanged') is True and
            targeted.get('full_related_suite') is False and targeted.get('exit_code') == 0 and
            targeted.get('build_receipt_sha256') == digest(c['RUNTIME']/'build.json') and
            targeted.get('AP_sha256') == expected['appFw.so'] and targeted.get('CP_sha256') == expected['cpapp-b.bin'],
            '017定向回归来源不符')
    require(cases(new_ev/'cpu/results.xml',16) == {n.rsplit('::',1)[-1] for n in targeted['tests']}, '定向回归XML不符')
    for name,h in targeted['sources'].items():
        require(digest(inside(root,name)) == h, '定向回归源码漂移：'+name)
    validate_page_tests(cases(new_ev/'after-icons.xml',7))
    compatibility = json.loads((new_ev/'compatibility.json').read_text())
    require(compatibility.get('status') == 'PASS' and compatibility.get('independent_rebuild_identical') is True and
            compatibility['components'] == runtime['components'] and
            compatibility['changed_components'] == ['image_00_23_IPSX.uxc','image_00_32_IPSX.uxc'], '017兼容／重建回执不符')
    rebuild = json.loads((new_ev/'rebuild-build.json').read_text())
    require(rebuild['components'] == runtime['components'], '独立重建四组件不一致')

    proof = json.loads((new_ev/'qemu-proof.json').read_text())
    verifier = root/'a7r5-qemu/experiments/native24-tabs-pages/verify_receipt.py'
    require(proof.get('status') == 'PASS' and proof.get('recipe_set') == 'installed12' and
            proof.get('components') == expected and proof.get('actions') == proof.get('raw_png_frames') == 103 and
            proof.get('verifier_sha256') == digest(verifier), '新分块QEMU证据不符')
    require(Path(proof['manifest']).is_relative_to(root/'a7r5-qemu/build') and
            Path(proof['run']).is_relative_to(root/'a7r5-qemu/runs') and
            proof['manifest_sha256'] == digest(Path(proof['manifest'])), '新QEMU来源路径或摘要不符')
    for name,h in proof['files'].items():
        p = Path(name)
        require(p.is_relative_to(root/'a7r5-qemu/runs') and digest(p) == h, '新QEMU文件漂移：'+name)
    for name,row in json.loads((Path(proof['run'])/'validation-sources.json').read_text()).items():
        require(hashlib.sha256(row['text'].encode()).hexdigest() == row['sha256'] == digest(Path(name)), 'QEMU源码漂移')
    # 用同一验证器重新核对CPIO、原帧和三侧退出，不启动虚拟器。
    import subprocess
    command = [str(root/'a7r5-qemu/.venv/bin/python'),'-B',str(verifier),
               '--run',proof['run'],'--manifest',proof['manifest'],'--output',str(out/'qemu-rechecked.json')]
    env = dict(__import__('os').environ, PYTHONPATH='tools')
    checked = subprocess.run(command,cwd=root/'a7r5-qemu',env=env,capture_output=True,text=True)
    (out/'qemu-recheck.log').write_text(checked.stdout+checked.stderr)
    require(checked.returncode == 0, '新分块QEMU完整回执复核失败')

    for name in ('after-icons.xml','before-pages.xml','block-audit.json','compatibility.json','qemu-proof.json','qemu-identity.log'):
        shutil.copyfile(new_ev/name,out/name)
    shutil.copyfile(new_ev/'cpu/session-result.json',out/'targeted-cpu-session.json')
    shutil.copyfile(new_ev/'cpu/results.xml',out/'targeted-regression.xml')
    shutil.copyfile(c['CPU']/'session-result.json',out/'runtime-cpu-session.json')
    shutil.copyfile(c['CPU']/'regression.xml',out/'runtime-regression.xml')
    c['save'](out/'runtime-evidence.json', dict(status='PASS',CPU_tests=82,CPU_scope='同AP/CP原完整回归',
        targeted_tests=23,targeted_scope='新分块7项＋构建/Tab16项',QEMU_identity_tests=2,
        QEMU_production_operations=103,raw_png_frames=103,archive_sha256=c['ARCHIVE_SHA'],
        sources_unchanged=True,old_source_changes=sorted(changes),hardware_LDEC_verified=False,camera_io=False))
