"""真实本机C产物的权限、并发、持久指针和恢复失败注入；没有设备或网络。"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time

import pytest

HERE=Path(__file__).resolve().parents[1]
ID='b'*32
OLD='a'*32
HELPER=b'HELPER_FIXTURE_ONLY'
HOOK=b'HOOK_FIXTURE_ONLY'
PUBLIC=b'PUBLIC_FIXTURE_ONLY\n'
READY=b'READY_FIXTURE_ONLY\n'


def sha(raw):return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def lab(tmp_path):
    root=tmp_path/'etc';root.mkdir()
    ram=tmp_path/'ram';ram.mkdir(mode=0o755)
    old=root/'old';old.mkdir()
    active=ram/'active'
    stage=ram/'stage';stage.mkdir(mode=0o700)
    net=root/'network'
    (old/'ssh-service.arm64').write_bytes(HELPER);(old/'ssh-service.arm64').chmod(0o755)
    (old/'boot.so').write_bytes(b'OLD_HOOK')
    (old/'enabled').write_text(OLD+'\n')
    (stage/'network.so').write_bytes(HOOK)
    (root/'ld.so.preload').write_text(str(old)+'/boot.so\n')
    (tmp_path/'cmdline').write_bytes(b'/usr/bin/wpa_supplicant\0-Dnl80211\0-iwlan0\0')
    (tmp_path/'exe').symlink_to('/usr/bin/wpa_supplicant')
    (tmp_path/'self-ns').symlink_to('mnt:[123]');(tmp_path/'init-ns').symlink_to('mnt:[123]')
    (tmp_path/'tcp').write_text('  sl  local_address rem_address st tx_queue rx_queue\n')
    (tmp_path/'self-real').write_bytes(b'FIXTURE_STATIC_CONTROLLER')
    (tmp_path/'self').symlink_to(tmp_path/'self-real')
    values=dict(NET_ID=ID,OLD_ID=OLD,SERVICE_RUN='c'*32,NET_NAME=net.name,NET_DIR=str(net),NET_TRIGGER='/usr/bin/wpa_supplicant',
        HELPER_DIR=str(old),HELPER_PATH=str(old/'ssh-service.arm64'),HELPER_SHA=sha(HELPER),OLD_HOOK_SHA=sha(b'OLD_HOOK'),
        SERVICE_RAM=str(active),RAM_PARENT=str(ram),CLAIM_NAME='claim',CLAIM_PATH=str(ram/'claim'),
        PROC_CMDLINE=str(tmp_path/'cmdline'),PROC_EXE=str(tmp_path/'exe'),PROC_SELF_NS=str(tmp_path/'self-ns'),
        PROC_INIT_NS=str(tmp_path/'init-ns'),PROC_TCP=str(tmp_path/'tcp'),ETC_ROOT=str(root),STAGE_DIR=str(stage),
        ACTIVE_NS='mnt:[123]',SELF_EXE=str(tmp_path/'self'),READY_SHA=sha(READY),PUBLIC_SHA=sha(PUBLIC),
        OLD_PRELOAD=str(old)+'/boot.so\n',NEW_PRELOAD=str(net)+'/network.so\n',PRELOAD_NEW='new',PRELOAD_RESTORE='restore',HOOK_SHA=sha(HOOK))
    (tmp_path/'net_config.h').write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in values.items())+'#define HELPER_BYTES '+str(len(HELPER))+'\n')
    header=tmp_path/'host.h'
    header.write_text('''#define NS_HOST_TEST 1
#include "ns_abi.h"
static int fake_fs(int fd,void *v){(void)fd;long *p=v;memset(p,0,256);p[0]=getenv("NET_NOT_RAM")?1:0x01021994;p[1]=4096;p[4]=getenv("NET_LOW_SPACE")?1:1024;return 0;}
static int fake_sync(int fd){static int calls;calls++;(void)fd;if(getenv("NET_SYNC_FAIL")||(getenv("NET_COMMIT_SYNC_FAIL")&&calls==2)){errno=5;return -1;}return 0;}
static int fake_rename(int a,const char *p,int b,const char *q){if(getenv("NET_RENAME_FAIL")){errno=5;return -1;}return renameat(a,p,b,q);}
static int fake_detach(void){int fd=open("/dev/null",O_RDWR);if(fd<0)return -1;for(int i=0;i<3;i++)dup2(fd,i);if(fd>2)close(fd);if(getenv("NET_DELAY"))usleep(150000);return 0;}
static int fake_fork(void){if(getenv("NET_FORK_FAIL"))return -1;return fork();}
static void before_final(void){if(getenv("NET_DISABLE_LATE"))unlink(NET_DIR "/enabled");}
static void fake_launch(int fd,char *const *args,char *const *env){(void)args;(void)env;close(fd);if(getenv("NET_CHECK_CHLD")&&signal(SIGCHLD,SIG_DFL)==SIG_IGN)_exit(90);if(getenv("NET_EXEC_FAIL")){errno=8;return;}int out=open(FIXTURE_COUNTER,O_WRONLY|O_CREAT|O_APPEND,0600);if(out>=0){write(out,"1",1);close(out);}_exit(0);}
#define NET_FSTATFS fake_fs
#define NET_SYNCFS fake_sync
#define NET_RENAME fake_rename
#define NET_DETACH fake_detach
#define NET_FORK fake_fork
#define NET_BEFORE_FINAL before_final
#define NET_TEST_LAUNCH fake_launch
''')
    commands=[]
    def build(source,name,entry=False):
        path=tmp_path/name
        command=['/usr/bin/clang','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
            '-Wall','-Wextra','-Werror','-Wno-unused-function','-DNET_OWNER='+str(os.getuid()),
            '-DFIXTURE_COUNTER='+json.dumps(str(tmp_path/'counter')),'-I',str(HERE/'sdk'),'-I',str(HERE/'src'),
            '-I',str(tmp_path),'-include',str(tmp_path/'net_config.h'),'-include',str(header)]
        if entry:command+=['-DNET_TEST_ENTRY']
        command += [str(HERE/'src'/source),'-o',str(path)]
        value=subprocess.run(command,capture_output=True,timeout=30)
        assert value.returncode==0,value.stderr.decode();commands.append(command)
        return path
    cache={}
    def binary(name):
        if name not in cache:cache[name]=build('network_hook.c' if name=='hook' else 'control.c',name,name=='hook')
        return cache[name]
    def run(name,action=None,**env):
        command=[str(binary(name))]+([] if action is None else [action])
        return subprocess.run(command,capture_output=True,env={**os.environ,**env},timeout=5)
    def enabled():
        net.mkdir(exist_ok=True);(net/'enabled').write_text(ID+'\n')
    def existing():
        active.mkdir(mode=0o700);(active/'ready').write_bytes(READY);(active/'host-public-key').write_bytes(PUBLIC)
    def wait():
        until=time.monotonic()+3
        while time.monotonic()<until:
            if (tmp_path/'counter').exists() or (ram/'claim/result').exists():return
            time.sleep(.01)
    return dict(root=root,ram=ram,old=old,stage=stage,net=net,active=active,tmp=tmp_path,
                run=run,binary=binary,enable=enabled,existing=existing,wait=wait)


def test_network_trigger_concurrent_and_repeated(lab):
    lab['enable']();binary=lab['binary']('hook')
    processes=[subprocess.Popen([str(binary)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,'NET_DELAY':'1'}) for _ in range(20)]
    for p in processes:
        stdout,stderr=p.communicate(timeout=5);assert p.returncode==0,stdout+stderr
    lab['wait']();assert (lab['tmp']/'counter').read_bytes()==b'1'
    assert lab['run']('hook').returncode==0
    assert (lab['tmp']/'counter').read_bytes()==b'1'


def test_worker_resets_inherited_sigchld_without_touching_host(lab):
    import signal
    lab['enable']();binary=lab['binary']('hook')
    def ignored():signal.signal(signal.SIGCHLD,signal.SIG_IGN)
    value=subprocess.run([str(binary)],capture_output=True,timeout=5,preexec_fn=ignored,env={**os.environ,'NET_CHECK_CHLD':'1'})
    assert value.returncode==0;lab['wait']();assert (lab['tmp']/'counter').read_bytes()==b'1'


@pytest.mark.parametrize('fault', ['non_target','argv_mismatch','namespace','disabled','writable_marker','symlink_marker','not_ram','ram_mode','claim_symlink','partial_claim','fork'])
def test_early_refusal_never_launches(lab,fault):
    lab['enable']();root=lab['tmp']
    if fault=='non_target':(root/'exe').unlink();(root/'exe').symlink_to('/usr/bin/dhcpcd')
    if fault=='argv_mismatch':(root/'cmdline').write_bytes(b'/usr/bin/wpa_supplicant-other\0')
    if fault=='namespace':(root/'self-ns').unlink();(root/'self-ns').symlink_to('mnt:[124]')
    if fault=='disabled':(lab['net']/'enabled').unlink()
    if fault=='writable_marker':(lab['net']/'enabled').chmod(0o666)
    if fault=='symlink_marker':(lab['net']/'enabled').rename(lab['net']/'saved');(lab['net']/'enabled').symlink_to('saved')
    if fault=='ram_mode':lab['ram'].chmod(0o777)
    if fault=='claim_symlink':(lab['ram']/'claim').symlink_to(lab['old'])
    if fault=='partial_claim':(lab['ram']/'claim').mkdir()
    env={'NET_NOT_RAM':'1'} if fault=='not_ram' else {'NET_FORK_FAIL':'1'} if fault=='fork' else {}
    assert lab['run']('hook',**env).returncode==0
    assert not (root/'counter').exists()


@pytest.mark.parametrize('fault,expected', [('healthy_ram','EXISTING_RAM_REFUSED'),('stale_pid','EXISTING_RAM_REFUSED'),('empty_ram','EXISTING_RAM_REFUSED'),
    ('listener','PORT_OR_TABLE_REFUSED'),('malformed_tcp','PORT_OR_TABLE_REFUSED'),('helper_hash','HELPER_REFUSED'),('helper_mode','HELPER_REFUSED'),
    ('helper_fifo','HELPER_REFUSED'),('disabled_late','FINAL_GATE_REFUSED'),('exec','EXEC_FAILED')])
def test_restore_and_late_failures_preserve_evidence(lab,fault,expected):
    lab['enable']();root=lab['tmp'];env={}
    if fault in ('healthy_ram','stale_pid','empty_ram'):
        lab['active'].mkdir(mode=0o700)
        if fault!='empty_ram':(lab['active']/'ready').write_bytes(b'healthy' if fault=='healthy_ram' else b'parent=1 child=2 PID_REUSED')
    if fault=='listener':(root/'tcp').write_text('sl local_address rem_address st\n 0: 00000000:08AE 00000000:0000 0A 0 0\n')
    if fault=='malformed_tcp':(root/'tcp').write_text('bad table\n')
    if fault=='helper_hash':(lab['old']/'ssh-service.arm64').write_bytes(b'corrupted')
    if fault=='helper_mode':(lab['old']/'ssh-service.arm64').chmod(0o777)
    if fault=='helper_fifo':(lab['old']/'ssh-service.arm64').unlink();os.mkfifo(lab['old']/'ssh-service.arm64')
    if fault=='disabled_late':env={'NET_DISABLE_LATE':'1'}
    if fault=='exec':env={'NET_EXEC_FAIL':'1'}
    before={p.name:p.read_bytes() for p in lab['active'].glob('*')}
    assert lab['run']('hook',**env).returncode==0;lab['wait']()
    assert (lab['ram']/'claim/result').read_text()==expected+'\n'
    assert not (root/'counter').exists()
    assert {p.name:p.read_bytes() for p in lab['active'].glob('*')}==before
    assert lab['run']('hook',**env).returncode==0
    assert not (root/'counter').exists()


def test_warm_restore_fixture_persistent_config_with_reset_ram(lab):
    # 仅重建夹具RAM，模拟旧进程未执行构造函数、网络程序随后重新加载。
    lab['enable']();lab['existing']()
    assert lab['run']('control','install').returncode==10  # 新目录已有，拒绝重复安装。
    assert lab['run']('hook').returncode==0;lab['wait']()
    assert (lab['ram']/'claim/result').read_text()=='EXISTING_RAM_REFUSED\n'
    # 模拟另一个全新RAM环境；这些删除只发生在临时目录，不是设备恢复策略。
    import shutil
    shutil.rmtree(lab['ram']/'claim');shutil.rmtree(lab['active'])
    assert lab['run']('hook').returncode==0;lab['wait']()
    assert (lab['tmp']/'counter').read_bytes()==b'1'


def test_install_and_both_recovery_actions_keep_service(lab):
    lab['existing']();before={p.name:p.read_bytes() for p in lab['active'].iterdir()}
    value=lab['run']('control','install');assert value.returncode==0,value.stdout+value.stderr
    assert (lab['root']/'ld.so.preload').read_text()==str(lab['net'])+'/network.so\n'
    assert (lab['ram']/'claim/suppressed-active-service').exists()
    assert lab['run']('control','rollback').returncode==0
    assert (lab['root']/'ld.so.preload').read_text()==str(lab['old'])+'/boot.so\n'
    assert lab['run']('control','neutralize').returncode==0
    assert (lab['root']/'ld.so.preload').read_bytes()==b'\n'*512
    assert {p.name:p.read_bytes() for p in lab['active'].iterdir()}==before


@pytest.mark.parametrize('fault,code',[('unknown',10),('tamper',12),('stale_ready',13),('namespace',13),('lock',14),('low_space',14),('claim',18),('rename',21),('sync_before',19),('sync_after',21)])
def test_install_failure_does_not_claim_success(lab,fault,code):
    lab['existing']();before=(lab['root']/'ld.so.preload').read_bytes();env={}
    if fault=='unknown':(lab['root']/'ld.so.preload').write_text('foreign.so\n')
    if fault=='tamper':(lab['stage']/'network.so').write_bytes(b'broken')
    if fault=='stale_ready':(lab['active']/'ready').write_bytes(b'old')
    if fault=='namespace':(lab['tmp']/'self-ns').unlink();(lab['tmp']/'self-ns').symlink_to('mnt:[125]')
    if fault=='lock':(lab['root']/'.a7r5-preload-edit.lock').mkdir()
    if fault=='claim':(lab['ram']/'claim').mkdir()
    if fault=='low_space':env={'NET_LOW_SPACE':'1'}
    if fault=='rename':env={'NET_RENAME_FAIL':'1'}
    if fault=='sync_before':env={'NET_SYNC_FAIL':'1'}
    if fault=='sync_after':env={'NET_COMMIT_SYNC_FAIL':'1'}
    value=lab['run']('control','install',**env);assert value.returncode==code,value.stdout+value.stderr
    if fault not in ('unknown','sync_after'):assert (lab['root']/'ld.so.preload').read_bytes()==before
    if fault=='sync_after':assert (lab['root']/'ld.so.preload').read_text()==str(lab['net'])+'/network.so\n'


@pytest.mark.parametrize('fault',['library','helper','marker','directory'])
def test_static_neutralization_does_not_depend_on_damaged_components(lab,fault):
    lab['existing']();assert lab['run']('control','install').returncode==0
    if fault=='library':(lab['net']/'network.so').write_bytes(b'broken')
    if fault=='helper':(lab['old']/'ssh-service.arm64').write_bytes(b'broken')
    if fault=='marker':(lab['net']/'enabled').write_bytes(b'broken')
    if fault=='directory':lab['net'].rename(lab['root']/'lost')
    assert lab['run']('control','neutralize').returncode==0
    assert (lab['root']/'ld.so.preload').read_bytes()==b'\n'*512


def test_unknown_pointer_and_failed_restore_are_not_overwritten(lab):
    (lab['root']/'ld.so.preload').write_text('unrelated.so\n')
    assert lab['run']('control','neutralize').returncode==30
    assert (lab['root']/'ld.so.preload').read_text()=='unrelated.so\n'


def test_rollback_refuses_corrupt_previous_library_but_can_neutralize(lab):
    lab['existing']();assert lab['run']('control','install').returncode==0
    (lab['old']/'boot.so').write_bytes(b'broken')
    assert lab['run']('control','rollback').returncode==29
    assert (lab['root']/'ld.so.preload').read_text()==str(lab['net'])+'/network.so\n'
    assert lab['run']('control','neutralize').returncode==0


def test_restore_rename_failure_leaves_disabled_marker_and_no_success(lab):
    lab['existing']();assert lab['run']('control','install').returncode==0
    before=(lab['root']/'ld.so.preload').read_bytes()
    value=lab['run']('control','neutralize',NET_RENAME_FAIL='1')
    assert value.returncode==32 and (lab['root']/'ld.so.preload').read_bytes()==before
