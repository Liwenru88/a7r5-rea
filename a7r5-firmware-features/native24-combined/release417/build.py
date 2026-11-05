"""封装左键切组与两组应用记忆的固定 4.17 候选。"""
import argparse
from dataclasses import replace
from functools import partial
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'release415'))
import build as packaging

ROOT = packaging.ROOT
FEATURE = HERE.parent
RELEASE = FEATURE/'releases/4.17'
OLD_NATIVE12 = Path('a7r5-firmware-features/native12-combined')
NEW_NATIVE12 = (packaging.PARENT).relative_to(ROOT)
AP_SHA = '27bc6eb0a0d9996e96e3835205d06c1cf03c7ef73421e6781b6e96c4b6ed7962'
COMPONENTS = {**packaging.COMPONENTS, 'appFw.so': AP_SHA}
CPU_COUNT = 28
FRAME_COUNT = 39


class CandidatePatch(packaging.CandidatePatch):
    _bindings = {
        **packaging.CandidatePatch._bindings,
        '/lib/appFw.so': replace(packaging.CandidatePatch._bindings['/lib/appFw.so'],
                                 target_sha256=AP_SHA),
    }


def verified(path, expected):
    packaging.require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
                      and packaging.digest(path) == expected, '固定证据摘要不符：'+str(path))
    return path


def verify_cpu(path, xml, build_sha, gate):
    cpu = json.loads(path.read_text())
    tests = {item.rsplit('::', 1)[-1] for item in cpu['tests']}
    packaging.require(cpu['status']=='PASS' and cpu['exit_code']==0 and cpu['sources_unchanged'] is True
                      and cpu['build_receipt_sha256']==build_sha and cpu['camera_io'] is False
                      and (cpu['AP_sha256'], cpu['CP_sha256']) == (AP_SHA, COMPONENTS['cpapp-b.bin'])
                      and len(cpu['tests'])==CPU_COUNT and tests==gate.cases(xml, CPU_COUNT),
                      '候选回归结果不符：'+str(path))
    return cpu, tests


def migrated_source(name):
    path = Path(name)
    if path.is_relative_to(OLD_NATIVE12):
        return str(NEW_NATIVE12/path.relative_to(OLD_NATIVE12))
    return name


def verify_evidence(out, *, runtime, rebuild, archive):
    build_sha = '554634f8afb96669960cab2910c90f8899c58adbf004ba84954953ee210b6305'
    sources = {
        'runtime-build.json': build_sha,
        'runtime-rebuild.json': 'eebcf314392dd5359b44ab91bde29c8870e212db74235e17a829363096098f73',
        'runtime-regression.json': '071bb5e91a7e6a4bea4299bf0bce12635061520ef441a1ab75c0de96e3740b64',
        'runtime-regression.xml': 'a64c87d7ba86a291110db56863db0b1948f683d6603326971bda267a83404b16',
        'qemu-proof.json': '459d0cc71ab9135793a8369ec660b42ba7944e3516869bf6797722add89ed500',
        'qemu-manifest.json': 'd0a4d67be847c2850ecb1a831a6d7282f6305f921eec25b982bb9401443df304',
    }
    evidence = {name: verified(archive/name, expected) for name, expected in sources.items()}
    gate = packaging.load(packaging.HERE/'evidence_gate.py', 'native24_417_shared_gate')
    for folder, name in ((runtime, 'runtime-build.json'), (rebuild, 'runtime-rebuild.json')):
        current = folder/'build.json'
        packaging.require(current.is_file() and not any(p.is_symlink() for p in (current, *current.parents)),
                          '构建回执不存在或含符号链接：'+str(current))
        for path in (evidence[name], current):
            build = json.loads(path.read_text())
            packaging.require(build['installable'] is False and
                              {k:v['sha256'] for k,v in build['components'].items()} == COMPONENTS,
                              '构建组件或验收状态不符：'+str(path))
        for component, expected in COMPONENTS.items():
            verified(folder/component, expected)
        for relative, expected in build['owned_sources'].items():
            verified(gate.inside(FEATURE, relative), expected)
        for relative, expected in build['external_sources'].items():
            verified(gate.inside(ROOT, relative), expected)
        shutil.copyfile(current, out/('reproduced-'+name))
    cpu, tests = verify_cpu(evidence['runtime-regression.json'], evidence['runtime-regression.xml'], build_sha, gate)
    for name, expected in cpu['sources'].items():
        verified(gate.inside(RELEASE/'source', name), expected)
    fresh_json = runtime/'evidence/session-result.json'
    fresh_xml = runtime/'tab-memory-regression.xml'
    fresh, fresh_tests = verify_cpu(fresh_json, fresh_xml, packaging.digest(runtime/'build.json'), gate)
    packaging.require(fresh_tests == tests and set(fresh['sources']) == {migrated_source(name) for name in cpu['sources']},
                      '迁移后的回归用例或源码集合不符')
    for name, expected in fresh['sources'].items():
        verified(gate.inside(ROOT, name), expected)
    shutil.copyfile(fresh_json, out/'reproduced-runtime-regression.json')
    shutil.copyfile(fresh_xml, out/'reproduced-runtime-regression.xml')
    proof = json.loads(evidence['qemu-proof.json'].read_text())
    for row in (cpu, proof, json.loads(evidence['qemu-manifest.json'].read_text())):
        packaging.require((row['AP_sha256'],row['CP_sha256'])==(AP_SHA,COMPONENTS['cpapp-b.bin']),
                          '验证组件与封包候选不符')
    packaging.require(proof['manifest_sha256']==packaging.digest(evidence['qemu-manifest.json'])
                      and proof['qt_operations']==FRAME_COUNT and len(proof['raw_png_frames'])==FRAME_COUNT
                      and proof['factory_last_row_restored'] is True and proof['camera_io'] is False
                      and proof['E4_application_completed'] is False
                      and proof['custom_success_memory_verified_in_QEMU'] is False
                      and proof['selection_persistence_verified_in_QEMU'] is False,
                      'QEMU复验范围不符')
    for name, path in evidence.items():
        shutil.copyfile(path, out/name)
    packaging.save(out/'candidate-417.json', dict(
        components=COMPONENTS, independent_rebuild_identical=True, reused_CPU_tests=CPU_COUNT,
        reproduced_CPU_tests=CPU_COUNT, reused_QEMU_frames=FRAME_COUNT, qemu_raw_frames_rechecked=False,
        E4_application_completed=False, camera_io=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True, help='主构建及定向回归输出')
    parser.add_argument('--rebuild', type=Path, required=True, help='独立重建输出')
    parser.add_argument('--evidence-dir', type=Path, default=RELEASE/'evidence', help='固定发布回执所在目录')
    args = parser.parse_args()
    runtime, rebuild = args.runtime.absolute(), args.rebuild.absolute()
    if runtime.resolve() == rebuild.resolve():
        parser.error('主构建和独立重建必须使用不同目录')
    archive = args.evidence_dir.absolute()
    packaging.package(args.output.absolute(), baseline=args.baseline.absolute(),
                      components_dir=runtime, components=COMPONENTS, patch_type=CandidatePatch,
                      version='4.17', release_dir=HERE,
                      evidence_check=partial(verify_evidence, runtime=runtime, rebuild=rebuild, archive=archive),
                      reused=dict(reused_CPU_tests=CPU_COUNT, reproduced_CPU_tests=CPU_COUNT,
                                  reused_QEMU_frames=FRAME_COUNT))


if __name__ == '__main__':
    main()
