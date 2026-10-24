"""清理只发生在本机完整副本持久化之后；测试禁止真实设备。"""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

import common
import device
from capture_operation import Operation
from transport import FileResultError


@pytest.mark.parametrize('fault', [None, 'download', 'persist', 'cleanup'])
def test_cleanup_requires_durable_backup_and_preserves_it_on_failure(tmp_path, baseline, ram_runtime, monkeypatch, fault):
    package, _ = device.prepare_capture(tmp_path, 'a'*32, baseline)
    cfg = common.load(package/'config.json')
    cfg.update(version_sha256=hashlib.sha256(b'version').hexdigest(),
               loader_sha256=hashlib.sha256(b'loader').hexdigest())
    (package/'config.json').write_text(json.dumps(cfg))
    image = bytes(range(256))*(common.PARTITION_BYTES//256)
    digest = hashlib.sha256(image).hexdigest()
    native = (cfg['expected_output_begin']+f'A7R5_CAPTURE_COMPLETE {digest} bytes=25100288 twice=1 chunks=1532 chunk_bytes=16384\n'+cfg['expected_output_end']).encode()
    run = cfg['run_id'];cleanup = '/tmp_wbshd/a7r5-cleanup-'+run+'/task'
    receipt = f'A7R5_CAPTURE_CLEANUP {run} sha256={digest} deleted=1532 bytes=25100288 directory_removed=1\n'.encode()
    uploads = [];triggers = [0]
    class Files:
        def __init__(self, driver, operation, log):self.op = operation
        def put(self, path, raw):
            if 'a7r5-cleanup-' in path:
                saved = self.op.output/'partition1.logical.bin'
                assert saved.read_bytes() == image
                assert common.load(self.op.output/'backup-verified.json')['sha256'] == digest
                assert self.op.output.joinpath('backup-verified.json').stat().st_mode & 0o777 == 0o600
            uploads.append(path)
            if path == '/tmp/jiritsu/libJit.so':triggers[0] += 1
        def read(self, path, limit):
            if path == '/version.txt':return b'version'
            if path == '/usr/lib/libJiritsu.so':return b'loader'
            if path == '/etc/ld.so.preload':return b'\n'*512
            if path.endswith('.ticket') and path in uploads:return self.op.ticket
            if path == self.op.prefix+'.state' and triggers[0]:
                return f'A7R5-JIT-1 {run} DONE 0 uid=0 euid=0 bytes={len(native)} disarmed=1 children=0\n'.encode()
            if path == self.op.prefix+'.output' and triggers[0]:return native
            if path == cleanup+'.state' and triggers[0] == 2:
                state = 'FAILED 72' if fault == 'cleanup' else 'DONE 0'
                return f'A7R5-JIT-1 {run} {state} uid=0 euid=0 bytes={len(receipt)} disarmed=1 children=0\n'.encode()
            if path == cleanup+'.output' and triggers[0] == 2:return receipt
            if path in dict(self.op.parts):
                index = int(path.rsplit('-', 1)[1]);data = image[index*16384:(index+1)*16384]
                return b'!'+data[1:] if fault == 'download' and index == 1 else data
            raise FileResultError(0x10000006)
    op = Operation(package, channel_factory=Files, sleep=lambda seconds: None)
    dest = tmp_path/'session';dest.mkdir();report = {}
    if fault=='persist':
        def fail_sync(*args):raise OSError('模拟本机落盘失败')
        monkeypatch.setattr('capture_operation.os.fsync',fail_sync)
    if fault is None:
        op(None, dest, lambda *a, **k: None, report)
        assert report.get('capture_cleanup_verified') is True, '完整下载后没有清理机内副本'
        assert report['capture_cleanup_deleted_chunks'] == 1532 and op.safe_to_stop
        assert report['fixed_writes_attempted'] == 4 and report['trigger_attempts'] == 2
    else:
        with pytest.raises((ValueError, RuntimeError, OSError)):
            op(None, dest, lambda *a, **k: None, report)
        assert not op.safe_to_stop
    if fault in ('download','persist'):
        assert len(uploads) == 2 and triggers[0] == 1
        assert not report.get('capture_verified') and not (dest/'backup-verified.json').exists()
    else:
        assert report['capture_verified'] and report['backup_persisted']
        assert (dest/'partition1.logical.bin').read_bytes() == image
        assert len(uploads) == 4 and triggers[0] == 2
        if fault == 'cleanup':assert report['capture_cleanup_state'] == 'failed'


@pytest.fixture(scope='module')
def native_cleanup(tmp_path_factory):
    root=Path(__file__).resolve().parents[1];folder=tmp_path_factory.mktemp('capture-cleanup')
    run='a'*32
    values=dict(RUN_ID=run,TICKET_BYTES='A7R5_LIBJIT '+run+'\n',
        CLEANUP_DIRECTORY='a7r5-capture-'+run,SOURCE_CONTROL_DIRECTORY='a7r5-control-'+run,
        CAPTURE_BEGIN='A7R5_CAPTURE_BEGIN '+run+'\n',CAPTURE_END='A7R5_CAPTURE_END '+run+'\n',
        PRELOAD_A='\n'*512,PRELOAD_B='\n'*512)
    header='#define CAPTURE_PART_BYTES 16384\n#define CAPTURE_PART_COUNT 1532\n#define CAPTURE_SUMMARY " bytes=25100288 twice=1 chunks=1532 chunk_bytes=16384\\n"\n#define CLEANUP_PARENT root_path\n'+''.join('#define '+key+' '+json.dumps(value)+'\n' for key,value in values.items())
    (folder/'cleanup_config.h').write_text(header)
    binary=folder/'cleanup-core'
    result=subprocess.run(['/usr/bin/clang','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
        '-I',str(folder),'-I',str(root/'sources/trust'),str(root/'tests/host_capture_cleanup.c'),'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return binary,run


@pytest.mark.parametrize('fault', ['complete','digest','short','symlink','hardlink','directory-symlink','unexpected','state','vfat','owner','unlink'])
def test_native_cleanup_deletes_only_bound_ram_copy(native_cleanup,tmp_path,fault):
    binary,run=native_cleanup
    image=bytes(range(256))*(common.PARTITION_BYTES//256);digest=hashlib.sha256(image).hexdigest()
    capture=tmp_path/('a7r5-capture-'+run);capture.mkdir(mode=0o700)
    control=tmp_path/('a7r5-control-'+run);control.mkdir(mode=0o700)
    output=f'A7R5_CAPTURE_BEGIN {run}\nA7R5_CAPTURE_COMPLETE {digest} bytes=25100288 twice=1 chunks=1532 chunk_bytes=16384\nA7R5_CAPTURE_END {run}\n'.encode()
    (control/'task.output').write_bytes(output)
    state=f'A7R5-JIT-1 {run} DONE 0 uid=0 euid=0 bytes={len(output)} disarmed=1 children=0\n'.encode()
    (control/'task.state').write_bytes(state if fault!='state' else state.replace(b'DONE 0',b'RUNNING 0'))
    (control/'task.claim').write_bytes(('A7R5_LIBJIT '+run+'\n').encode())
    for index in range(1532):(capture/f'partition.bin.part-{index}').write_bytes(image[index*16384:(index+1)*16384])
    # 历史目录、控制证据以及外部目标都必须原样保留。
    old=tmp_path/'a7r5-capture-historical';old.mkdir();(old/'sentinel').write_bytes(b'history')
    foreign=tmp_path/'foreign';foreign.write_bytes(b'foreign')
    if fault=='digest':(capture/'partition.bin.part-1531').write_bytes(b'!'+image[1531*16384+1:])
    if fault=='short':(capture/'partition.bin.part-1531').write_bytes(b'short')
    if fault=='symlink':
        (capture/'partition.bin.part-0').unlink();(capture/'partition.bin.part-0').symlink_to(foreign)
    if fault=='hardlink':(tmp_path/'part-alias').hardlink_to(capture/'partition.bin.part-0')
    if fault=='directory-symlink':
        outside=tmp_path/'foreign-capture';capture.rename(outside);capture.symlink_to(outside,target_is_directory=True)
    if fault=='unexpected':(capture/'unrecognized').write_bytes(b'keep')
    protected={p:p.read_bytes() for p in [foreign,old/'sentinel',*control.iterdir()]}
    before={p.name:p.read_bytes() for p in capture.iterdir()}
    injected={'vfat':1,'owner':2,'unlink':3}.get(fault,0)
    result=subprocess.run([str(binary),str(tmp_path),str(injected)],capture_output=True,text=True,check=True)
    assert 'write_opens=0' in result.stdout
    assert all(p.read_bytes()==raw for p,raw in protected.items())
    if fault=='complete':
        assert 'code=0 deletions=1533' in result.stdout and not capture.exists()
        assert f'sha256={digest} deleted=1532 bytes=25100288 directory_removed=1' in result.stdout
    elif fault=='unlink':
        assert 'code=71 deletions=5' in result.stdout and len(list(capture.iterdir()))==1527
        assert 'deleted=5 code=71' in result.stdout
    else:
        assert 'deletions=0' in result.stdout and 'code=0 ' not in result.stdout
        assert {p.name:p.read_bytes() for p in capture.iterdir()}==before


def test_cleanup_failure_remains_a_failed_task_with_usable_local_backup(tmp_path, baseline, ram_runtime):
    from types import SimpleNamespace
    image=b'x'*common.PARTITION_BYTES
    def session(output,transport,_operation):
        output.mkdir();(output/'partition1.logical.bin').write_bytes(image)
        return dict(failure='清理超时',protocol_gate_passed=True,capture_verified=True,backup_persisted=True,
            preload_unchanged=True,capture_sha256=hashlib.sha256(image).hexdigest(),expected_preload_hex=(b'\n'*512).hex(),
            fixed_writes_attempted=4,trigger_attempts=2,service_stop_attempts=0,
            capture_cleanup_required=True,capture_cleanup_verified=False,capture_cleanup_state='failed')
    def forbidden(*args,**kwargs):pytest.fail('清理失败不能继续观察或发设备请求')
    value=device.run(dict(run_id='b'*32,kind='backup'),tmp_path.resolve(),
        session_module=SimpleNamespace(__name__='simulation',run_session=session),
        host_module=SimpleNamespace(snapshot=lambda *args:baseline,observe=forbidden))
    assert value['backup_complete'] and value['backup_sha256']==hashlib.sha256(image).hexdigest()
    assert not value['task_complete'] and not value['can_replug'] and value['error']=='清理超时'
    assert not value['automatic_retry'] and value['report']['service_stop_attempts']==0
