"""开发入口的缓存更新与离线启动边界。"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location('desktop_dev', Path(__file__).resolve().parents[1] / 'scripts/dev.py')
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


@pytest.mark.parametrize('changed', ['engine/device.py', 'web/app.js', 'src-tauri/src/main.rs'])
def test_cache_reused_until_source_changes(tmp_path, monkeypatch, changed):
    base = tmp_path / 'prepared/engine'
    base.mkdir(parents=True)
    (base / 'integrity.json').write_text('{}')
    source = tmp_path / changed
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('first')
    cache = tmp_path / 'cache'
    monkeypatch.setattr(dev, 'ROOT', tmp_path)
    monkeypatch.setattr(dev, 'BASE', base)
    monkeypatch.setattr(dev, 'CACHE', cache)
    monkeypatch.setattr(dev.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(dev.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(dev, 'source_inputs', lambda: [source])
    builds, checks = [], []
    def build(paths, key):
        app = cache / key / 'A7R5 Studio.app'
        app.mkdir(parents=True)
        builds.append(key)
        return app
    monkeypatch.setattr(dev, 'build', build)
    monkeypatch.setattr(dev, 'selfcheck', lambda app: checks.append(app) or dict(ok=True))
    monkeypatch.setattr(dev.subprocess, 'run', lambda *a, **k: pytest.fail('仅自检不能打开 GUI 或运行外部命令'))
    # 不同源码使用不同应用目录；缓存命中后仍需自检。
    old_umask = dev.os.umask(0o077)
    try:
        dev.main(['--selfcheck'])
        dev.main(['--selfcheck'])
        source.write_text('second')
        dev.main(['--selfcheck'])
        assert len(builds) == 2 and len(checks) == 3
        launches = []
        monkeypatch.setattr(dev.subprocess, 'run', lambda argv, **k: launches.append(argv))
        dev.main([])
    finally:
        dev.os.umask(old_umask)
    assert len(builds) == 2 and builds[0] != builds[1]
    assert len(checks) == 4 and checks[0] == checks[1] and checks[2] != checks[0]
    assert launches == [['/usr/bin/open', '-a', str(checks[-1])]]
    assert (base / 'integrity.json').read_text() == '{}'


def test_damaged_runtime_is_rejected_before_build(tmp_path, monkeypatch):
    original = tmp_path / 'profile.json'
    original.write_text('original')
    manifest = dict(files={'profile.json': dict(bytes=original.stat().st_size, sha256=dev.sha(original))})
    (tmp_path / 'integrity.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(dev, 'BASE', tmp_path)
    dev.verify_base()
    original.write_text('tampered')
    with pytest.raises(ValueError, match='运行材料校验失败'):
        dev.verify_base()


def test_selfcheck_refuses_camera_access_receipt(tmp_path, monkeypatch):
    proof = dict(ok=True, camera_IO=True, USB_enumerated=True)
    monkeypatch.setattr(dev.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=json.dumps(proof)))
    with pytest.raises(ValueError, match='离线自检回执不完整'):
        dev.selfcheck(tmp_path)


@pytest.mark.parametrize('complete', [True, False])
def test_terminal_backup_keeps_history_and_never_starts_update(tmp_path, monkeypatch, complete):
    data = tmp_path/'data';data.mkdir()
    old = data/'pending.json';old.write_text('historical-record')
    active=data/'active-ssh.json';active.write_text('ssh-instance-record')
    calls = []
    def helper(argv, **kwargs):
        assert argv[0:2] == ['/usr/bin/sudo', '--']
        assert argv[-2] == '--privileged-task'
        request = Path(argv[-1]);calls.append(argv)
        assert json.loads(request.read_text())['kind'] == 'backup'
        proof = dict(task_complete=complete, kind='backup', device_IO=True, simulation=False,
                     backup_file=str(request.parent/'device/session/partition1.logical.bin'),
                     trust_state='unsupported', USB_recovered=True, error='模拟下载超时')
        (request.parent/'privileged-result.json').write_text(json.dumps(proof))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(dev.subprocess, 'run', helper)
    if complete:
        dev.backup(tmp_path/'client.app', data)
    else:
        with pytest.raises(RuntimeError, match='模拟下载超时'):
            dev.backup(tmp_path/'client.app', data)
    assert len(calls) == 1 and old.read_text() == 'historical-record'
    assert active.read_text()=='ssh-instance-record'
    folder = next((data/'tasks').iterdir())
    assert (folder/'request.json').stat().st_mode & 0o777 == 0o600
    assert json.loads((folder/'result.json').read_text())['task_complete'] is complete
    assert json.loads((folder/'status.json').read_text())['running'] is False


def test_terminal_backup_keeps_concurrent_process_lock(tmp_path, monkeypatch):
    import fcntl
    lock=(tmp_path/'application.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    monkeypatch.setattr(dev.subprocess,'run',lambda *a,**k:pytest.fail('进程锁冲突时不能启动设备事务'))
    with pytest.raises(RuntimeError,match='正常退出'):
        dev.backup(tmp_path/'client.app', tmp_path)
    lock.close()
    assert not (tmp_path/'tasks').exists()
