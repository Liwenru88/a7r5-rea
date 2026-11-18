"""原厂锁快照边界；不执行目标指令或访问相机。"""
from pathlib import Path
import subprocess

NATIVE=Path(__file__).resolve().parents[1]/'native'

def test_locked_snapshot_is_private_and_failure_never_publishes(tmp_path):
    binary=tmp_path/'snapshot'
    command=['clang','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined','-DAF_MEDIA_SNAPSHOT406_HOST_TEST',
        '-I'+str(NATIVE),str(NATIVE/'af_media_snapshot406.c'),
        str(Path(__file__).with_name('native_media_snapshot406.c')),'-o',str(binary)]
    run=subprocess.run(command,capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    assert 'wrong_getter_unlock_no_publication' in run.stdout
