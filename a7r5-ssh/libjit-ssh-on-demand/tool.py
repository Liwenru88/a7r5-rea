"""默认仅本机；设备路径必须显式批准、单次锁及共享恢复门槛全部通过。"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ACTIONS = ('load-once','start-once','stop-once','collect-once')


def regular(path):
    import stat
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)) or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('只接受无链接的普通本机文件')
    return path


def sha(path):
    with regular(path).open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()


def save(path,value):
    with Path(path).open('x',encoding='utf-8') as handle:
        os.fchmod(handle.fileno(),0o600)
        json.dump(value,handle,ensure_ascii=False,indent=2)
        handle.write('\n')


def check(package):
    package=Path(package).absolute()
    if any(p.is_symlink() for p in (package,*package.parents)) or package.stat().st_mode&0o077:
        raise ValueError('包目录须为无链接0700目录')
    manifest=json.loads(regular(package/'manifest.json').read_text())
    if manifest.get('schema')!='a7r5-libjit-ssh-package-1' or manifest['directory']!=str(package):
        raise ValueError('材料目录绑定不符；移动后须重新封包')
    for name,want in manifest['files'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or sha(package/p)!=want:
            raise ValueError('材料改变：'+name)
    for name,want in manifest['dependencies'].items():
        if sha(name)!=want:
            raise ValueError('依赖改变：'+name)
    if str(Path(sys.executable).resolve())!=manifest['python_real']:
        raise ValueError('解释器变化')
    return manifest


def phrase(package,action):
    if action not in ACTIONS:
        raise ValueError('阶段不符')
    return 'ACCEPT-'+action+'-'+sha(Path(package)/'manifest.json')[:16]


@contextmanager
def exclusive(project):
    with (project/'a7r5-exec/ACTIVE_SESSION.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def guard(package,action,accept,device_io):
    manifest=check(package)
    if not device_io or accept!=phrase(package,action):
        raise PermissionError('没有本阶段显式设备批准，不枚举设备')
    if manifest.get('qemu_only') is not False:
        raise PermissionError('QEMU材料禁止用于设备')
    if sys.platform!='darwin' or os.geteuid()!=0:
        raise PermissionError('仅允许macOS本机sudo执行USB阶段')
    project=Path(manifest['project'])
    coordinator=Path(manifest['coordinator'])
    if (coordinator/'PENDING_RECOVERY.json').exists() or (project/'a7r5-exec/PENDING_RECOVERY.json').exists():
        raise PermissionError('存在待恢复或待屏幕确认会话，禁止新尝试')
    state=package/'.state'
    for path in (state,coordinator,project):
        if any(p.is_symlink() for p in (path,*path.parents)):
            raise ValueError('状态或协调路径存在链接')
    active=coordinator/'ACTIVE_SERVICE.json'
    if action in ('load-once','start-once') and active.exists():
        raise PermissionError('已有活动或未收口服务，不重复启动')
    predecessor={'start-once':'load-once','stop-once':'start-once','collect-once':'start-once'}.get(action)
    if predecessor:
        previous=json.loads(regular(state/predecessor/'result.json').read_text())
        screen=json.loads(regular(state/predecessor/'screen.json').read_text())
        if previous.get('passed') is not True or screen.get('screen_normal') is not True or screen.get('result_sha256')!=sha(state/predecessor/'result.json'):
            raise PermissionError('前阶段、恢复及屏幕门槛未通过')
    if action in ('stop-once','collect-once'):
        if json.loads(regular(active).read_text()).get('run_id')!=manifest['run_id']:
            raise PermissionError('活动实例不匹配')
    state.mkdir(mode=0o700,exist_ok=True)
    attempt=state/action
    attempt.mkdir(mode=0o700)  # 永久单次锁；异常也不删除。
    binding=dict(run_id=manifest['run_id'],package=str(package),action=action,manifest_sha256=sha(package/'manifest.json'))
    save(coordinator/'PENDING_RECOVERY.json',binding)
    return manifest,attempt,binding


def camera_session(package,action,output):
    sys.path[:0]=[str(package/'runtime'),str(package/'runtime/vendor/engine/libs'),str(package/'runtime/vendor/engine/mac')]
    from operation import Operation
    from system_dump import session
    operation=Operation(package,action)
    operation.output=output
    return session.run_session(output,'libusb',_operation=operation)


def snapshot_runtime(package):
    sys.path.insert(0,str(package/'runtime'))
    import host_state
    return host_state


def execute(package,action,accept=None,device_io=False):
    package=Path(package).absolute()
    m=check(package)
    # 未明确批准不得连共享锁都绕过后直接访问设备。
    if not device_io or accept!=phrase(package,action):
        raise PermissionError('没有本阶段设备批准')
    with exclusive(Path(m['project'])):
        m,out,binding=guard(package,action,accept,device_io)
        result=dict(**binding,passed=False,automatic_retry=False,preload_written=False,
                    debug_commands_sent=False,autostart=False,host_recovery_verified=False)
        try:
            host=snapshot_runtime(package)
            baseline=json.loads((package/'config.json').read_text())['host_baseline']
            initial=host.snapshot(out,'initial')
            if initial.get('kind')!='ordinary' or any(initial.get(k)!=baseline[k] for k in ['location_id','media','drivers']):
                raise ValueError('普通USB、同端口及完整媒体基线不符，不打开USB')
            report=camera_session(package,action,out/'session')
            save(out/'session-result.json',report)
            result.update({k:report.get(k) for k in ['protocol_gate_passed','fixed_writes_attempted','trigger_attempts',
                          'service_stop_attempts','service_stop_result','service_stop_error','preload_unchanged',
                          'service_ready','service_ended','originals_unchanged','changes_observed'] if k in report})
            recovery=host.observe(baseline,lambda label,timeout=5:host.snapshot(out,label,timeout))
            save(out/'host-recovery.json',recovery)
            result['host_recovery_verified']=recovery['recovered']
            counts={'load-once':3,'start-once':2,'stop-once':1,'collect-once':0}
            result['passed']=bool(not report.get('failure') and report.get('protocol_gate_passed') is True
                                  and report.get('preload_unchanged') is True
                                  and report.get('fixed_writes_attempted')==counts[action]
                                  and report.get('trigger_attempts')==(1 if action=='start-once' else 0)
                                  and report.get('service_stop_attempts')==1 and recovery['recovered'])
            if not result['passed']:
                raise RuntimeError(report.get('failure','协议、次数或主机恢复未全部通过'))
            coordinator=Path(m['coordinator'])
            if action=='start-once':
                save(coordinator/'ACTIVE_SERVICE.json',binding)
                public=(out/'host-public-key').read_bytes()
                (out/'known_hosts').write_bytes(b'a7r5-libjit-'+m['run_id'].encode()+b' '+b' '.join(public.split()[:2])+b'\n')
            result['screen_confirmation_pending']=True
        except (Exception,KeyboardInterrupt) as exc:
            result['failure']=type(exc).__name__+': '+str(exc)
        finally:
            save(out/'result.json',result)
            owner=package.stat()
            for item in [package/'.state',out,*out.rglob('*'),Path(m['coordinator'])/'PENDING_RECOVERY.json',Path(m['coordinator'])/'ACTIVE_SERVICE.json']:
                if item.exists():
                    if item.is_symlink():
                        raise ValueError('输出出现链接')
                    os.chown(item,owner.st_uid,owner.st_gid,follow_symlinks=False)
        return result


def confirm_screen(package,action,screen_normal=False):
    m=check(package)
    if not screen_normal:
        raise PermissionError('须人工确认屏幕正常')
    with exclusive(Path(m['project'])):
        out=package/'.state'/action
        result=json.loads(regular(out/'result.json').read_text())
        pending=Path(m['coordinator'])/'PENDING_RECOVERY.json'
        binding={k:result[k] for k in ['run_id','package','action','manifest_sha256']}
        if result.get('passed') is not True or not result.get('host_recovery_verified') or json.loads(regular(pending).read_text())!=binding:
            raise ValueError('不能以屏幕确认覆盖失败或其它会话')
        active=None
        if action in ('stop-once','collect-once'):
            active=Path(m['coordinator'])/'ACTIVE_SERVICE.json'
            if json.loads(regular(active).read_text()).get('run_id')!=m['run_id']:
                raise ValueError('活动记录变化')
        save(out/'screen.json',dict(screen_normal=True,result_sha256=sha(out/'result.json')))
        if active is not None:
            active.unlink()  # 只解除本机门槛，不删除永久尝试锁及相机文件。
        pending.unlink()
        return dict(screen_normal=True,device_requests=0)


def main():
    p=argparse.ArgumentParser(description='libJit按需SSH：默认离线，实机逐阶段显式批准')
    p.add_argument('action',choices=['check','status','confirm-screen',*ACTIONS])
    p.add_argument('--package',type=Path,default=HERE)
    p.add_argument('--accept')
    p.add_argument('--device-io',action='store_true')
    p.add_argument('--phase',choices=ACTIONS)
    p.add_argument('--screen-normal',action='store_true')
    args=p.parse_args()
    m=check(args.package)
    if args.action in ('check','status'):
        value=dict(run_id=m['run_id'],offline_only=True,ttl_seconds=m['ttl_seconds'],
                   phases={a:phrase(args.package,a) for a in ACTIONS},
                   pending_recovery=(Path(m['coordinator'])/'PENDING_RECOVERY.json').exists(),
                   active_record=(Path(m['coordinator'])/'ACTIVE_SERVICE.json').exists())
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    if args.action=='confirm-screen':
        if args.phase is None:
            raise ValueError('须指定确认阶段')
        result=confirm_screen(args.package,args.phase,args.screen_normal)
    else:
        result=execute(args.package,args.action,args.accept,args.device_io)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result.get('passed',True) else 3


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr)
        raise SystemExit(2)
