"""封装六款内置滤镜、十档纵横比与二十四槽的 4.18 离线候选。"""

import argparse
from functools import partial
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
FEATURE = HERE.parent
sys.path.insert(0, str(FEATURE / 'release417'))
import container_package as p
from evidence_gate import regular

BUILD_SHA = '62b88be29409219b5a3f296709d6579f6c6004041f28a8462aad84dd6fb01c99'
AVCAM = {
    'partition_sha256': '7f5a573ce2d491035238f3a676562b49ae51eb6f21e4f6e92bacf4793f7bdce4',
    'component_sha256': '640740f3bbd7e20cf49be3288f496415b1d045020c5b9a46ea77fb187699ab04',
}
RUNTIME_AP = 'eaf0b742745696f651dbe5ee75a813bb168ac41db81706743712ab8f6d0491bf'
RUNTIME_CP = '530b45341bd17649d561bb5f906a23c505724d78e408ec2edc7dbf465eade3d5'
ASPECT = FEATURE.parent / 'photo-aspect-ratios/src'
DIRECTORIES = (ASPECT, FEATURE.parent / 'lens-af-compat/src', FEATURE.parent / 'look-factory-six/src',
               FEATURE / 'tests', FEATURE / 'runtime', FEATURE)
SUITE = ('test_legacy_six.py', 'test_tabs.py', 'test_stability.py',
         'test_background_interaction.py', 'test_relative_parameters.py', 'test_native_e4_parameters.py')
REQUIRED = {
    'test_all_24_sd_slots_and_factory_six_share_the_final_pair',
    'test_leaf_round_trip_keeps_private_values_out_of_stock_property',
    'test_boot_preserves_page_root_and_maps_new_code',
    'test_joint_matrix_and_chroma_match_historical_six',
}


def sources():
    paths = {q for directory in DIRECTORIES for q in directory.iterdir()
             if q.is_file() and q.suffix in ('.py', '.c', '.S', '.h', '.ld', '.json')
             and q.name != 'current-candidate.json'}
    paths.update((Path(p.__file__), FEATURE / 'release417/evidence_gate.py', p.PARENT / 'build.py'))
    paths.update((p.ROOT / 'a7r5-dat-tool/a7r5dat').glob('*.py'))
    materials = FEATURE.parent / 'materials'
    paths.update((materials / 'upstream-default-six').iterdir())
    paths.update(materials / n for n in ('joint-layout.json', 'six-looks.json', 'recipes.json'))
    paths.add(materials / 'source/a7r5-qemu/source/guest/look-joint.S')
    code = materials / 'source/analysis/custom-features-20261021-03/research-materials-v3/code'
    paths.update(code / n for n in ('assembler.py', 'cp_runtime.py'))
    return {str(q.relative_to(p.ROOT)): p.digest(q) for q in sorted(paths)}


def components(folder):
    receipt = regular(folder / 'build.json')
    p.require(p.digest(receipt) == BUILD_SHA, '4.18 候选构建回执摘要不符')
    entries = json.loads(receipt.read_text())['components']
    p.require(len(entries) == 73 and {'appFw.so', 'cpapp-b.bin', 'AV-CAM.BIN'} <= entries.keys(),
              '4.18 组件集合不完整')
    for name, sha in entries.items():
        p.require(p.digest(regular(folder / name)) == sha, '4.18 组件摘要不符：'+name)
    return entries


def usr_patch_type(baseline, folder, entries):
    raw = regular(baseline / 'patched/nflasha15')
    p.require(p.digest(raw) == p.USR_SHA, '4.18 USR 基底摘要不符')
    fs = p.reader(raw.read_bytes())
    bindings = {}
    for name, sha in entries.items():
        if name in ('AV-CAM.BIN', 'cpapp-b.bin'):
            continue
        target = '/lib/' if name == 'appFw.so' else '/share/app/'
        path = target + name
        inode = fs.walk(path)
        old = fs.read_inode(inode)
        bindings[path] = p.ImageBinding(inode, len(old), (folder / name).stat().st_size, p.sha(old), sha)
    p.require(len(bindings) == 71, 'USR 文件替换集合不符')
    return type('Candidate418Patch', (p.AppendImagePatch,), {'_bindings': bindings})


def verify_tests(evidence, *, args, entries, result):
    for folder in (args.components, args.rebuild):
        p.require(components(folder) == entries, '两次独立构建不一致')
    shutil.copyfile(args.components / 'build.json', evidence / 'candidate-build.json')
    shutil.copyfile(args.rebuild / 'build.json', evidence / 'candidate-rebuild.json')
    p.require(p.digest(regular(args.runtime / 'appFw.so')) == RUNTIME_AP, '4.17 AP 前像不符')
    p.require(p.digest(regular(args.test_runtime / 'cpapp-b.bin')) == RUNTIME_CP, '镜头 AF CP 前像不符')
    env = dict(os.environ, A7R5_LEGACY_SIX_BUILD=str(args.components),
        A7R5_LEGACY_SIX_RUNTIME=str(args.runtime), A7R5_NATIVE24_BUILD=str(args.test_runtime),
        A7R5_LEGACY_SIX_STOCK_CP=str(args.baseline / 'inputs/cpapp-b.bin'),
        A7R5_ASPECT_AP_INPUT=str(args.runtime / 'appFw.so'),
        A7R5_ASPECT_CP_INPUT=str(args.test_runtime / 'cpapp-b.bin'),
        A7R5_ASPECT_STOCK_USR=str(args.baseline / 'inputs/nflasha15'),
        A7R5_ASPECT_NATIVE24_IMAGES=str(args.runtime))
    env.pop('A7R5_NATIVE24_EVIDENCE', None)
    xml = evidence / 'cpu.xml'
    command = [str(args.cpu_python), '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
               '--tb=short', '--junitxml='+str(xml), str(ASPECT),
               *(str(FEATURE / 'tests' / name) for name in SUITE)]
    print('运行 4.18 指令回放和 24 槽状态回归', flush=True)
    with (evidence / 'cpu.log').open('xb') as log:
        test = subprocess.run(command, env=env, cwd=p.ROOT, stdout=log, stderr=subprocess.STDOUT)
    p.require(test.returncode == 0, 'CPU 回归失败，见 '+str(evidence / 'cpu.log'))
    cases = list(ET.parse(xml).getroot().iter('testcase'))
    p.require(cases and REQUIRED <= {row.get('name') for row in cases}
              and not any(row.find(tag) is not None for row in cases for tag in ('failure', 'error', 'skipped')),
              'CPU 回归包含跳过、失败或缺失用例')
    result['reproduced_CPU_tests'] = len(cases)
    p.save(evidence / 'cpu.json', dict(status='PASS', tests=len(cases), candidate=entries,
        original_runtime_AP_sha256=RUNTIME_AP, host_fixture=True, camera_io=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'components', 'rebuild', 'runtime', 'test-runtime', 'cpu-python', 'output'):
        parser.add_argument('--'+name, type=lambda value: Path(value).absolute(), required=True)
    args = parser.parse_args()
    p.require(args.components.resolve() != args.rebuild.resolve(), '需要两个独立构建目录')
    entries = components(args.components)
    patch_type = usr_patch_type(args.baseline, args.components, entries)
    result = dict(reused_CPU_tests=0, reused_QEMU_frames=0, QEMU_executed=False,
                  independent_rebuild_identical=True, fixed_looks=6, import_slots=24, photo_aspect_ratios=10)
    p.package(args.output, baseline=args.baseline, components_dir=args.components,
        components=entries, patch_type=patch_type, version='4.18', release_dir=HERE,
        evidence_check=partial(verify_tests, args=args, entries=entries, result=result),
        reused=result, source_inventory=sources, avcam=AVCAM, invalidate_wbi=True)


if __name__ == '__main__':
    main()
