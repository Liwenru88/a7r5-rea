"""材料绑定、单次执行和人工屏幕确认不能被快捷入口跳过。"""
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
import controller


def sealed(tmp_path,monkeypatch):
    tool=tmp_path/'tool';tool.mkdir();monkeypatch.setattr(core,'HERE',tool)
    dependency=tmp_path/'dependency';dependency.write_bytes(b'fixed-tool')
    for name in ['CLANG','LLD','LIBUSB']:monkeypatch.setattr(core,name,dependency)
    (tool/'source.py').write_text('fixed-source\n')
    core.save(tool/'TOOL.json',dict(schema='a7r5-exec-tool-1',resources=core.resources()))
    directory=tool/'runs'/('aabbccdd'*4);directory.mkdir(parents=True)
    (directory/'task.sh').write_text('id\n')
    op=dict(schema='a7r5-exec-once-1',directory=str(directory),tool_root=str(tool),engine='kit',run_id=directory.name,
            risk=core.risk('kit'),resources=core.resources(),
            dependencies={str(p):core.sha(p) for p in [Path(sys.executable).resolve(),dependency]},
            artifacts={'task.sh':core.sha(directory/'task.sh')})
    core.save(directory/'operation.json',op)
    return directory,op,dependency


@pytest.mark.parametrize('fault',['task','source','dependency','approval','accepted-int','used','symlink','moved'])
def test_binding_changes_reject_before_execute(tmp_path,monkeypatch,fault):
    directory,op,dependency=sealed(tmp_path,monkeypatch)
    phrase='ACCEPT-'+core.sha(directory/'operation.json')[:16];core.approve(directory,phrase)
    assert core.approved(directory)==op
    if fault=='task':(directory/'task.sh').write_text('wrong')
    if fault=='source':(core.HERE/'source.py').write_text('wrong')
    if fault=='dependency':dependency.write_bytes(b'wrong')
    if fault in ['approval','accepted-int']:
        value=core.approval_for(directory,op,True);value['accepted']=1 if fault=='accepted-int' else False
        (directory/'approval.json').write_text(json.dumps(value))
    if fault=='used':(directory/'ATTEMPT_LOCK').mkdir()
    if fault=='symlink':(directory/'task.sh').unlink();(directory/'task.sh').symlink_to(dependency)
    if fault=='moved':directory.rename(directory.parent/'moved')
    with pytest.raises((ValueError,PermissionError,FileExistsError,FileNotFoundError)):core.approved(directory)


@pytest.mark.parametrize('success',[False,True])
def test_screen_only_clears_matching_successful_session_marker(tmp_path,monkeypatch,success):
    directory,op,_=sealed(tmp_path,monkeypatch);core.approve(directory,'ACCEPT-'+core.sha(directory/'operation.json')[:16])
    (directory/'result').mkdir();(directory/'ATTEMPT_LOCK').mkdir()
    binding=dict(run_id=op['run_id'],directory=str(directory),operation_sha256=core.sha(directory/'operation.json'))
    core.save(core.HERE/'PENDING_RECOVERY.json',binding)
    core.save(directory/'result/result.json',dict(**binding,execution_succeeded=success,host_recovery_verified=True))
    if success:
        assert controller.confirm_screen(directory,True)['completed']
        assert not (core.HERE/'PENDING_RECOVERY.json').exists()
        assert (directory/'ATTEMPT_LOCK').exists()
        assert (directory/'result/screen-confirmation.json').exists()
    else:
        with pytest.raises(ValueError):controller.confirm_screen(directory,True)
        assert (core.HERE/'PENDING_RECOVERY.json').exists()


def test_wrapper_quotes_script_and_keeps_exit_handling_outside_user_shell():
    script="echo '引号'; printf '%s' \"$(id)\"; exit 17"
    wrapped,begin,end=core.wrapper(script,'abcd'*8)
    assert '/bin/sh -c ' in wrapped and 'task_rc=$?' in wrapped
    assert '|| exit "$task_rc"' in wrapped and begin in wrapped and end in wrapped


@pytest.mark.parametrize('engine',['libjit','kit'])
def test_real_cross_compile_preserves_lld_driver_name(tmp_path,engine):
    task,_,_=core.wrapper('echo "test"','abcd'*8)
    elf=core.compile_payload(tmp_path,engine,'abcd'*8,task,1)
    command=json.loads((tmp_path/'build.json').read_text())['argv']
    assert any(arg.endswith('/ld.lld') for arg in command if arg.startswith('--ld-path='))
    assert elf['bytes']>0
    assert elf['needed']==([] if engine=='libjit' else ['libc.so.6'])
