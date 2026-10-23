"""真实日志回归：旧持久路径失效时只接受当前RAM来源，拒绝先于上传。"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'source_gate.py').is_file() and (p/'candidate_once.py').is_file())
sys.path.insert(0, str(ROOT))
import source_gate


@pytest.fixture
def fixture(tmp_path):
    source = tmp_path / 'var/run' / Path(source_gate.SOURCE).name
    source.mkdir(parents=True, mode=0o700)
    key = source / 'host_ecdsa'; key.write_bytes(b'x'*505); key.chmod(0o600)
    config = source / 'sshd_config'
    config.write_text(f'Port 2222\nHostKey {source}/host_ecdsa\n')
    proc = tmp_path / 'proc'; (proc/'707').mkdir(parents=True); (proc/'900').mkdir()
    (proc/'707/stat').write_text('707 (sshd) '+' '.join(['S']+['0']*18+['295'])+'\n')
    (proc/'900/status').write_text('Name:\tsh\nPPid:\t707\n')
    bb = tmp_path/'busybox'
    # 夹具不读取模拟私钥；仅把本机文件所有者映射为测试用root。
    bb.write_text('#!'+sys.executable+'\n'+'''import os,sys,stat
args=sys.argv[1:]
if args[0]=='readlink':
    p=args[-1]
    if p.endswith('/707/exe'):print('/usr/sbin/sshd')
    elif p.endswith('/707/ns/mnt'):print('mnt:[4026533159]')
    else:print(os.path.realpath(p))
elif args[0]=='ls':
    p=args[-1];s=os.lstat(p)
    print(stat.filemode(s.st_mode),s.st_nlink,0,0,s.st_size,'Oct 21 00:00',p)
elif args[0]=='cat':
    assert args[-1].endswith('/707/stat')
    print(open(args[-1]).read(),end='')
else:raise SystemExit(91)
''');bb.chmod(0o700)
    body=source_gate.script().replace(source_gate.SOURCE,str(source)).replace('/bin/busybox',str(bb)).replace('/proc/',str(proc)+'/').replace('pid=$$','pid=900')
    body=body.replace('for component in /var /var/run ',f'for component in {tmp_path}/var {tmp_path}/var/run ')
    script='set -eu\ndie(){ printf "REFUSED:%s\\n" "$1" >&2; exit 1; }\n'+body+'printf "GATE_PASSED\\n"\n'
    return source,key,config,proc,bb,script


def test_original_failure_is_reproduced_then_ram_source_passes(fixture):
    source,key,config,proc,bb,script=fixture
    old=source.parents[1]/'jiritsu/historical/host_ecdsa'
    # 原03包判断会因持久源不在当前视图中而失败，且与权限无关。
    assert subprocess.run(['/bin/sh','-c',f'[ -f "{old}" ] && [ ! -L "{old}" ]']).returncode == 1
    assert not key.with_suffix('.pub').exists()
    result=subprocess.run(['/bin/sh'],input=script,text=True,capture_output=True)
    assert result.returncode==0 and result.stdout=='GATE_PASSED\n',result.stderr
    assert key.read_bytes()==b'x'*505


@pytest.mark.parametrize('fault',['missing','mode','size','link','directory_mode','directory_link','hardlink','config_key','config_port','pid_reuse','namespace','ancestry'])
def test_source_change_refused(fixture,fault):
    source,key,config,proc,bb,script=fixture
    if fault=='missing':key.unlink()
    elif fault=='mode':key.chmod(0o644)
    elif fault=='size':key.write_bytes(b'x'*506)
    elif fault=='link':
        target=source/'other';key.rename(target);key.symlink_to(target)
    elif fault=='directory_mode':source.chmod(0o755)
    elif fault=='directory_link':
        target=source.with_name('moved');source.rename(target);source.symlink_to(target,target_is_directory=True)
    elif fault=='hardlink':(source/'second').hardlink_to(key)
    elif fault=='config_key':config.write_text('Port 2222\nHostKey /wrong/key\n')
    elif fault=='config_port':config.write_text(f'Port 2223\nHostKey {key}\n')
    elif fault=='pid_reuse':(proc/'707/stat').write_text('707 (sshd) '+' '.join(['S']+['0']*18+['296'])+'\n')
    elif fault=='namespace':bb.write_text(bb.read_text().replace('4026533159','4026539999'))
    elif fault=='ancestry':(proc/'900/status').write_text('Name:\tsh\nPPid:\t1\n')
    result=subprocess.run(['/bin/sh'],input=script,text=True,capture_output=True)
    assert result.returncode!=0 and 'GATE_PASSED' not in result.stdout


def test_readonly_audit_never_opens_key_content():
    # 加载只读逻辑时不加载网络库；确认允许集合在SFTP open前拒绝私钥。
    path=ROOT/'key-source-audit-20261021-02/audit.py'
    code=path.read_text().replace('import paramiko','')
    namespace={'__file__':str(path),'__name__':'offline_audit'}
    exec(compile(code,str(path),'exec'),namespace)
    class Forbidden:
        def open(self,*args):pytest.fail('不应打开密钥')
    for path in [source_gate.SOURCE+'/host_ecdsa',source_gate.SOURCE+'/host_ecdsa.pub','/etc/shadow']:
        with pytest.raises(PermissionError):namespace['read_allowed'](Forbidden(),path)


def test_real_metadata_contract():
    b=source_gate.binding()
    assert b['pid']==707 and b['start_ticks']==295 and b['bytes']==505
    assert b['key'].startswith('/var/run/')
