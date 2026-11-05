"""封装左键切组与两组应用记忆的固定 4.17 候选。"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'release415'))
import build as packaging

ROOT = packaging.ROOT
RUNTIME = ROOT/'.local/native24-tab-memory-20261105-02'
REBUILD = ROOT/'.local/native24-tab-memory-20261105-rebuild'
RUN = ROOT/'a7r5-qemu/runs/native-native12-410-vjfcts40'
MANIFEST = ROOT/'a7r5-qemu/build/native24-tab-memory-menu-20261105-01/manifest.json'
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


def verify_evidence(out):
    build_sha = '554634f8afb96669960cab2910c90f8899c58adbf004ba84954953ee210b6305'
    evidence = {
        'runtime-build.json': verified(RUNTIME/'build.json', build_sha),
        'runtime-rebuild.json': verified(REBUILD/'build.json',
            'eebcf314392dd5359b44ab91bde29c8870e212db74235e17a829363096098f73'),
        'runtime-regression.json': verified(RUNTIME/'evidence/session-result.json',
            '071bb5e91a7e6a4bea4299bf0bce12635061520ef441a1ab75c0de96e3740b64'),
        'runtime-regression.xml': verified(RUNTIME/'tab-memory-regression.xml',
            'a64c87d7ba86a291110db56863db0b1948f683d6603326971bda267a83404b16'),
        'qemu-proof.json': verified(RUN/'tab-memory-proof.json',
            '459d0cc71ab9135793a8369ec660b42ba7944e3516869bf6797722add89ed500'),
        'qemu-manifest.json': verified(MANIFEST,
            'd0a4d67be847c2850ecb1a831a6d7282f6305f921eec25b982bb9401443df304'),
    }
    for folder, name in ((RUNTIME, 'runtime-build.json'), (REBUILD, 'runtime-rebuild.json')):
        build = json.loads(evidence[name].read_text())
        packaging.require(build['installable'] is False and
                          {k:v['sha256'] for k,v in build['components'].items()} == COMPONENTS,
                          '构建组件或验收状态不符')
        for component, expected in COMPONENTS.items():
            verified(folder/component, expected)
    cpu = json.loads(evidence['runtime-regression.json'].read_text())
    tests = {item.rsplit('::', 1)[-1] for item in cpu['tests']}
    gate = packaging.load(packaging.HERE/'evidence_gate.py', 'native24_417_shared_gate')
    packaging.require(cpu['status']=='PASS' and cpu['exit_code']==0 and cpu['sources_unchanged'] is True
                      and cpu['build_receipt_sha256']==build_sha and cpu['camera_io'] is False
                      and len(cpu['tests'])==CPU_COUNT
                      and tests==gate.cases(evidence['runtime-regression.xml'], CPU_COUNT),
                      '候选回归结果不符')
    for name, expected in cpu['sources'].items():
        verified(gate.inside(ROOT, name), expected)
    proof = json.loads(evidence['qemu-proof.json'].read_text())
    for row in (cpu, proof, json.loads(evidence['qemu-manifest.json'].read_text())):
        packaging.require((row['AP_sha256'],row['CP_sha256'])==(AP_SHA,COMPONENTS['cpapp-b.bin']),
                          '验证组件与封包候选不符')
    packaging.require(proof['manifest_sha256']==packaging.digest(MANIFEST)
                      and proof['qt_operations']==FRAME_COUNT and len(proof['raw_png_frames'])==FRAME_COUNT
                      and proof['factory_last_row_restored'] is True and proof['camera_io'] is False
                      and proof['E4_application_completed'] is False
                      and proof['custom_success_memory_verified_in_QEMU'] is False
                      and proof['selection_persistence_verified_in_QEMU'] is False,
                      'QEMU复验范围不符')
    for name, expected in proof['raw_png_frames'].items():
        verified(gate.inside(RUN, name), expected)
    for name, path in evidence.items():
        shutil.copyfile(path, out/name)
    packaging.save(out/'candidate-417.json', dict(
        components=COMPONENTS, independent_rebuild_identical=True, reused_CPU_tests=CPU_COUNT,
        reused_QEMU_frames=FRAME_COUNT, E4_application_completed=False, camera_io=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    packaging.package(args.output.absolute(), baseline=args.baseline.absolute(),
                      components_dir=RUNTIME, components=COMPONENTS, patch_type=CandidatePatch,
                      version='4.17', release_dir=HERE, evidence_check=verify_evidence,
                      reused=dict(reused_CPU_tests=CPU_COUNT, reused_QEMU_frames=FRAME_COUNT))


if __name__ == '__main__':
    main()
