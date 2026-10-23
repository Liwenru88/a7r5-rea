"""在本机临时目录验证kit监督者；不冒充原厂内核或root身份验收。"""
import json
from pathlib import Path
import resource
import subprocess
import time
import pytest

SOURCE=Path(__file__).resolve().parents[1]/'payload/kit.c'


@pytest.mark.parametrize('script,expected',[('printf okay','DONE 0'),('exit 42','DONE 42'),
                                         ('/bin/sleep 4','TIMEOUT 85'),('/usr/bin/yes X','FAILED 83')])
def test_real_host_kit_supervisor_failure_paths(tmp_path,script,expected):
    prefix=str(tmp_path/'task');arm=prefix+'.so\n'
    values=dict(RUN_ID='abcd'*8,TASK_SCRIPT=script,STATE_PATH=prefix+'.state',OUTPUT_PATH=prefix+'.output',
                ARM_BYTES=arm,PRELOAD_PATH=str(tmp_path/'preload'),GATE_PATH=str(tmp_path/'gate'))
    (tmp_path/'root_config.h').write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in values.items())+
                                       '#define TASK_SECONDS 1U\n#define OUTPUT_LIMIT 32768U\n')
    (tmp_path/'preload').write_text(arm)
    (tmp_path/'gate').write_bytes(b'/bin/sh\0-c\0/bin/date -s 070421422017.26\0')
    exe=tmp_path/'host-test'
    subprocess.run(['/usr/bin/clang','-DA7R5_HOST_TEST','-O2','-Wall','-Wextra','-Werror','-I',str(tmp_path),
                    str(SOURCE),'-o',str(exe)],check=True,capture_output=True,timeout=30)
    def limits():resource.setrlimit(resource.RLIMIT_NOFILE,(256,256))
    subprocess.run([str(exe)],check=True,capture_output=True,timeout=5,preexec_fn=limits)
    deadline=time.monotonic()+10;raw=b''
    while time.monotonic()<deadline:
        state=Path(prefix+'.state')
        if state.exists():
            raw=state.read_bytes()
            if expected.encode() in raw:break
        time.sleep(.02)
    assert expected.encode() in raw
    assert (tmp_path/'preload').read_bytes()==b'\n'*512
    assert Path(prefix+'.output').stat().st_size<=(32768)
