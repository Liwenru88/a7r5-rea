"""固定相对偏移候选、源码与真实离线回执；不引用旧QEMU结论。"""
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import container_package as p

PINNED = {
    'verification.json': '4df5b60fb0eb7a61e7da9ad127e934771db3de08b83ad71e355dbaf93000878f',
    'build.json': 'be6e105e64d925b4a75259d0ca75e0965f8f8a91330ded147ece6ac3bf290523',
    'rebuild.json': '7d814f7d36ef5889fb1d5d729d71b7a1081f18fcf88671c68bb00bc85d5b10cc',
    'runtime-regression.json': '7c6e032ed79f21f681e08784c53f367272e4fc9655ed1fb482cf4bf57d8e1be3',
    'runtime-regression.xml': 'c20869e25f2c4985d4923af0ba6eab9ce73038d56d87047c634fc81f2392a056',
    'parity-proof.json': 'ad5da5d30e2dc42aa17ce8056e5a80db2d0dd68f2a780187ac7400f754c07a6b',
}
REQUIRED_TESTS = {
    'test_all_twenty_four_display_zero_and_signed_native_ranges_preserve_registers',
    'test_offsets_follow_native_changes_clamp_without_losing_intent_and_reset',
    'test_legacy_absolute_file_converts_to_offsets_and_same_identity_survives_restart',
    'test_first_capture_keeps_concurrent_offset_and_failed_publish_rolls_back',
    'test_eight_values_reach_original_cp_and_survive_restart_without_bin_changes',
    'test_left_restores_each_groups_last_applied_row',
    'test_parameter_center_is_forwarded_through_native_parameter_entry',
    *('test_import_uses_recipe_identity_for_saved_microadjustments['+name+']'
      for name in ('same','renamed','moved','new')),
}


def inside(root, name):
    path = Path(name)
    p.require(not path.is_absolute() and bool(path.parts) and '..' not in path.parts, '证据路径越界')
    return root/path


def regular(path):
    p.require(path.is_file() and not any(q.is_symlink() for q in (path, *path.parents))
              and not any(path.absolute().is_relative_to(q) for q in map(Path, ('/dev','/Volumes','/proc','/sys'))),
              '证据不是本地普通文件：'+str(path))
    return path


def verified(path, expected):
    p.require(p.digest(regular(path)) == expected, '固定证据或组件摘要不符：'+str(path))
    return path


def cases(path, count):
    rows = list(ET.parse(path).getroot().iter('testcase'))
    names = {row.get('name') for row in rows}
    p.require(len(rows) == len(names) == count and None not in names
              and not any(row.find(tag) is not None for row in rows for tag in ('failure','error','skipped')),
              '回归XML存在缺失、重复、失败或跳过')
    return names


def validate_cpu(cpu, names, build_sha):
    selected = cpu.get('tests', [])
    short = {name.rsplit('::',1)[-1] for name in selected}
    p.require(cpu.get('status') == 'PASS' and cpu.get('exit_code') == 0
              and cpu.get('sources_unchanged') is True and cpu.get('camera_io') is False
              and cpu.get('build_receipt_sha256') == build_sha
              and (cpu.get('AP_sha256'),cpu.get('CP_sha256')) ==
                  (p.COMPONENTS['appFw.so'],p.COMPONENTS['cpapp-b.bin'])
              and len(selected) == len(set(selected)) == len(short) == 31
              and short == names and REQUIRED_TESTS <= short,
              '相对偏移31项回归身份、用例或状态不符')


def validate_parity(proof):
    rows = proof.get('candidate_comparison', [])
    p.require(proof.get('status') == 'PASS' and proof.get('camera_io') is False
              and proof.get('candidate_AP_sha256') == p.COMPONENTS['appFw.so']
              and proof.get('native_E4_executions') == 48 and proof.get('native_packets') == 432
              and proof.get('first_twelve_records_exact') is True
              and proof.get('formal_recipe_sha256') == p.FILTER_SHA
              and len(rows) == 4 and len({r.get('name') for r in rows}) == 4
              and all(r.get('slots') == list(range(1,13)) and r.get('all_nine_packets_exact') is True for r in rows),
              '十二款上游消息比对不完整或不属于当前AP')


def verify_evidence(out, *, runtime, rebuild, archive):
    for name, expected in PINNED.items():
        verified(archive/name, expected)
    names = set()
    for line in regular(archive/'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ',1)
        p.require(name not in names, '证据清单重复')
        verified(inside(archive,name),expected)
        names.add(name)
    p.require(names | {'SHA256SUMS'} == {str(f.relative_to(archive)) for f in archive.rglob('*') if f.is_file()},
              '证据目录含未登记或缺失文件')
    frozen = [json.loads((archive/name).read_text()) for name in ('build.json','rebuild.json')]
    for folder, old in zip((runtime,rebuild),frozen):
        current = json.loads(regular(folder/'build.json').read_text())
        for build in (old,current):
            p.require(build.get('installable') is False and build.get('DAT_generated') is False
                      and build.get('camera_io') is False
                      and {k:v['sha256'] for k,v in build['components'].items()} == p.COMPONENTS,
                      '构建组件或验收状态不符')
        for key in ('owned_sources','external_sources'):
            p.require(current[key] == old[key], '构建源码与被测候选不符')
        for name, expected in p.COMPONENTS.items():
            verified(folder/name,expected)
        for name, expected in current['owned_sources'].items():
            verified(inside(p.FEATURE,name),expected)
        for name, expected in current['external_sources'].items():
            verified(inside(p.ROOT,name),expected)
        shutil.copyfile(folder/'build.json',out/('runtime-'+('build' if folder==runtime else 'rebuild')+'.json'))
    cpu = json.loads((archive/'runtime-regression.json').read_text())
    validate_cpu(cpu,cases(archive/'runtime-regression.xml',31),PINNED['build.json'])
    for name, expected in cpu['sources'].items():
        verified(inside(p.ROOT,name),expected)
    proof = json.loads((archive/'parity-proof.json').read_text())
    validate_parity(proof)
    summary = json.loads((archive/'verification.json').read_text())
    p.require(summary.get('status') == 'OFFLINE_VERIFIED' and summary.get('tune_file_version') == 2
              and summary.get('default_zero_slots') == 24 and summary.get('camera_io') is False
              and summary.get('sources') == cpu['sources'], '相对偏移摘要或源码集合不符')
    shutil.copytree(archive,out/'relative-parameters')
    p.save(out/'candidate-417.json',dict(components=p.COMPONENTS,independent_rebuild_identical=True,
        reused_CPU_tests=31,reused_QEMU_frames=0,QEMU_executed=False,camera_io=False,
        upstream_native_E4_executions=48,upstream_native_packets_compared=432,
        tune_file_version=2,default_zero_slots=24,device_acceptance_verified=False))
