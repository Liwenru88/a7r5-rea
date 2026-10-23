"""普通临时文件的失败注入；不会运行目标ELF或访问相机。"""
import hashlib,json,os,subprocess
from pathlib import Path
import pytest
HERE=Path(__file__).resolve().parents[1]
WORK=next(p for p in HERE.parents if (p/'a7r5-qemu/runtime/manifest.json').is_file())
AID='a'*32
PUBLIC=b'PUBLIC_TEST_ONLY\n';READY=b'READY_TEST_ONLY\n'
HOOK=b'H'*128;HELPER=b'X'*192

def sha(raw):return hashlib.sha256(raw).hexdigest()

@pytest.fixture
def lab(tmp_path):
    root=tmp_path/'etc';ram=tmp_path/'ram';root.mkdir();ram.mkdir()
    stage=ram/'stage';stage.mkdir(mode=0o700)
    active=ram/'active';active.mkdir(mode=0o700)
    private=ram/'private';private.mkdir(mode=0o700)
    ns=tmp_path/'ns';ns.symlink_to('mnt:[900]')
    selfexe=tmp_path/'self';selfexe.write_bytes(b'TEST_STATIC_SELF')
    (stage/'boot.so').write_bytes(HOOK);(stage/'ssh-service.arm64').write_bytes(HELPER)
    (active/'host-public-key').write_bytes(PUBLIC);(active/'ready').write_bytes(READY)
    (private/'host_ecdsa').write_bytes((b'PRIVATE_CANARY'*40)[:505])
    assert (private/'host_ecdsa').stat().st_size==505
    (private/'host_ecdsa').chmod(0o600)
    (root/'ld.so.preload').write_bytes(b'\n'*512)
    auto=root/('a7r5-autostart-'+AID)
    values=dict(AUTO_ID=AID,AUTO_NAME=auto.name,AUTO_DIR=str(auto),ETC_ROOT=str(root),PRELOAD_LINE=str(auto)+'/boot.so\n',
       PRELOAD_NEW='new',PRELOAD_RESTORE='restore',STAGE_DIR=str(stage),PRIVATE_SOURCE=str(private),RAM_ROOT=str(active),
       RAM_PARENT=str(ram),CLAIM_NAME='claim',ACTIVE_NS='mnt:[900]',PROC_NS=str(ns),SELF_EXE=str(selfexe),
       PUBLIC_SHA=sha(PUBLIC),READY_SHA=sha(READY),HELPER_SHA=sha(HELPER),HOOK_SHA=sha(HOOK))
    (tmp_path/'auto_config.h').write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in values.items()))
    header=tmp_path/'host.h'
    header.write_text('''#define NS_HOST_TEST 1
#include "ns_abi.h"
static int fake_statfs(int fd,void *v){(void)fd;long *p=v;memset(p,0,256);p[0]=getenv("AS_NOT_TMPFS")?123:0x01021994;p[1]=4096;p[4]=getenv("AS_LOW_SPACE")?1:1024;return 0;}
static int fake_syncfs(int fd){static int calls;calls++;(void)fd;if(getenv("AS_SYNC_FAIL")||(getenv("AS_SYNC_COMMIT_FAIL")&&calls==2)){errno=5;return -1;}return 0;}
static int fake_rename(int a,const char *p,int b,const char *q){if(getenv("AS_RENAME_FAIL")){errno=5;return -1;}return renameat(a,p,b,q);}
#define AS_FSTATFS fake_statfs
#define AS_SYNCFS fake_syncfs
#define AS_RENAME fake_rename
''')
    binary=tmp_path/'control'
    command=['/usr/bin/clang','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function','-DAS_OWNER='+str(os.getuid()),'-I',str(WORK/'a7r5-ssh/src'),'-I',str(tmp_path),'-include',str(header),str(HERE/'src/control.c'),'-o',str(binary)]
    result=subprocess.run(command,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr.decode()
    def run(action,**env):
        p=subprocess.run([str(binary),action],capture_output=True,env={**os.environ,**env},timeout=3)
        assert b'PRIVATE_CANARY' not in p.stdout+p.stderr
        return p
    return dict(root=root,ram=ram,stage=stage,active=active,private=private,ns=ns,auto=auto,run=run)

def neutral(lab):return (lab['root']/'ld.so.preload').read_bytes()==b'\n'*512

def test_enable_disable_preserves_original_service(lab):
    before={p.name:p.read_bytes() for p in lab['active'].iterdir()}
    assert lab['run']('enable').returncode==0
    assert (lab['auto']/'host_ecdsa').read_bytes()==(lab['private']/'host_ecdsa').read_bytes()
    assert (lab['auto']/'ssh-service.arm64').stat().st_mode&0o100
    assert (lab['auto']/'control.static').stat().st_mode&0o100
    assert (lab['ram']/'claim/current-boot-suppressed').read_text()==AID+'\n'
    assert lab['run']('inspect').stdout.endswith(b'preload=active\n')
    assert lab['run']('enable').returncode==10
    assert lab['run']('disable').returncode==0 and neutral(lab)
    assert lab['run']('disable').returncode==0
    assert {p.name:p.read_bytes() for p in lab['active'].iterdir()}==before
    assert (lab['auto']/'disabled').exists()

@pytest.mark.parametrize('case,stage',[('unknown',10),('symlink_preload',10),('fifo_preload',10),('existing_install',10),('tamper_hook',12),('tamper_helper',12),('stale_ready',13),('namespace',14),('key_mode',15),('key_symlink',15),('key_fifo',15),('private_not_private',15),('existing_lock',16),('claim',20)])
def test_failures_never_arm_preload(lab,case,stage):
    r=lab['root'];preload=r/'ld.so.preload';key=lab['private']/'host_ecdsa'
    if case=='unknown':preload.write_text('foreign.so\n')
    elif case=='symlink_preload':preload.unlink();preload.symlink_to(lab['active']/'ready')
    elif case=='fifo_preload':preload.unlink();os.mkfifo(preload)
    elif case=='existing_install':lab['auto'].mkdir()
    elif case=='tamper_hook':(lab['stage']/'boot.so').write_bytes(b'altered')
    elif case=='tamper_helper':(lab['stage']/'ssh-service.arm64').write_bytes(b'altered')
    elif case=='stale_ready':(lab['active']/'ready').write_text('stale')
    elif case=='namespace':lab['ns'].unlink();lab['ns'].symlink_to('mnt:[901]')
    elif case=='key_mode':key.chmod(0o755)
    elif case=='key_symlink':key.unlink();key.symlink_to(lab['active']/'ready')
    elif case=='key_fifo':key.unlink();os.mkfifo(key)
    elif case=='private_not_private':lab['private'].chmod(0o755)
    elif case=='existing_lock':(r/'.a7r5-preload-edit.lock').mkdir()
    elif case=='claim':(lab['ram']/'claim').mkdir()
    p=lab['run']('enable');assert p.returncode==stage,p.stdout
    if case not in ('unknown','symlink_preload','fifo_preload'):assert neutral(lab)
    if stage<17:assert not lab['auto'].exists() or case=='existing_install'

@pytest.mark.parametrize('env,stage',[({'AS_NOT_TMPFS':'1'},11),({'AS_LOW_SPACE':'1'},16),({'AS_SYNC_FAIL':'1'},21),({'AS_RENAME_FAIL':'1'},23)])
def test_storage_failures_keep_neutral(lab,env,stage):
    p=lab['run']('enable',**env);assert p.returncode==stage and neutral(lab),p.stdout

@pytest.mark.parametrize('breakage',['helper','hook','marker','directory'])
def test_recovery_independent_of_hook_and_helper(lab,breakage):
    assert lab['run']('enable').returncode==0
    if breakage=='helper':(lab['auto']/'ssh-service.arm64').write_text('broken')
    if breakage=='hook':(lab['auto']/'boot.so').write_text('broken')
    if breakage=='marker':(lab['auto']/'enabled').write_text('broken')
    if breakage=='directory':lab['auto'].rename(lab['auto'].with_name('lost-install'))
    assert lab['run']('recover').returncode==0 and neutral(lab)

def test_unknown_preload_recovery_refuses(lab):
    (lab['root']/'ld.so.preload').write_text('some-other-hook.so\n')
    assert lab['run']('recover').returncode==30
    assert (lab['root']/'ld.so.preload').read_text()=='some-other-hook.so\n'

def test_failed_restore_does_not_claim_success(lab):
    assert lab['run']('enable').returncode==0
    assert lab['run']('disable',AS_RENAME_FAIL='1').returncode==32
    assert not neutral(lab)

@pytest.mark.parametrize('mode,expected',[(0o1777,0),(0o777,20)])
def test_shared_ram_permissions(lab,mode,expected):
    lab['ram'].chmod(mode)
    assert lab['run']('enable').returncode==expected

def test_sync_failure_after_commit_reports_failure_with_active_pointer(lab):
    # 同步失败发生在rename之后：必须报告失败并保留证据，不能宣称已回滚。
    assert lab['run']('enable',AS_SYNC_COMMIT_FAIL='1').returncode==23
    assert not neutral(lab)
    assert (lab['root']/'.a7r5-preload-edit.lock').is_dir()
