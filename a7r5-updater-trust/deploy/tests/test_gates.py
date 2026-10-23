"""批准、夹具隔离与材料绑定都必须在真实设备操作之前拒绝。"""
import json
from pathlib import Path
import shutil
import pytest
import build
import controller


def test_missing_approval_and_device_flag_do_not_touch_backend(sealed,monkeypatch):
    def forbidden():raise AssertionError('未批准却初始化后端')
    monkeypatch.setattr(controller,'runtime',forbidden)
    with pytest.raises(PermissionError):controller.execute(sealed,False)
    with pytest.raises(FileNotFoundError):controller.execute(sealed,True)
    with pytest.raises(FileNotFoundError):controller.terminal(sealed)
    assert not (sealed/'ATTEMPT_LOCK').exists() and not (sealed/'approval.json').exists()
    assert build.check(sealed)['fixture'] is False


def test_wrong_confirmation_phrase_has_no_effect(sealed):
    with pytest.raises(PermissionError):controller.authorize(sealed,'APPROVE-wrong')
    assert not (sealed/'approval.json').exists()


def test_moved_or_tampered_package_rejected(tmp_path,sealed):
    copy=tmp_path/sealed.name;shutil.copytree(sealed,copy)
    with pytest.raises(ValueError):build.check(copy)
    manifest=json.loads((copy/'manifest.json').read_text());manifest['directory']=str(copy)
    (copy/'manifest.json').write_text(json.dumps(manifest))
    payload=copy/'materials/libJit.so';raw=bytearray(payload.read_bytes());raw[-1]^=1;payload.write_bytes(raw)
    with pytest.raises(ValueError):build.check(copy)


def test_fixture_cannot_be_relabelled_production(tmp_path):
    import os
    source=Path(os.environ['A7R5_TRUST_FIXTURE_RUN']);copy=tmp_path/source.name;shutil.copytree(source,copy)
    manifest=json.loads((copy/'manifest.json').read_text());manifest['directory']=str(copy)
    (copy/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='夹具库'):build.check(copy)
    manifest['fixture']=False;manifest['payload']['fixture']=False
    (copy/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='内部'):build.check(copy)


def test_firmware_preload_profile_cannot_widen_targets():
    profile=json.loads((build.HERE/'profile-historical.json').read_text())
    for key,value in [('location_id',0x01100000),('model','ILCE-7CM2')]:
        changed=json.loads(json.dumps(profile));changed['host_baseline'][key]=value
        with pytest.raises(ValueError):build.validate_profile(changed,'blank-512')
    changed=json.loads(json.dumps(profile));changed['interfaces']['interface-2.json']['endpoints'][0]['attributes']=3
    with pytest.raises(ValueError):build.validate_profile(changed,'blank-512')
    profile['preload_baselines']=[['blank-512',b'unknown'.hex()]]
    with pytest.raises(ValueError):build.validate_profile(profile,'blank-512')


def test_screen_confirmation_cannot_override_failed_attempt(tmp_path,sealed):
    import hashlib
    path=tmp_path/'failed';path.mkdir();(path/'result').mkdir()
    (path/'manifest.json').write_text('{}')
    (path/'result/result.json').write_text(json.dumps(dict(execution_succeeded=False,host_recovery_verified=True)))
    # 拒绝发生在读取pending／删除门禁之前，模拟上层已经校验过的材料。
    from unittest.mock import patch
    with patch.object(controller,'check',return_value=dict(run_id='x')):
        with pytest.raises(ValueError):controller.confirm_screen(path,True)


def test_exact_approval_is_single_use_and_does_not_start_device(tmp_path,monkeypatch):
    path=tmp_path/'run'
    path.mkdir();(path/'manifest.json').write_text('{}')
    monkeypatch.setattr(controller,'check',lambda _:dict(run_id='run'))
    token='APPROVE-'+build.digest(path/'manifest.json')[:20]
    assert controller.authorize(path,token)['camera_IO'] is False
    assert controller.approved(path)['run_id']=='run'
    (path/'ATTEMPT_LOCK').mkdir()
    with pytest.raises(FileExistsError):controller.approved(path)
    with pytest.raises(FileExistsError):controller.authorize(path,token)


def test_metadata_rejection_keeps_pending_and_prevents_reentry(tmp_path,sealed,monkeypatch):
    from types import SimpleNamespace
    path=tmp_path/'run';path.mkdir();(path/'manifest.json').write_text('{}')
    (path/'config.json').write_bytes((sealed/'config.json').read_bytes())
    monkeypatch.setattr(controller,'HERE',tmp_path)
    monkeypatch.setattr(controller,'MODULE',tmp_path/'module')
    host=SimpleNamespace(snapshot=lambda *a,**k:dict(kind='absent'))
    def forbidden(*args,**kwargs):raise AssertionError('主机拒绝后不得接入协议')
    result=controller.run_attempt(path,host,forbidden,SimpleNamespace(run_session=forbidden))
    assert not result['execution_succeeded'] and not result['partition_write_may_have_started']
    assert (path/'ATTEMPT_LOCK').is_dir() and (tmp_path/'PENDING_RECOVERY.json').is_file()
    with pytest.raises(PermissionError):controller.run_attempt(path,host,forbidden,SimpleNamespace(run_session=forbidden))


def test_copied_terminal_script_refuses_before_privileged_entry(tmp_path,sealed):
    import re,shlex,subprocess
    marker=tmp_path/'would-enter-privileged-command'
    text=(sealed/'run-once.command').read_text()
    # 把特权调用替换成纯本机标记；即使复现旧缺陷也不运行sudo。
    safe,count=re.subn(r'^exec sudo .*$',lambda _: '/usr/bin/touch '+shlex.quote(str(marker))+'\nexit 0',text,flags=re.M)
    assert count==1 and 'exec sudo' not in safe
    copied=tmp_path/'copied.command';copied.write_text(safe)
    result=subprocess.run(['/bin/zsh',str(copied)],capture_output=True,text=True)
    assert result.returncode==2 and not marker.exists(),'复制旧脚本不能回指原目录进入特权执行'
