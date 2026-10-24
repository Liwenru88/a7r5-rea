"""通用libJit的编译配置、主机白名单与Mac结果保存使用同一RAM布局。"""
import json
from pathlib import Path

import pytest

import core
from libjit_operation import Operation
from test_exec import Camera, operation


RUN='abcd'*8
PREFIX='/tmp_wbshd/a7r5-jit-'+RUN


def test_compiled_and_runtime_paths_keep_only_trigger_in_work(tmp_path,monkeypatch):
    tool=tmp_path/'tool';tool.mkdir()
    original=core.HERE
    for name in ['payload/libjit.c','runtime/profile.json']:
        target=tool/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((original/name).read_bytes())
    monkeypatch.setattr(core,'HERE',tool);monkeypatch.setattr(core,'check_tool',lambda:None)
    first=core.prepare('libjit','echo ram-result',1)
    second=core.prepare('libjit','echo ram-result',1)
    assert first!=second
    for directory in [first,second]:
        cfg=json.loads((directory/'config.json').read_text());rid=cfg['run_id']
        prefix='/tmp_wbshd/a7r5-jit-'+rid
        assert cfg['control_layout']=='ram-flat-v1' and cfg['control_prefix']==prefix
        header=(directory/'materials/jit_config.h').read_text()
        for key,suffix in [('TICKET_PATH','.ticket'),('CLAIM_PATH','.claim'),('STATE_PATH','.state'),('STATE_NEW','.state.new'),('OUTPUT_PATH','.output')]:
            assert '#define '+key+' '+json.dumps(prefix+suffix)+'\n' in header
        assert '#define LIBJIT_PATH "/tmp/jiritsu/libJit.so"\n' in header
        assert '/tmp/jiritsu/a7r5-jit-' not in header
        payload=(directory/'materials/libJit.so').read_bytes()
        assert prefix.encode() in payload and b'/tmp/jiritsu/a7r5-jit-' not in payload
        instance=Operation(directory)
        assert instance.prefix==prefix
        assert set(instance.writes)=={prefix+'.ticket','/tmp/jiritsu/libJit.so'}
        assert {path for path in instance.reads if path.startswith('/tmp/jiritsu/')}=={'/tmp/jiritsu/libJit.so'}
        assert not (directory/'result').exists()


@pytest.mark.parametrize('change',[{'control_prefix':'/tmp/jiritsu/a7r5-jit-'+RUN},
    {'control_prefix':'/tmp_wbshd/a7r5-jit-'+('0'*32)}, {'control_layout':'unknown'}])
def test_layout_mismatch_rejected_before_any_transport(tmp_path,change):
    instance=operation(tmp_path/'run','libjit')
    config=instance.config;config.update(change)
    (instance.bundle/'config.json').write_text(json.dumps(config))
    with pytest.raises(ValueError):Operation(instance.bundle)


def test_protocol_uses_ram_but_archives_outputs_and_states_on_mac(tmp_path):
    import hashlib
    instance=operation(tmp_path/'run','libjit')
    instance.config['version_sha256']=hashlib.sha256(b'fixed-version').hexdigest()
    driver=Camera(instance,'libjit');out=tmp_path/'host-session';out.mkdir();report={}
    instance(driver,out,lambda *args,**kwargs:None,report)
    assert instance.prefix.startswith('/tmp_wbshd/')
    assert [path for path,_ in driver.puts]==[instance.prefix+'.ticket','/tmp/jiritsu/libJit.so']
    assert instance.safe_to_stop and driver.triggers==1
    assert (out/'shell-output.bin').read_bytes()==driver.output
    assert (out/'state-repeat.bin').read_bytes().startswith(b'A7R5-JIT-1 ')
    assert not report['debug_commands_sent'] and not report['preload_written']


def test_ram_ticket_failure_never_falls_back_to_work_or_triggers_library(tmp_path):
    import hashlib
    instance=operation(tmp_path/'run','libjit')
    instance.config['version_sha256']=hashlib.sha256(b'fixed-version').hexdigest()
    driver=Camera(instance,'libjit','ram-full');out=tmp_path/'host-session';out.mkdir()
    with pytest.raises(ValueError):instance(driver,out,lambda *args,**kwargs:None,{})
    assert [path for path,_ in driver.puts]==[instance.prefix+'.ticket']
    assert driver.triggers==0 and not instance.safe_to_stop
