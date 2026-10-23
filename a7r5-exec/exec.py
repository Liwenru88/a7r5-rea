#!/usr/bin/env python3
"""libJit一条命令准备并执行；prepare/check/status及--prepare-only不访问相机。"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
sys.dont_write_bytecode=True
import core


def run_prepared(directory):
    """仅当前这次调用提权执行；sudo交互留在调用者终端，不自动重试。"""
    print('本次记录：'+str(directory),file=sys.stderr,flush=True)
    process=subprocess.run(['/usr/bin/sudo',str(Path(sys.executable).resolve()),'-B',str(core.HERE/'exec.py'),
                            'execute','--run',str(directory),'--device-io'],stdout=subprocess.PIPE)
    if process.returncode:
        if process.stdout:sys.stderr.write(process.stdout.decode('utf-8',errors='replace'))
        return process.returncode if process.returncode>0 else 2
    result=json.loads(core.regular(directory/'result/result.json').read_text())
    if not result.get('execution_succeeded'):raise RuntimeError('执行结果未通过，请查看本次记录')
    cfg=json.loads(core.regular(directory/'config.json').read_text())
    data=core.regular(directory/'result/session/shell-output.bin').read_bytes()
    begin=cfg['expected_output_begin'].encode();end=cfg['expected_output_end'].encode()
    if not data.startswith(begin) or not data.endswith(end):raise ValueError('输出标记不符')
    sys.stdout.buffer.write(data[len(begin):-len(end)]);sys.stdout.buffer.flush()
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    for action in ['run','prepare']:
        p=sub.add_parser(action,help='libJit准备后直接执行' if action=='run' else '仅本机构建、封存固定命令或脚本')
        if action=='prepare':p.add_argument('--engine',choices=['libjit','kit'],required=True)
        else:p.add_argument('--prepare-only',action='store_true',help='仅本机准备，不执行、不提权、不查询设备')
        group=p.add_mutually_exclusive_group(required=True);group.add_argument('--command');group.add_argument('--script',type=Path)
        p.add_argument('--timeout',type=int,default=15)
    for action in ['check','status','approve','terminal','execute','confirm-screen']:
        p=sub.add_parser(action);p.add_argument('--run',type=Path,required=True)
        if action=='approve':p.add_argument('--accept',required=True)
        if action=='execute':p.add_argument('--device-io',action='store_true')
        if action=='confirm-screen':p.add_argument('--screen-normal',action='store_true')
    sub.add_parser('check-tool',help='仅本机核对工具材料')
    args=parser.parse_args(argv)
    if args.action=='check-tool':core.check_tool();value=dict(tool_verified=True,offline_only=True)
    elif args.action in ['run','prepare']:
        script=core.regular(args.script).read_bytes().decode('utf-8',errors='strict') if args.script else args.command
        engine='libjit' if args.action=='run' else args.engine
        directory=core.prepare(engine,script,args.timeout);op=core.load(directory)
        if args.action=='run' and not args.prepare_only:return run_prepared(directory)
        value=dict(directory=str(directory),run_id=op['run_id'],engine=op['engine'],risk=op['risk'],offline_only=True,
                   terminal=str(directory/'run-once.command'))
        if engine=='kit':value['consent_phrase']='ACCEPT-'+core.sha(directory/'operation.json')[:16]
    elif args.action=='approve':
        core.approve(args.run,args.accept);value=dict(approved=True,camera_requests=0)
    elif args.action=='terminal':
        directory=core.safe(args.run);op=core.load(directory)
        if op['engine']=='kit':core.approved(directory)
        # 只打开这一个经过封存的Terminal脚本，不自动提供密码。
        subprocess.run(['/usr/bin/open','-a','Terminal',str(directory/'run-once.command')],check=True,timeout=10)
        value=dict(terminal_requested=True)
    elif args.action=='execute':
        from controller import execute
        value=execute(args.run,args.device_io)
    elif args.action=='confirm-screen':
        from controller import confirm_screen
        value=confirm_screen(args.run,args.screen_normal)
    else:
        directory=core.safe(args.run);op=core.load(directory)
        value=dict(run_id=op['run_id'],engine=op['engine'],risk=op['risk'],offline_only=True,
                   attempted=(directory/'result').exists() or (directory/'ATTEMPT_LOCK').exists(),
                   pending_recovery=op['engine']=='kit' and (core.HERE/'PENDING_RECOVERY.json').exists())
        if op['engine']=='kit':value['consent_phrase']='ACCEPT-'+core.sha(directory/'operation.json')[:16]
        if args.action=='status' and (directory/'result/result.json').exists():
            value['result']=json.loads(core.regular(directory/'result/result.json').read_text())
    print(json.dumps(value,ensure_ascii=False,indent=2))
    return 3 if value.get('execution_succeeded') is False else 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (Exception,KeyboardInterrupt) as exc:
        print('停止：'+type(exc).__name__+': '+str(exc)+'；本次不自动重试，记录予以保留。',file=sys.stderr)
        raise SystemExit(2)
