"""独立封包器的RAM控制路径与固定库路径分离，不改历史包。"""
import json

import pytest

import operation as op
from test_contract import bundle,Service,OUTPUT


RUN='1234abcd'*4


def test_fixed_protocol_saves_ram_results_to_mac(tmp_path):
    instance=op.Operation(bundle(tmp_path/'bundle'),Service)
    assert instance.prefix=='/tmp_wbshd/a7r5-jit-'+RUN
    assert set(instance.writes)=={instance.prefix+'.ticket','/tmp/jiritsu/libJit.so'}
    assert {path for path in instance.reads if path.startswith('/tmp/jiritsu/')}=={'/tmp/jiritsu/libJit.so'}
    output=tmp_path/'host-result';output.mkdir();report={}
    instance(None,output,lambda *args,**kwargs:None,report)
    assert (output/'shell-output.bin').read_bytes()==OUTPUT
    assert (output/'state-repeat.bin').read_bytes().startswith(b'A7R5-JIT-1 ')
    assert instance.safe_to_stop and report['trigger_attempts']==1


@pytest.mark.parametrize('change',[{'control_prefix':'/tmp/jiritsu/a7r5-jit-'+RUN},
    {'control_prefix':'/tmp_wbshd/a7r5-jit-'+('0'*32)}, {'control_layout':'unknown'}])
def test_stale_or_mismatched_control_layout_is_not_silently_reused(tmp_path,change):
    package=bundle(tmp_path/'bundle');config=json.loads((package/'config.json').read_text());config.update(change)
    (package/'config.json').write_text(json.dumps(config))
    with pytest.raises(ValueError):op.Operation(package)
