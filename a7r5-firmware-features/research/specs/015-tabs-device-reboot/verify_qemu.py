"""核对本故障诊断的Qt回执、原帧和正常退出；不将软件解码当成LDEC验收。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'a7r5-qemu/tools'))
from menu_live import snapshot_png


def verify(run, manifest):
    guest = json.loads(manifest.read_text())
    driver = json.loads((run / 'validation-driver.json').read_text())
    ui = json.loads((run / 'qt-research.json').read_text())
    menu = json.loads((run / 'native410-menu.json').read_text())
    cp = json.loads((run / 'cp/close.json').read_text())
    tabs = json.loads((run / 'tabs-validation.json').read_text())
    parameters = json.loads((run / 'parameter-validation.json').read_text())
    if [driver['exit_code'], ui['worker_exit_code'], menu['close']['exit_code'], cp['exit_code']] != [0] * 4:
        raise ValueError('Qt／AP／CP未正常退出')
    if driver['command'][-2:] != ['--manifest', str(manifest.resolve())] or ui['operations'][-1]['action'] != 'STOP':
        raise ValueError('驱动输入或停止回执不符')
    if tabs['status'] != 'PASS' or parameters['status'] != 'PASS' or not tabs['navigation_only_no_application']:
        raise ValueError('Tab／调参契约未通过')
    if len(ui['operations']) != 103 or len(driver['actions']) != 103:
        raise ValueError('正式十二款诊断动作不完整')
    if tabs['custom_rows'] != list(range(0x1611, 0x161c)) + [0x1610]:
        raise ValueError('正式十二款未完整遍历')
    for name, source in json.loads((run / 'validation-sources.json').read_text()).items():
        if hashlib.sha256(source['text'].encode()).hexdigest() != source['sha256']:
            raise ValueError('验证源码快照摘要不符：' + name)
    frames = [p for p in run.glob('*.bin') if p.with_suffix('.png').is_file()]
    if len(frames) != 103:
        raise ValueError('原帧数量不符')
    for frame in frames:
        if snapshot_png(frame.read_bytes()) != frame.with_suffix('.png').read_bytes():
            raise ValueError('原帧与PNG不符：' + frame.name)
    return {'status': 'PASS', 'run': str(run), 'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'AP_sha256': guest['AP_sha256'], 'CP_sha256': guest['CP_sha256'], 'actions': 103, 'raw_png_frames': len(frames),
            'software_lz77': True, 'hardware_LDEC_verified': False, 'camera_io': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'manifest', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.run.resolve(), args.manifest.resolve())
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False))
