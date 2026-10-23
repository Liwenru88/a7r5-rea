"""主机调度门槛：批准、单次锁、USB恢复和屏幕回执互不替代。"""
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import tool


@pytest.fixture
def context(tmp_path,monkeypatch):
    project=tmp_path/'project';(project/'a7r5-exec').mkdir(parents=True)
    coordinator=project/'coordinator';coordinator.mkdir()
    package=coordinator/'package';package.mkdir(mode=0o700)
    (package/'manifest.json').write_text('{}')
    baseline=dict(location_id=1048576,media=[[True,67108864]],drivers=['driver'])
    (package/'config.json').write_text(json.dumps(dict(host_baseline=baseline)))
    manifest=dict(project=str(project),coordinator=str(coordinator),run_id='ab'*16,qemu_only=False)
    monkeypatch.setattr(tool,'check',lambda _:manifest)
    monkeypatch.setattr(tool,'phrase',lambda p,a:'ACCEPT-'+a)
    monkeypatch.setattr(tool.os,'geteuid',lambda:0)
    monkeypatch.setattr(tool.os,'chown',lambda *a,**kw:None)
    class Host:
        recovered=True
        @staticmethod
        def snapshot(*a,**kw):return dict(kind='ordinary',**baseline)
        @classmethod
        def observe(cls,*a,**kw):return dict(recovered=cls.recovered)
    monkeypatch.setattr(tool,'snapshot_runtime',lambda _:Host)
    return package,coordinator,manifest,Host


@pytest.mark.parametrize('fault',['no-approval','pending','qemu','previous','symlink'])
def test_device_guard_faults_before_camera(context,monkeypatch,fault):
    package,coordinator,m,host=context
    monkeypatch.setattr(tool,'camera_session',lambda *a:pytest.fail('must not open USB'))
    action='load-once'
    if fault=='pending':(coordinator/'PENDING_RECOVERY.json').write_text('{}')
    if fault=='qemu':m['qemu_only']=True
    if fault=='previous':action='start-once'
    if fault=='symlink':(package/'.state').symlink_to(coordinator,target_is_directory=True)
    with pytest.raises((PermissionError,ValueError,FileNotFoundError)):
        tool.execute(package,action,'wrong' if fault=='no-approval' else 'ACCEPT-'+action,True)


@pytest.mark.parametrize('fault',['none','usb-recovery','write-count','protocol'])
def test_full_host_result_controls_confirmation_and_retains_lock(context,monkeypatch,fault):
    package,coordinator,m,host=context
    host.recovered=fault!='usb-recovery'
    calls=[]
    ownership=[]
    monkeypatch.setattr(tool.os,'chown',lambda path,*a,**kw:ownership.append(path))
    def camera(p,a,out):
        calls.append(a)
        return dict(protocol_gate_passed=fault!='protocol',preload_unchanged=True,
                    fixed_writes_attempted=99 if fault=='write-count' else 3,trigger_attempts=0,
                    service_stop_attempts=1,service_stop_result='error',service_stop_error='Pipe error')
    monkeypatch.setattr(tool,'camera_session',camera)
    result=tool.execute(package,'load-once','ACCEPT-load-once',True)
    assert calls==['load-once'] and result['passed']==(fault=='none')
    assert package/'.state' in ownership
    assert (coordinator/'PENDING_RECOVERY.json').exists()
    if fault=='none':
        receipt=tool.confirm_screen(package,'load-once',True)
        assert receipt['device_requests']==0 and not (coordinator/'PENDING_RECOVERY.json').exists()
        assert (package/'.state/load-once/result.json').exists()
        with pytest.raises(FileExistsError):tool.execute(package,'load-once','ACCEPT-load-once',True)
    else:
        with pytest.raises(ValueError):tool.confirm_screen(package,'load-once',True)
        assert (coordinator/'PENDING_RECOVERY.json').exists()


def test_material_hash_and_symlinks_rejected_without_runtime_import(tmp_path):
    package=tmp_path/'package';package.mkdir(mode=0o700)
    file=package/'source.py';file.write_text('fixed')
    manifest=dict(schema='a7r5-libjit-ssh-package-1',directory=str(package),
                  python_real=str(Path(sys.executable).resolve()),dependencies={},files={'source.py':tool.sha(file)})
    (package/'manifest.json').write_text(json.dumps(manifest))
    assert tool.check(package)==manifest
    file.write_text('changed')
    with pytest.raises(ValueError):tool.check(package)
    file.unlink();file.symlink_to(package/'manifest.json')
    with pytest.raises(ValueError):tool.check(package)


def test_stop_screen_refuses_other_active_owner_before_clearing_pending(context):
    package,coordinator,m,host=context
    out=package/'.state/stop-once';out.mkdir(parents=True)
    binding=dict(run_id=m['run_id'],package=str(package),action='stop-once',manifest_sha256=tool.sha(package/'manifest.json'))
    tool.save(out/'result.json',dict(**binding,passed=True,host_recovery_verified=True))
    tool.save(coordinator/'PENDING_RECOVERY.json',binding)
    tool.save(coordinator/'ACTIVE_SERVICE.json',dict(run_id='different'))
    with pytest.raises(ValueError):tool.confirm_screen(package,'stop-once',True)
    assert (coordinator/'PENDING_RECOVERY.json').exists() and not (out/'screen.json').exists()
