"""纯本机封存本次恢复材料；不存在覆盖或设备访问入口。"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'recovery'), str(ROOT)]
import recovery_flow as flow
from references import loader_path

OLD = ROOT/'packages/libjit-info-20261021-01'
BUNDLE = ROOT/'recovery/packages/libjit-recovery-20261021-01'
EVENT_SHA = 'd083ae6d74a0b7390fb5efccc4e36e3a1c46c5f553d24dc8fc0e4ab367060a12'
OP_SHA = '775e6b31a6e2dec8691117aa5026add9abd55c52fc5f4de08de890ba8bdb705a'


def sha(path):
    return flow.digest(flow.regular(path).read_bytes())


def prepare():
    if BUNDLE.exists():
        raise FileExistsError('历史恢复包已存在；保留旧包、批准和锁，禁止重复封装或重跑')
    operation = json.loads((OLD/'operation.json').read_text())
    config = json.loads((OLD/'config.json').read_text())
    assessment = json.loads((OLD/'result/stopped-assessment.json').read_text())
    if sha(OLD/'operation.json') != OP_SHA or sha(OLD/'result/session/events.jsonl') != EVENT_SHA:
        raise ValueError('源会话不是已审查的失败证据')
    if config['run_id'] != flow.RUN or assessment['run_id'] != flow.RUN or not (OLD/'ATTEMPT_LOCK').is_dir():
        raise ValueError('源会话或旧锁不符')
    for name in ('trigger_attempts', 'fixed_writes_attempted', 'service_stop_attempts'):
        if assessment[name] != 0:
            raise ValueError('源会话已经执行额外操作')
    if assessment['preload_written'] or assessment['debug_commands_sent']:
        raise ValueError('源会话发生过预加载写入或DEBUG')
    # 原封存包必须完整；不把修改过的来源再次封为新基线。
    for name, expected in operation['files'].items():
        if sha(OLD/name) != expected:
            raise ValueError('原封存包材料变化：'+name)
    library = loader_path(ROOT)
    if sha(library) != config['loader_sha256'] or library.stat().st_size != 233416:
        raise ValueError('本机已知库不是本次版本')
    if sha(OLD/'result/session/version.bin') != config['version_sha256']:
        raise ValueError('本次版本回执变化')
    headers = [row for row in map(json.loads, (OLD/'result/session/events.jsonl').read_text().splitlines())
               if row['event'] == 'response_header']
    if [row['sequence'] for row in headers] != [1, 2, 3, 4] or headers[-1]['raw_hex'] != 'cc8f03004000040003000000':
        raise ValueError('最后响应位置或报文序号不同')
    BUNDLE.mkdir(parents=True, exist_ok=False)
    def copy(source, name):
        dest = BUNDLE/name; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    for name in ('recovery_flow.py',):
        copy(ROOT/'recovery'/name, name)
    for name in ('transport.py', 'host_state.py'):
        copy(ROOT/name, name)
    copy(library, 'evidence/libJiritsu.so')
    evidence = ['operation.json', 'config.json', 'transport.py', 'operation.py',
                'result/result.json', 'result/stopped-assessment.json', 'result/host-recovery.json',
                'result/session/events.jsonl', 'result/session/summary.json', 'result/session/version.bin',
                'result/session/interface-2.json', 'result/session/endpoints-2.json', 'result/session/sources.json']
    for name in evidence:
        copy(OLD/name, 'evidence/source-session/'+name)
    reference = OLD/'vendor/engine/sources/workspaces/j/work/sony-pmca-re/pmca/usb/sony.py'
    copy(reference, 'evidence/sony-reference.py')
    for path in sorted((OLD/'vendor/engine/libs/usb').rglob('*.py')):
        copy(path, 'vendor/usb/'+str(path.relative_to(OLD/'vendor/engine/libs/usb')))
    copy(OLD/'licenses/pyusb-LICENSE', 'licenses/pyusb-LICENSE')
    copy(ROOT/'recovery/分析与恢复方案.md', '分析与恢复方案.md')
    for name in ('chunk-before.log', 'chunk-before.xml', 'chunk-after.log', 'chunk-after.xml',
                 'recovery-first.log', 'recovery-fixed.log', 'recovery-fixed.xml', 'recovery-final.log', 'recovery-final.xml'):
        copy(ROOT/'recovery/packages/libjit-recovery-20261021-01/verification'/name, 'verification/'+name)
    for name in ('test_bulk_chunks.py', 'test_stream_recovery.py'):
        copy(ROOT/'tests'/name, 'verification/source-tests/'+name)
    python = str((ROOT.parent/'.venv/bin/python').resolve(strict=True))
    libusb = '/opt/homebrew/Cellar/libusb/1.0.30/lib/libusb-1.0.0.dylib'
    script = '#!/bin/zsh\nset -eu\ncd -- "${0:A:h}"\nexec sudo '+python+' -B recovery_flow.py execute --device-io\n'
    (BUNDLE/'run-recovery-once.command').write_text(script)
    (BUNDLE/'run-recovery-once.command').chmod(0o700)
    dependencies = dict(operation['dependencies'])
    for name in evidence:
        dependencies[str(OLD/name)] = sha(OLD/name)
    archive = OLD.with_suffix('.zip')
    dependencies[str(archive)] = sha(archive)
    for name, expected in dependencies.items():
        if sha(name) != expected:
            raise ValueError('外部依赖变化：'+name)
    manifest = dict(schema='a7r5-libjit-stream-recovery-1', directory=str(BUNDLE), run_id=flow.RUN,
                    risk=flow.RISK, config=config, source_operation_sha256=OP_SHA,
                    source_events_sha256=EVENT_SHA, libusb=libusb, python=python,
                    dependencies=dependencies, camera_execution_verified=False,
                    max_protocol_requests=8, max_stop_attempts=1,
                    authentication=0, start=0, debug=0, uploads=0, preload_writes=0,
                    files={str(p.relative_to(BUNDLE)): sha(p) for p in sorted(BUNDLE.rglob('*')) if p.is_file()})
    flow.save(BUNDLE/'recovery.json', manifest)
    approval = dict(accepted=False, recovery_sha256=sha(BUNDLE/'recovery.json'), risk=flow.RISK)
    flow.save(BUNDLE/'approval-template.json', approval)
    with (BUNDLE/'checksums.sha256').open('x') as handle:
        for p in sorted(BUNDLE.rglob('*')):
            if p.is_file() and p.name != 'checksums.sha256':
                handle.write(sha(p)+'  '+str(p.relative_to(BUNDLE))+'\n')
    archive = BUNDLE.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(BUNDLE.rglob('*')):
            if p.is_file(): z.write(p, str(p.relative_to(BUNDLE.parent)))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('ZIP CRC校验失败')
    flow.save(BUNDLE.parent/'libjit-recovery-20261021-01-receipt.json',
              dict(bundle=str(BUNDLE), archive=str(archive), archive_sha256=sha(archive),
                   recovery_sha256=sha(BUNDLE/'recovery.json'), files=len(manifest['files']),
                   approved=False, device_requests=0, source_session_preserved=True))
    print(BUNDLE)
    print('ZIP SHA-256: '+sha(archive))


if __name__ == '__main__':
    prepare()
