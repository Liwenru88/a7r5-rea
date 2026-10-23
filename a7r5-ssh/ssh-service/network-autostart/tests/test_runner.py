"""假传输验证离线默认、当前实例门槛、失败即停及恢复范围。"""
from pathlib import Path
import hashlib
import json
import re
import sys
import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import runner


@pytest.fixture
def package(tmp_path):
    op=json.loads((HERE/'operation.json').read_text());op['dependencies']={}
    (tmp_path/'materials').mkdir()
    for name in ['expected-ready.bin','trusted-host-public-key','preload.previous','network.so','control.static']:
        (tmp_path/'materials'/name).write_bytes((HERE/'materials'/name).read_bytes())
    (tmp_path/'known_hosts').write_text('SYNTHETIC_HOST_FILE')
    return tmp_path,op


def evidence(root,op):
    old=(HERE/'tests/fixtures/live-mounts.txt').read_bytes()
    ready=(root/'materials/expected-ready.bin').read_bytes()
    identity=re.search(rb'parent=(\d+) child=(\d+)',ready)
    def beat(n):return b'A7R5_PRIVATE_ALIVE '+op['service_run'].encode()+b' parent='+identity[1]+b' child='+identity[2]+b' ttl=0 elapsed_ms='+str(n).encode()+b' parent_unchanged=1\n'
    pairs=[('NS',(op['active_namespace']+'\n').encode()),('MOUNTS',old),('READY',ready),
        ('PUBLIC',(root/'materials/trusted-host-public-key').read_bytes()),('HEART1',beat(1000000)),('HEART2',beat(1002000)),
        ('PRELOAD',(root/'materials/preload.previous').read_bytes()),
        ('ORIGINAL_HASHES',''.join('SHA2-256('+k+')= '+v+'\n' for k,v in op['original_hashes'].items()).encode())]
    return b'A7R5_NET_PREFLIGHT1\nUid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\n'+b''.join(b'\n==='+n.encode()+b'===\n'+v for n,v in pairs)+b'===END===\n'


def reply(index,root,op):
    if index==1:return evidence(root,op)
    if index==2:return b'A7R5_NET_STAGE1\n'
    if index in [3,4]:return b''
    if index==5:return ('A7R5_NET_INSTALLED1 '+op['net_id']+' current_boot_suppressed=1 service_preserved=1 rebooted=0\n').encode()
    return b'A7R5_NET_POST1\n'+(op['net_dir']+'/network.so\n').encode()+(root/'materials/expected-ready.bin').read_bytes()+(op['net_id']+'\nA7R5_NET_POST_END1\n').encode()


def test_install_current_instance_and_no_start_no_reboot(package,tmp_path):
    root,op=package;out=tmp_path/'out';out.mkdir();calls=[]
    def transport(command,data,environment,**kw):
        calls.append((command,data));assert 'StrictHostKeyChecking=yes' in command and 'IdentityAgent=none' in command
        return 0,reply(len(calls),root,op),b''
    report=runner.execute(root,op,'install','SECRET_CANARY',out,transport=transport)
    assert report['status']=='passed' and len(calls)==6 and report['uploads']==2
    assert not report['real_boot_verified'] and not report['network_trigger_verified']
    scripts=b'\n'.join(d for _,d in calls if d)
    assert b'--launch' not in scripts and b'DEBUG' not in scripts and b' reboot' not in scripts
    assert op['private_source'].encode()+b'/host_ecdsa' not in scripts


@pytest.mark.parametrize('failure',range(1,7))
def test_transport_failure_never_retries_or_automatically_rolls_back(package,tmp_path,failure):
    root,op=package;out=tmp_path/'out';out.mkdir();calls=[]
    def transport(command,data,environment,**kw):
        calls.append(command)
        if len(calls)==failure:return 255,b'PARTIAL',b'SECRET_CANARY'
        return 0,reply(len(calls),root,op),b''
    with pytest.raises(RuntimeError):runner.execute(root,op,'install','SECRET_CANARY',out,transport=transport)
    assert len(calls)==failure
    result=json.loads((out/'result.json').read_text());assert result['status']=='failed' and result['reboot_attempts']==0
    assert all(b'SECRET_CANARY' not in p.read_bytes() for p in out.iterdir())


@pytest.mark.parametrize('fault',['uid','ready','namespace','mount','frozen','preload','original','public','trailing'])
def test_preflight_refuses_before_any_writes(package,tmp_path,fault):
    root,op=package;raw=evidence(root,op)
    if fault=='uid':raw=raw.replace(b'Uid:\t0',b'Uid:\t1')
    if fault=='ready':raw=raw.replace(b'parent=1339',b'parent=1338')
    if fault=='namespace':raw=raw.replace(op['active_namespace'].encode(),b'mnt:[999]')
    if fault=='mount':raw=raw.replace(b'63 56 0:22',b'63 39 0:22')
    if fault=='frozen':raw=raw.replace(b'elapsed_ms=1002000',b'elapsed_ms=1000000')
    if fault=='preload':raw=raw.replace((op['helper_dir']+'/boot.so\n').encode(),b'foreign.so\n')
    if fault=='original':raw=raw.replace(next(iter(op['original_hashes'].values())).encode(),b'f'*64)
    if fault=='public':raw=raw.replace(b'ecdsa-sha2-nistp256',b'ssh-rsa')
    if fault=='trailing':raw+=b'EXTRA'
    out=tmp_path/'out';out.mkdir();calls=[]
    def transport(*args,**kwargs):calls.append(args);return 0,raw,b''
    with pytest.raises(ValueError):runner.execute(root,op,'install','TEST',out,transport=transport)
    assert len(calls)==1


@pytest.mark.parametrize('action,prefix',[('rollback','A7R5_NET_ROLLED_BACK1'),('neutralize','A7R5_NET_NEUTRAL1')])
def test_recovery_calls_only_static_controller_once(package,tmp_path,action,prefix):
    root,op=package;out=tmp_path/'out';out.mkdir();calls=[]
    def transport(command,data,environment,**kw):
        calls.append(data);assert b'--launch' not in data and b'kill' not in data and b'ssh-service.arm64' not in data
        return 0,(prefix+' '+op['net_id']+' service_preserved=1\n').encode(),b''
    assert runner.execute(root,op,action,'TEST',out,transport=transport)['status']=='passed'
    assert len(calls)==1


def sealed(root,op):
    (root/'operation.json').write_text(json.dumps(op))
    data={str(p.relative_to(root)):runner.sha(p) for p in root.rglob('*') if p.is_file()}
    (root/'seal.json').write_text(json.dumps(dict(files=data)))
    return runner.sha(root/'seal.json')


def test_missing_approval_template_and_lock_block_network(package,tmp_path,monkeypatch):
    root,op=package;digest=sealed(root,op);monkeypatch.setattr(runner,'HERE',root)
    with pytest.raises(PermissionError):runner.main(['install'])
    approval=tmp_path/'approval.json'
    data=dict(schema='a7r5-network-autostart-approval-v1',action='install',net_id=op['net_id'],seal_sha256=digest,
              approved=False,risk=runner.RISK,no_reboot=True,preserve_current_service=True)
    approval.write_text(json.dumps(data))
    with pytest.raises(PermissionError):runner.approved(root,approval,'install',op,digest)
    data['approved']=True;approval.write_text(json.dumps(data));calls=[]
    monkeypatch.setattr(runner.credentials,'load',lambda p:'TEST')
    def fail(*a,**kw):calls.append(1);raise TimeoutError('synthetic transport failure')
    monkeypatch.setattr(runner,'execute',fail)
    args=['install','--approval',str(approval),'--credentials',str(tmp_path/'external')]
    with pytest.raises(TimeoutError):runner.main(args)
    with pytest.raises(FileExistsError):runner.main(args)
    assert calls==[1] and (root/'attempt-install.lock').exists()


def test_seal_rejects_changed_payload(package):
    root,op=package;sealed(root,op);(root/'materials/network.so').write_bytes(b'bad')
    with pytest.raises(ValueError):runner.verify(root)
