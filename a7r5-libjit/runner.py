"""默认只核对本地包；设备执行须新批准、显式开关及独占尝试锁。"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
RISK=('两阶段USB认证/START；只写本会话票据和固定/tmp/jiritsu/libJit.so，各一次，后者写入即执行root载荷。'
      '0x10000006仅证明stat失败，不能排除不可读既有libJit.so或并发创建，接受该固定路径潜在覆盖风险。'
      '不写预加载、不DEBUG、不修改账户、不启动SSH、不操作SD卡；保留现有预加载与服务。'
      '载荷执行15秒固定只读脚本，普通文件上限32KiB，核对自删/票据删除、无活动后代、前后预加载和重复终态；'
      '全部门槛通过后仅一次STOP，随后仅主机元数据核对普通USB与完整媒体，屏幕人工确认。'
      '原厂服务内加载崩溃、USB失步、落盘或自删失败可能需受限恢复，不能保证不中断相机。'
      '库、票据、claim、状态和输出可能持久残留；不自动清理，不重试触发、不自动断电或重启。')

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def regular(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():raise ValueError('不是无链接普通文件')
    return path

def save(path,obj):
    with Path(path).open('x') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())

def check(approved=False):
    manifest=json.loads(regular(HERE/'operation.json').read_text())
    if manifest.get('schema')!='a7r5-libjit-once-1' or manifest['directory']!=str(HERE) or manifest['risk']!=RISK:raise ValueError('包位置、格式或风险说明不符')
    for name,digest in manifest['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or sha(regular(HERE/name))!=digest:raise ValueError('材料变化：'+name)
    for name,digest in manifest['dependencies'].items():
        if sha(regular(name))!=digest:raise ValueError('依赖变化')
    if approved:
        template=dict(accepted=True,operation_sha256=sha(HERE/'operation.json'),risk=RISK)
        if json.loads(regular(HERE/'approval.json').read_text())!=template:raise PermissionError('未取得本包批准')
        if (HERE/'ATTEMPT_LOCK').exists() or (HERE/'result').exists():raise FileExistsError('包已尝试，不允许重跑')
    return manifest

def execute(device_io=False):
    if not device_io:raise PermissionError('没有实机开关，不观察设备')
    # 没有批准时，在加载USB库或读取主机元数据之前拒绝。
    if not (HERE/'approval.json').is_file():raise PermissionError('没有本次明确实机批准')
    manifest=check(True)
    if sys.platform!='darwin' or os.geteuid()!=0:raise PermissionError('需要macOS Terminal本机sudo认证')
    (HERE/'ATTEMPT_LOCK').mkdir(mode=0o700)
    out=HERE/'result';out.mkdir(mode=0o700)
    result=dict(run_id=manifest['run_id'],operation_sha256=sha(HERE/'operation.json'),execution_succeeded=False,screen_confirmation_pending=True,trigger_attempts=0,
                debug_commands_sent=False,preload_written=False,automatic_retry=False,sd_operations=False)
    try:
        import host_state
        from operation import Operation
        baseline=manifest['host_baseline'];initial=host_state.snapshot(out,'initial')
        if initial.get('kind')!='ordinary' or initial['location_id']!=baseline['location_id'] or Counter(map(tuple,initial['media']))!=Counter(map(tuple,baseline['media'])) or set(initial['drivers'])!=set(baseline['drivers']):raise ValueError('普通USB或完整媒体基线不符，不打开USB')
        sys.path[:0]=[str(HERE/'vendor/engine/libs'),str(HERE/'vendor/engine/mac')]
        from system_dump import session
        operation=Operation(HERE);operation.output=out/'session'
        report=session.run_session(out/'session','libusb',_operation=operation)
        save(out/'session-result.json',report)
        for field in ('trigger_attempts','fixed_writes_attempted','service_stop_attempts','protocol_gate_passed','root_task_done','preload_unchanged'):
            result[field]=report.get(field,False)
        recovery=host_state.observe(baseline,lambda label,timeout=5:host_state.snapshot(out,label,timeout))
        save(out/'host-recovery.json',recovery);result['host_recovery_verified']=recovery['recovered']
        result['execution_succeeded']=bool(not report.get('failure') and report.get('protocol_gate_passed') and report.get('trigger_attempts')==1 and report.get('fixed_writes_attempted')==2 and report.get('service_stop_attempts')==1 and recovery['recovered'])
        if not result['execution_succeeded']:raise RuntimeError('实机或恢复门槛未全部通过，停止')
    except (Exception,KeyboardInterrupt) as exc:result['failure']=type(exc).__name__+': '+str(exc)
    finally:
        save(out/'result.json',result)
        owner=HERE.stat()
        for path in [HERE/'ATTEMPT_LOCK',out,*out.rglob('*')]:
            if path.is_symlink():raise ValueError('输出出现链接')
            os.chown(path,owner.st_uid,owner.st_gid,follow_symlinks=False)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('check','approve','execute','confirm-screen'))
    p.add_argument('--accept');p.add_argument('--device-io',action='store_true');args=p.parse_args()
    if args.action=='execute':value=execute(args.device_io)
    elif args.action=='approve':
        manifest=check();phrase='ACCEPT-'+sha(HERE/'operation.json')[:16]
        if args.accept!=phrase:raise PermissionError('必须接受本包精确风险短语')
        if (HERE/'ATTEMPT_LOCK').exists() or (HERE/'result').exists():raise FileExistsError('已尝试')
        save(HERE/'approval.json',dict(accepted=True,operation_sha256=sha(HERE/'operation.json'),risk=RISK));value=dict(approved=True)
    elif args.action=='confirm-screen':
        check(True) if not (HERE/'result').exists() else check()
        result=json.loads(regular(HERE/'result/result.json').read_text())
        manifest=check()
        approved=dict(accepted=True,operation_sha256=sha(HERE/'operation.json'),risk=RISK)
        if json.loads(regular(HERE/'approval.json').read_text())!=approved or result.get('run_id')!=manifest['run_id'] or result.get('operation_sha256')!=approved['operation_sha256'] or not result.get('execution_succeeded') or not result.get('host_recovery_verified'):raise ValueError('不能以屏幕确认覆盖执行、批准或恢复失败')
        # 此子命令本身不访问设备；人工确认与协议结果分开保存。
        save(HERE/'result/screen-confirmation.json',dict(screen_normal=True,run_id=json.loads((HERE/'config.json').read_text())['run_id'],source='user_explicit_confirmation'))
        value=dict(screen_normal=True)
    else:
        manifest=check();value=dict(offline_only=True,approved=(HERE/'approval.json').exists(),run_id=manifest['run_id'],risk=RISK,consent_phrase='ACCEPT-'+sha(HERE/'operation.json')[:16])
    print(json.dumps(value,ensure_ascii=False,indent=2));return 1 if value.get('execution_succeeded') is False else 0

if __name__=='__main__':
    sys.dont_write_bytecode=True
    try:raise SystemExit(main())
    except (Exception,KeyboardInterrupt) as exc:
        print('停止：'+type(exc).__name__+': '+str(exc)+'；不重试、不自动断电。',file=sys.stderr);raise SystemExit(2)
