"""简化入口可连续调用；仅替换设备与sudo边界，真实构建和材料校验照常执行。"""
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

import core
import controller

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('exec_entry',ROOT/'exec.py')
entry=importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


@pytest.fixture
def simple_tool(tmp_path,monkeypatch):
    tool=tmp_path/'tool';tool.mkdir()
    for name in ['runtime/profile.json','payload/libjit.c']:
        target=tool/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    monkeypatch.setattr(core,'HERE',tool)
    monkeypatch.setattr(core,'check_tool',lambda:None)
    monkeypatch.setattr(controller.sys,'platform','darwin')
    monkeypatch.setattr(controller.os,'geteuid',lambda:0)
    monkeypatch.setattr(controller.os,'chown',lambda *a,**k:None)
    return tool


@pytest.mark.parametrize('first_fault',[None,'task-failure','host-mismatch'])
def test_simple_command_runs_again_without_approval_or_recovery_gate(simple_tool,monkeypatch,capsys,first_fault):
    tool=simple_tool
    pending=tool/'PENDING_RECOVERY.json';pending.write_text('legacy-evidence\n')
    directories=[];camera_runs=[];results=[]
    baseline=json.loads((tool/'runtime/profile.json').read_text())['host_baseline']
    def snapshot(*args):
        row=dict(baseline,kind='ordinary')
        if len(directories)==1 and first_fault=='host-mismatch':row['location_id']='wrong-port'
        return row
    host=SimpleNamespace(snapshot=snapshot,observe=lambda *a:dict(recovered=True))
    monkeypatch.setattr(controller,'snapshot_runtime',lambda:host)
    def camera(directory,op):
        camera_runs.append(directory)
        cfg=json.loads((directory/'config.json').read_text())
        session=directory/'result/session';session.mkdir()
        (session/'shell-output.bin').write_bytes((cfg['expected_output_begin']+'hello\n'+cfg['expected_output_end']).encode())
        report=dict(protocol_gate_passed=True,root_task_done=True,trigger_attempts=1,
                    fixed_writes_attempted=2,service_stop_attempts=1,preload_unchanged=True)
        if len(directories)==1 and first_fault=='task-failure':
            report.update(failure='TIMEOUT',protocol_gate_passed=False,service_stop_attempts=0)
        return report
    monkeypatch.setattr(controller,'camera_session',camera)
    original=subprocess.run
    def local_process(argv,**kwargs):
        if argv[0]!='/usr/bin/sudo':return original(argv,**kwargs)
        assert argv[2:4]==['-B',str(tool/'exec.py')]
        assert argv[4]=='execute' and argv[-1]=='--device-io'
        directory=Path(argv[argv.index('--run')+1]);directories.append(directory)
        result=controller.execute(directory,True);results.append(result)
        return subprocess.CompletedProcess(argv,0 if result['execution_succeeded'] else 3,
                                           stdout=json.dumps(result).encode())
    monkeypatch.setattr(subprocess,'run',local_process)
    first=entry.main(['run','--command','echo hello'])
    assert first==(0 if first_fault is None else 3)
    assert entry.main(['run','--command','echo hello'])==0
    assert len(directories)==2 and directories[0]!=directories[1]
    assert len(camera_runs)==(1 if first_fault=='host-mismatch' else 2)
    assert pending.read_text()=='legacy-evidence\n'
    for directory,result in zip(directories,results):
        assert not any((directory/name).exists() for name in ['approval.json','approval-template.json','ATTEMPT_LOCK'])
        assert result['screen_confirmation_pending'] is False
        assert (directory/'result/result.json').is_file()
    assert capsys.readouterr().out=='hello\n'*(2 if first_fault is None else 1)


@pytest.mark.parametrize('input_mode',['command','script'])
def test_prepare_only_never_launches_device_process(simple_tool,monkeypatch,capsys,input_mode):
    original=subprocess.run
    def offline(argv,**kwargs):
        assert argv[0]!='/usr/bin/sudo'
        return original(argv,**kwargs)
    monkeypatch.setattr(subprocess,'run',offline)
    marker=simple_tool/'should-not-exist'
    task='touch '+shlex.quote(str(marker))+'; echo hello'
    args=['--command',task]
    if input_mode=='script':
        script=simple_tool/'input.sh';script.write_text(task)
        args=['--script',str(script)]
    assert entry.main(['run',*args,'--prepare-only'])==0
    value=json.loads(capsys.readouterr().out)
    assert value['offline_only'] is True and value['engine']=='libjit'
    assert 'consent_phrase' not in value
    directory=Path(value['directory'])
    launcher=shlex.split((directory/'run-once.command').read_text().splitlines()[-1])
    assert launcher[1]==str(Path(sys.executable).absolute())
    assert 'run' in launcher and '--script' in launcher
    assert not (directory/'result').exists()
    assert not (simple_tool/'ACTIVE_SESSION.lock').exists()
    assert not marker.exists() and (directory/'task.sh').read_text()==task


def test_simple_entry_cannot_switch_to_kit(simple_tool):
    with pytest.raises(SystemExit) as error:
        entry.main(['run','--engine','kit','--command','echo hello'])
    assert error.value.code==2
    assert not (simple_tool/'runs').exists()
