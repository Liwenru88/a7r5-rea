"""离线失败验证：关注执行前拒绝、上传中断后零追加和永久锁。"""
import hashlib,json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(next(p for p in Path(__file__).resolve().parents if (p/'candidate_once.py').is_file())))
import candidate_once as tool


@pytest.fixture
def material(tmp_path,monkeypatch):
    root=tmp_path/'project';(root/'a7r5-exec').mkdir(parents=True)
    monkeypatch.setattr(tool,'project',lambda:root)
    prior=root/'a7r5-exec/runs'/tool.PREDECESSOR/'result';prior.mkdir(parents=True)
    (prior/'result.json').write_text(json.dumps(dict(run_id=tool.PREDECESSOR,execution_succeeded=True,host_recovery_verified=True,operation_sha256='0'*64)))
    (prior/'screen-confirmation.json').write_text(json.dumps(dict(run_id=tool.PREDECESSOR,screen_normal=True,operation_sha256='0'*64)))
    p=tmp_path/'package';p.mkdir(mode=0o700)
    files=['stage-prepare.sh','stage-verify.sh','known_hosts','anchor-task.sh']
    for f in files:(p/f).write_text(f)
    m=dict(schema='a7r5-original-view-1',run_id='a'*32,port=2223,ip='10.10.10.177',autostart=False,live_approved=False,
        qemu_only=False,seconds=600,install_directory='/tmp/jiritsu/a7r5-original-'+'a'*32,
        uploads=['ssh-original.arm64','session.arm64','sftp-server.arm64','anchor.arm64','start.sh'],
        files={f:tool.sha(p/f) for f in files})
    (p/'manifest.json').write_text(json.dumps(m))
    return p,root,m


@pytest.mark.parametrize('fault',['no_device_flag','no_approval','pending','tamper','extra','symlink','upload_set','seconds','qemu_material'])
def test_preflight_refuses_before_transport(material,fault):
    p,root,m=material
    accept=tool.phrase(p,'stage');device=True
    if fault=='no_device_flag':device=False
    if fault=='no_approval':accept='wrong'
    if fault=='qemu_material':
        m['qemu_only']=True;(p/'manifest.json').write_text(json.dumps(m));accept=tool.phrase(p,'stage')
    if fault=='pending':(root/'a7r5-exec/PENDING_RECOVERY.json').write_text('{}')
    if fault=='tamper':(p/'stage-prepare.sh').write_text('tampered')
    if fault=='extra':(p/'unlisted').write_text('x')
    if fault=='symlink':(p/'extra-link').symlink_to(p/'known_hosts')
    if fault in ['upload_set','seconds','qemu_material']:
        m['uploads' if fault=='upload_set' else 'seconds']=['../../etc/passwd'] if fault=='upload_set' else 0
        (p/'manifest.json').write_text(json.dumps(m));accept=tool.phrase(p,'stage')
    class Forbidden:
        def __init__(self,*a):pytest.fail('拒绝前不应创建连接')
    with pytest.raises((ValueError,PermissionError)):
        tool.execute(p,'stage',accept,device,transport=Forbidden)
    assert not (p/'.state/stage-ATTEMPT_LOCK').exists()


@pytest.mark.parametrize('where,expected',[('prepare',['prepare']),('upload',['prepare','upload']),('verify',['prepare','upload','verify'])])
def test_failure_stops_without_retry_or_cleanup(material,where,expected):
    p,root,m=material;events=[]
    class Fake:
        def __init__(self,*a):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def command(self,script,label):
            phase=label.split('-')[1];events.append(phase)
            if phase==where:raise RuntimeError('injected')
            return ('A7R5_STAGE_EMPTY '+m['run_id']+'\n').encode() if phase=='prepare' else b'bad'
        def upload(self,*a):
            events.append('upload')
            if where=='upload':raise RuntimeError('injected')
    result=tool.execute(p,'stage',tool.phrase(p,'stage'),True,transport=Fake)
    assert not result['passed'] and events==expected
    assert (p/'.state/stage-ATTEMPT_LOCK').is_dir()
    with pytest.raises(FileExistsError):tool.execute(p,'stage',tool.phrase(p,'stage'),True,transport=Fake)
    assert events==expected


def test_start_requires_completed_anchor_before_connect(material):
    p,root,m=material
    with pytest.raises(ValueError,match='尚未完成本次上传'):
        tool.execute(p,'start',tool.phrase(p,'start'),True)
    assert not (p/'.state/start-ATTEMPT_LOCK').exists()


def test_stale_approval_rejected(material):
    p,root,m=material;accepted=tool.phrase(p,'stage')
    (p/'known_hosts').write_text('changed');m['files']['known_hosts']=tool.sha(p/'known_hosts')
    (p/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(PermissionError):tool.execute(p,'stage',accepted,True)


@pytest.mark.parametrize('forged',[False,True])
def test_missing_pending_marker_does_not_close_old_failure(material,forged):
    p,root,m=material;prior=root/'a7r5-exec/runs'/tool.PREDECESSOR/'result'
    value=json.loads((prior/'result.json').read_text());value['execution_succeeded']=False
    (prior/'result.json').write_text(json.dumps(value))
    if forged:(prior/'recovery-closure.json').write_text(json.dumps(dict(schema='a7r5-recovery-closure-1',run_id=tool.PREDECESSOR,failed_result_sha256='wrong')))
    class Forbidden:
        def __init__(self,*a):pytest.fail('旧失败未收口时不得连接')
    with pytest.raises(PermissionError):tool.execute(p,'stage',tool.phrase(p,'stage'),True,transport=Forbidden)
    assert not (p/'.state/stage-ATTEMPT_LOCK').exists()
