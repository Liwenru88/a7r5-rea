"""主机只用假传输：验证门槛、停止、不重试和凭据脱敏。"""
from pathlib import Path
import importlib.util,json,sys,hashlib
import pytest
HERE=Path(__file__).resolve().parents[1]
WORK=next(p for p in HERE.parents if (p/'a7r5-qemu/runtime/manifest.json').is_file())
sys.path[:0]=[str(HERE),str(HERE.parent)]
import runner

@pytest.fixture
def package(tmp_path):
    op=json.loads((HERE/'operation.json').read_text())
    (tmp_path/'materials').mkdir()
    for name in ('expected-ready.bin','trusted-host-public-key','control.static','boot.so','ssh-service.arm64'):
        (tmp_path/'materials'/name).write_bytes((HERE/'materials'/name).read_bytes())
    (tmp_path/'known_hosts').write_text('TEST_ONLY')
    return tmp_path,op

def evidence(root,op):
    # 成功路径直接复用实机响应，防止简化夹具再次漏掉底层挂载。
    return (HERE/'tests/fixtures/live-preflight-20261021-01.txt').read_bytes()

@pytest.mark.parametrize('change',['uid','namespace','ready','public','mount','duplicate','trailing'])
def test_preflight_rejects_changed_evidence(package,change):
    root,op=package;raw=evidence(root,op)
    if change=='uid':raw=raw.replace(b'Uid:\t0',b'Uid:\t1')
    elif change=='namespace':raw=raw.replace(op['active_namespace'].encode(),b'mnt:[777]')
    elif change=='ready':raw=raw.replace(b'parent=1898',b'parent=1897')
    elif change=='public':raw=raw.replace(b'ecdsa-sha2-nistp256',b'ssh-rsa')
    elif change=='mount':raw=raw.replace(b'vfat /dev/nflasha10',b'ext2 /dev/nflasha7')
    elif change=='duplicate':raw=raw.replace(b'===READY===',b'9 0 0:1 / /etc rw - vfat /dev/nflasha10 rw\n===READY===')
    elif change=='trailing':raw+=b'unexpected'
    with pytest.raises(ValueError):runner.validate_preflight(raw,op,root)

@pytest.mark.parametrize('failure',range(6))
def test_each_transport_failure_stops_without_retry(package,tmp_path,failure):
    root,op=package;output=tmp_path/'output';output.mkdir();calls=[];password='TEST_PASSWORD_CANARY'
    def transport(command,data,env,**kw):
        calls.append((command,data))
        assert env['SSH_ASKPASS_REQUIRE']=='force'
        assert '-o' in command and 'ConnectionAttempts=1' in command and 'StrictHostKeyChecking=yes' in command
        if len(calls)==failure+1:return 1,b'',password.encode()
        if len(calls)==1:return 0,evidence(root,op),b''
        if len(calls)==2:return 0,b'A7R5_AUTO_STAGE_READY1\n',b''
        return 0,b'',b''
    with pytest.raises(RuntimeError):runner.execute(root,op,'enable',password,output,transport=transport)
    assert len(calls)==failure+1
    report=json.loads((output/'result.json').read_text());assert report['status']=='failed' and report['reboot_attempts']==0
    assert all(password.encode() not in p.read_bytes() for p in output.iterdir())

def test_success_uses_only_six_connections_and_never_reboots(package,tmp_path):
    root,op=package;output=tmp_path/'output';output.mkdir();calls=[]
    def transport(command,data,env,**kw):
        calls.append((command,data))
        if len(calls)==1:return 0,evidence(root,op),b''
        if len(calls)==2:return 0,b'A7R5_AUTO_STAGE_READY1\n',b''
        if len(calls)<6:return 0,b'',b''
        return 0,('A7R5_AUTO_ENABLED1 '+op['auto_id']+' current_boot_suppressed=1 service_preserved=1 rebooted=0\n').encode(),b''
    report=runner.execute(root,op,'enable','TEST_ONLY',output,transport=transport)
    assert report['status']=='passed' and len(calls)==6
    scripts=b'\n'.join(c[1] for c in calls if c[1])
    assert b' reboot' not in scripts and b'DEBUG' not in scripts and b' stop' not in scripts
    assert b'cat '+op['private_source'].encode()+b'/host_ecdsa' not in scripts

@pytest.mark.parametrize('action',['disable','recover'])
def test_disable_recovery_single_call_no_helper_hash_requirement(package,tmp_path,action):
    root,op=package;output=tmp_path/'output';output.mkdir();calls=[]
    def transport(command,data,env,**kw):
        calls.append(command);assert data==('exec '+op['auto_dir']+'/control.static '+action+'\n').encode()
        return 0,('A7R5_AUTO_NEUTRAL1 '+op['auto_id']+' service_preserved=1\n').encode(),b''
    assert runner.execute(root,op,action,'TEST_ONLY',output,transport=transport)['status']=='passed'
    assert len(calls)==1

def test_unapproved_template_rejected_before_execution(package,tmp_path):
    root,op=package;p=tmp_path/'approval.json';p.write_text(json.dumps(dict(approved=False)))
    with pytest.raises(PermissionError):runner.approval(root,p,'enable',op,'a'*64)

def test_current_pty_sftp_and_ram_key_config_preserved():
    old=(WORK/'a7r5-ssh/ssh-service/ram-key-fix/packages/ram-key-install-20261021-01/materials/config.h').read_text()
    new=(HERE/'materials/config.h').read_text()
    normalize=lambda x:'\n'.join(line for line in x.splitlines() if not line.startswith('#define INSTALL_DIR '))
    assert normalize(old)==normalize(new)
    assert 'PermitTTY yes' in new and 'Subsystem sftp internal-sftp' in new and 'ForceCommand' not in new
    assert '#define SSH_SECONDS 0' in new

def seal_fixture(root,op):
    (root/'operation.json').write_text(json.dumps(op))
    entries={str(p.relative_to(root)):runner.digest(p) for p in root.rglob('*') if p.is_file()}
    (root/'seal.json').write_text(json.dumps(dict(files=entries)))
    return runner.digest(root/'seal.json')

def test_attempt_lock_survives_failure_and_blocks_repeat(package,tmp_path,monkeypatch):
    root,op=package;sealsha=seal_fixture(root,op);approved=tmp_path/'approval.json'
    approved.write_text(json.dumps(dict(schema='a7r5-autostart-approval-v1',action='enable',auto_id=op['auto_id'],seal_sha256=sealsha,
     approved=True,accept_persistent_loader_risk=True,no_reboot=True,preserve_current_service=True)))
    monkeypatch.setattr(runner,'HERE',root);monkeypatch.setattr(runner.credentials,'load',lambda p:'TEST_ONLY')
    calls=[]
    def failure(*args,**kwargs):calls.append('once');raise TimeoutError('injected')
    monkeypatch.setattr(runner,'execute',failure)
    args=['enable','--approval',str(approved),'--credentials',str(tmp_path/'test-secret')]
    with pytest.raises(TimeoutError):runner.main(args)
    assert (root/'attempt-enable.lock').exists()
    with pytest.raises(FileExistsError):runner.main(args)
    assert calls==['once']

def test_main_refuses_no_approval_without_transport(package,monkeypatch):
    root,op=package;seal_fixture(root,op);monkeypatch.setattr(runner,'HERE',root)
    def never(*args,**kwargs):raise AssertionError('transport must not run')
    monkeypatch.setattr(runner,'execute',never)
    with pytest.raises(PermissionError):runner.main(['enable'])

def test_seal_rejects_tampered_payload(package):
    root,op=package;seal_fixture(root,op);(root/'materials/boot.so').write_bytes(b'changed')
    with pytest.raises(ValueError):runner.verify_package(root)

def test_bad_stack_stops_before_stage_or_upload(package,tmp_path):
    root,op=package;output=tmp_path/'output';output.mkdir();calls=[]
    def transport(command,data,env,**kw):
        calls.append(command)
        assert len(calls)==1,'错误挂载视图后不得创建目录或上传'
        return 0,evidence(root,op).replace(b'63 56 0:22',b'63 39 0:22'),b''
    with pytest.raises(ValueError):runner.execute(root,op,'enable','TEST_ONLY',output,transport=transport)
    assert len(calls)==1
    report=json.loads((output/'result.json').read_text())
    assert report['stage']=='preflight' and report['status']=='failed' and not report.get('preflight_verified')

def test_old_approval_cannot_authorize_new_seal(package,tmp_path):
    root,op=package
    # 只复用旧封印的授权数据；本用例不会执行入口或创建尝试锁。
    value=dict(schema='a7r5-autostart-approval-v1',action='enable',auto_id=op['auto_id'],seal_sha256='b65b56f721a75185d33f42b490384a704c88a917102c771418489f3c0603d6b5',
               approved=True,accept_persistent_loader_risk=True,no_reboot=True,preserve_current_service=True)
    p=tmp_path/'old-approval.json';p.write_text(json.dumps(value))
    with pytest.raises(PermissionError):runner.approval(root,p,'enable',op,'0'*64)
