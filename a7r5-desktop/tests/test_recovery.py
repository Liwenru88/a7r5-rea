"""失败任务只恢复连接状态，保留原错误，不能升级为任务成功。"""
import copy
import json
from pathlib import Path

import pytest
import bootstrap
import host


CONTRACT = json.loads((Path(__file__).parent/'fixtures/pre-service-recovery.json').read_text())


@pytest.mark.parametrize('case', CONTRACT['cases'], ids=lambda case: case['name'])
def test_pre_service_recovery_contract(tmp_path, monkeypatch, case):
    previous = copy.deepcopy(CONTRACT['base'])
    previous['report'].update(case['patch'])
    if 'remove' in case:
        previous['report'].pop(case['remove'])
    observations = []
    def snapshot(*args):
        observations.append(args)
        return previous['baseline']
    monkeypatch.setattr(host, 'snapshot', snapshot)
    original_observe = host.observe
    def observe(baseline, take):
        tick = [0]
        return original_observe(baseline, take, clock=lambda: tick[0],
                                sleep=lambda seconds: tick.__setitem__(0, tick[0]+seconds))
    monkeypatch.setattr(host, 'observe', observe)
    before = copy.deepcopy(previous)
    if not case['allowed']:
        with pytest.raises(ValueError):
            bootstrap.execute('recovery', dict(previous=previous), tmp_path)
        assert not observations
    else:
        result = bootstrap.execute('recovery', dict(previous=previous), tmp_path)
        assert result['USB_recovered'] and len(observations) == 3
        assert result['task_complete'] is False and result['error'] == previous['error']
        assert result['host_recovery']['camera_protocol_requests'] == 0
    assert previous == before


def test_recovery_binds_current_connection_instead_of_old_port(tmp_path, monkeypatch):
    previous = copy.deepcopy(CONTRACT['base'])
    current = dict(previous['baseline'], location_id=0x14100000, media=[[True, 200000]])
    observations = []
    def snapshot(*args, **kwargs):
        observations.append((args, kwargs))
        location = kwargs.get('location', args[3] if len(args) > 3 else None)
        if location is not None and location != current['location_id']:
            raise ValueError('设备位置变化或USB身份不支持')
        return current
    monkeypatch.setattr(host, 'snapshot', snapshot)
    original_observe = host.observe
    tick = [0]
    monkeypatch.setattr(host, 'observe', lambda baseline, take: original_observe(
        baseline, take, clock=lambda: tick[0], sleep=lambda n: tick.__setitem__(0, tick[0]+n)))
    result = bootstrap.execute('recovery', dict(previous=previous), tmp_path)
    assert result['USB_recovered'] and result['recovery_baseline'] == current
    assert result['baseline'] == previous['baseline'] and result['task_complete'] is False
    assert observations[0][1].get('location') is None


def test_new_ssh_stop_uses_current_port_and_saved_instance_identity(tmp_path, baseline):
    import base64
    import device
    from types import SimpleNamespace
    active = dict(run_id='b'*32, baseline=dict(baseline, location_id=0x02100000),
                  host_public_key=base64.b64encode(b'saved-instance-key').decode())
    configs = []
    def session(output, transport, _operation):
        configs.append(_operation.config)
        assert (_operation.package/'.state/start-once/host-public-key').read_bytes() == b'saved-instance-key'
        return dict(failure='模拟停止于通信前')
    result = device.run(dict(run_id='c'*32, kind='ssh_stop', active=active), tmp_path.resolve(),
                        session_module=SimpleNamespace(__name__='simulation',run_session=session),
                        host_module=SimpleNamespace(snapshot=lambda *args: baseline))
    assert configs[0]['host_baseline'] == baseline
    assert configs[0]['interfaces']['interface-1.json']['bus'] == 0x14
    assert configs[0]['interfaces']['interface-1.json']['ports'] == [1]
    assert result['run_id'] == active['run_id'] and not result['task_complete']


def test_recovery_refuses_port_change_during_current_check(tmp_path, monkeypatch):
    previous = copy.deepcopy(CONTRACT['base'])
    current = dict(previous['baseline'], location_id=0x14100000)
    samples = iter([current, current, dict(current, location_id=0x14200000)])
    monkeypatch.setattr(host, 'snapshot', lambda *a, **k: next(samples))
    original_observe = host.observe
    tick = [0]
    monkeypatch.setattr(host, 'observe', lambda baseline, take: original_observe(
        baseline, take, clock=lambda: tick[0], sleep=lambda n: tick.__setitem__(0, tick[0]+n)))
    with pytest.raises(ValueError, match='恢复位置不符'):
        bootstrap.execute('recovery', dict(previous=previous), tmp_path)
    assert not previous['USB_recovered']
