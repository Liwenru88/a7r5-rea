"""源码构建器契约；成品包不携带依赖本机源码工程的封包器。"""
import json
import pytest
import build


@pytest.mark.parametrize('library_root',['/tmp/jiritsu','/simulation/libjit/case-0'])
def test_real_payload_uses_ram_control_files_even_with_guest_library_root(tmp_path,library_root):
    run='1234abcd'*4;directory=tmp_path/'candidate'
    proof=build.compile_payload(directory,run,'echo offline',1,library_root)
    prefix='/tmp_wbshd/a7r5-jit-'+run
    header=(directory/'jit_config.h').read_text()
    for key,suffix in [('TICKET_PATH','.ticket'),('CLAIM_PATH','.claim'),('STATE_PATH','.state'),('STATE_NEW','.state.new'),('OUTPUT_PATH','.output')]:
        assert '#define '+key+' '+json.dumps(prefix+suffix)+'\n' in header
    assert '#define LIBJIT_PATH '+json.dumps(library_root+'/libJit.so')+'\n' in header
    assert not proof['needed'] and not proof['undefined']
    raw=(directory/'libJit.so').read_bytes()
    assert prefix.encode() in raw and b'/tmp/jiritsu/a7r5-jit-' not in raw
