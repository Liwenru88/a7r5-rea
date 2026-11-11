"""从最终 DAT 回读文件派生客体，保留所有生产组件的字节身份。"""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil

import environment as env


def build(bundle, readback, output, restore=None):
    lock = json.loads((bundle / 'lock.json').read_text())
    manifest = json.loads((readback / 'manifest.json').read_text())
    if env.digest(bundle / 'BODYDATA.DAT') != lock['dat']['sha256'] or manifest['source'] != lock['dat']:
        raise ValueError('最终 DAT 或独立解包输入不符')
    if output.exists() or output.parent.resolve() != env.LAB / 'build':
        raise ValueError('需要新的独立客体目录')
    candidate = output.with_name(output.name + '-components')
    candidate.mkdir(mode=0o700)
    runtime = bundle / 'build-evidence/native24'
    shutil.copytree(runtime / 'work', candidate / 'work')
    record = json.loads((runtime / 'build.json').read_text())
    record['runtime_origin'] = {k: record[k] for k in ('AP_sha256', 'CP_sha256')}
    for name, component in [('appFw.so', 'usr/lib/appFw.so'), ('cpapp-b.bin', 'cpapp-b.bin')]:
        source = readback / 'components' / component
        expected = lock['expected']['components'][component]['sha256']
        if env.digest(source) != expected:
            raise ValueError('最终组件摘要不符 ' + component)
        shutil.copyfile(source, candidate / name)
        record['AP_sha256' if name == 'appFw.so' else 'CP_sha256'] = expected
    env.save(candidate / 'build.json', record)
    capture = bundle / 'build-evidence/capture'
    for name in ('image_00_23_IPSX.uxc', 'image_00_32_IPSX.uxc'):
        shutil.copyfile(capture / name, candidate / name)
    extra = {}
    for key, pin in manifest['components'].items():
        if key.startswith('usr/share/app/string_'):
            source = readback / 'components' / key
            if env.digest(source) != pin['sha256']:
                raise ValueError('最终文字资源不符')
            extra[key] = source.read_bytes()
    if len(extra) != 68:
        raise ValueError('缺少完整横竖文字资源')
    extra['usr/lib/libmpr.so'] = (capture / 'libmpr.so').read_bytes()
    extra['simulation/R5NATIVE.BIN'] = (bundle / 'R5NATIVE.BIN').read_bytes()
    if env.digest(capture / 'libmpr.so') != lock['expected']['components']['usr/lib/libmpr.so']['sha256']:
        raise ValueError('最终回放组件不符')
    spec = importlib.util.spec_from_file_location('full419_guest_builder', env.PARENT / 'build_guest.py')
    parent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parent)
    env.AP_SHA, env.CP_SHA = record['AP_sha256'], record['CP_sha256']
    parent.build(output, candidate, restore, extra_components=extra)
    result = json.loads((output / 'manifest.json').read_text())
    shutil.copyfile(bundle / 'lock.json', output / 'full419-lock.json')
    shutil.copyfile(bundle / 'R5NATIVE.BIN', output / 'R5NATIVE.BIN')
    result['loading_inputs']['bin'] = env.fact(output / 'R5NATIVE.BIN')
    result.update(schema='r5-full419-qemu/1', firmware='4.19-full',
                  full419_lock=env.fact(output / 'full419-lock.json'), source_DAT_sha256=lock['dat']['sha256'],
                  package_source={'version': '4.19 全功能'}, DAT_generated=True)
    env.checked_lock(result)
    # 此清单刚由本次父构建器生成；只在本轮独占的新目录补齐最终包身份。
    (output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('bundle', 'readback', 'output'):
        p.add_argument('--' + key, type=Path, required=True)
    p.add_argument('--restore', type=Path)
    a = p.parse_args()
    build(a.bundle.resolve(), a.readback.resolve(), a.output.resolve(), a.restore)
