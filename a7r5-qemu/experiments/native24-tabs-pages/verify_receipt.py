"""绑定修复组件，核对真实Qt、CPIO载荷、原帧及正常退出；无机身入口。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import environment as env
from cpio_inputs import entries
from menu_live import snapshot_png

COUNTS = {'installed12': 103}


def verify(run, manifest):
    guest = json.loads(manifest.read_text())
    env.validate_identity(guest)
    recipe = guest['recipe_set']
    expected = COUNTS[recipe]
    obj = type('Candidate', (), {'manifest_path': manifest})()
    inputs = env.MenuVM.runtime_inputs(obj)
    actual = entries(inputs['initrd'])
    for name, digest in env.COMPONENT_SHAS.items():
        path = 'usr/lib/' + name if name == 'appFw.so' else 'cp/' + name if name == 'cpapp-b.bin' else 'usr/share/app/' + name
        if actual[path]['sha256'] != digest:
            raise ValueError('CPIO实际组件与修复身份不符：' + name)
    driver = json.loads((run / 'validation-driver.json').read_text())
    ui = json.loads((run / 'qt-research.json').read_text())
    ap = json.loads((run / 'native410-menu.json').read_text())
    cp = json.loads((run / 'cp/close.json').read_text())
    if [driver['exit_code'], ui['worker_exit_code'], ap['close']['exit_code'], cp['exit_code']] != [0] * 4:
        raise ValueError('Qt／AP／CP未正常退出')
    if driver['command'][-2:] != ['--manifest', str(manifest)] or driver['actions'][-1] != 'STOP':
        raise ValueError('驱动或停止身份不符')
    if len(driver['actions']) != expected or len(ui['operations']) != expected:
        raise ValueError('Qt操作数量不符')
    validation = json.loads((run / ('empty-validation.json' if recipe == 'empty' else 'tabs-validation.json')).read_text())
    if validation.get('status') != 'PASS' or not validation.get('no_application' if recipe == 'empty' else 'navigation_only_no_application'):
        raise ValueError('Tab契约未通过')
    if recipe == 'installed12':
        if validation['custom_rows'] != list(range(0x1611, 0x161c)) + [0x1610]:
            raise ValueError('正式12款未完整遍历')
        parameters = json.loads((run / 'parameter-validation.json').read_text())
        if parameters.get('status') != 'PASS' or not parameters.get('reset_verified') or not parameters.get('reopen_preserved'):
            raise ValueError('八项调参／重置未通过')
    for name, source in json.loads((run / 'validation-sources.json').read_text()).items():
        if hashlib.sha256(source['text'].encode()).hexdigest() != source['sha256'] or env.digest(Path(name)) != source['sha256']:
            raise ValueError('QEMU源码漂移：' + name)
    frames = [p for p in run.glob('*.bin') if p.with_suffix('.png').is_file()]
    if len(frames) != expected:
        raise ValueError('原帧数量不符')
    for p in frames:
        if snapshot_png(p.read_bytes()) != p.with_suffix('.png').read_bytes():
            raise ValueError('原帧与PNG不符：' + p.name)
    facts = {str(p): env.digest(p) for p in run.rglob('*') if p.is_file() and p.suffix in ('.bin', '.png', '.json', '.jsonl')}
    return {'schema': 'native24-tabs-pages-qemu-proof/1', 'status': 'PASS', 'recipe_set': recipe,
            'run': str(run), 'manifest': str(manifest), 'manifest_sha256': env.digest(manifest),
            'components': env.COMPONENT_SHAS, 'actions': expected, 'raw_png_frames': len(frames),
            'files': facts, 'camera_io': False, 'hardware_LDEC_verified': False,
            'verifier_sha256': env.digest(Path(__file__))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'manifest', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.run.resolve(), args.manifest.resolve())
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: result[k] for k in ('status', 'recipe_set', 'actions', 'raw_png_frames')}, ensure_ascii=False))
