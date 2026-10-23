#!/usr/bin/env python3
"""不启动SSH的隔离/跨STOP补证材料；实机操作有独立批准和一次性锁。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import uuid

import lab

PASSWD_SHA='4a691edcd492167bb3d538e4e15c24dd5fbc45785afcf2beddb3fbd39e097398'
RISK=('隔离与联网补证，不启动SSH、不修改账户字段；固定载荷/启动器和预加载写入，认证/START、一次DEBUG；'
      '仅精确512换行基线，私有挂载及原字节账户副本，75秒RAM元数据观察；符合门槛才一次STOP。'
      '结果仅RAM保留，独立批准读回会话不含DEBUG或文件写入；不自动二次认证、重试、断电或清理历史文件。')
TARGET=dict(model='ILCE-7RM5',firmware='4.00',normal_pid=0x0e0a,service_pid=0x0336,location_id=0x01100000)


def paths(run):
    if not re.fullmatch('[0-9a-f]{32}',run): raise ValueError('无效会话')
    prefix='/tmp/jiritsu/a7r5-'+run
    ram='/tmp_network/a7r5-ns-'+run
    return dict(prefix=prefix,helper=prefix+'.probe',payload=prefix+'.so',state=prefix+'.state',
                output=prefix+'.output',ram=ram,ready=ram+'/ready',heartbeat=ram+'/heartbeat',
                result=ram+'/result',trace=ram+'/trace')


def config_header(run,*,test=None):
    p=paths(run)
    values=dict(RUN_ID=run,RAM_PARENT='/tmp_network',RUN_DIR=p['ram'],READY_PATH=p['ready'],
                HEARTBEAT_PATH=p['heartbeat'],RESULT_PATH=p['result'],TRACE_PATH=p['trace'],
                PASSWD_PATH='/etc/passwd',VAR_PATH='/var',PRIVATE_PASSWD='/var/passwd.view',
                MARKER_PATH='/var/a7r5-ns-proof-'+run,PRIVATE_MARKER='/var/a7r5-ns-proof-'+run,
                NET_DEV_PATH='/proc/net/dev',NET_ROUTE_PATH='/proc/net/route')
    seconds=75;sample_ms=5000
    if test:
        root=Path(test['root'])
        values.update({name:str(root/name.lower()) for name in (
            'RAM_PARENT','RUN_DIR','READY_PATH','HEARTBEAT_PATH','RESULT_PATH','TRACE_PATH',
            'PASSWD_PATH','VAR_PATH','PRIVATE_PASSWD','MARKER_PATH','PRIVATE_MARKER',
            'NET_DEV_PATH','NET_ROUTE_PATH','NET_IP_PATH','TEST_MOUNTS')})
        values['RUN_DIR']=str(Path(values['RAM_PARENT'])/'run_dir')
        # 运行文件必须都位于唯一RAM目录内；其余是互相隔离的本机夹具。
        values.update({k:str(Path(values['RUN_DIR'])/k.lower()) for k in ('READY_PATH','HEARTBEAT_PATH','RESULT_PATH','TRACE_PATH')})
        seconds=2;sample_ms=100
    header=''.join('#define '+name+' '+json.dumps(value)+'\n' for name,value in values.items())
    return header+f'#define PROBE_SECONDS {seconds}\n#define SAMPLE_MS {sample_ms}\n'+(
        '#define TEST_FAILURE '+str(test.get('failure',0))+'\n' if test else '')


def compile_target(source,output,include,*,shared=False):
    libc=lab.ROOT/'vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    command=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu',
             '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-nostdlib','-ffreestanding','-fno-builtin',
             '-fno-stack-protector','-O2','-Wall','-Wextra','-Werror','-I',str(include),
             '-Wl,--no-undefined','-Wl,-z,max-page-size=65536']
    if shared: command+=['-fPIC','-fvisibility=hidden','-shared']
    else: command+=['-fPIE','-pie','-Wl,-e,_start','-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1',str(lab.ROOT/'src/start.S')]
    command += [str(source),str(libc),'-o',str(output)]
    completed=subprocess.run(command,capture_output=True,text=True,timeout=90)
    if completed.returncode:
        lab.save(output.with_suffix(output.suffix+'.failure.json'),dict(command=command,exit_code=completed.returncode,stderr=completed.stderr))
        raise RuntimeError(completed.stderr)
    lab.engine()
    from system_dump.environment import static_payload_check
    result=static_payload_check(output,lab.digest(output))
    result['command']=command
    if not shared:
        from elftools.elf.elffile import ELFFile
        with output.open('rb') as f:
            symbols={s.name for s in ELFFile(f).get_section_by_name('.dynsym').iter_symbols() if s['st_shndx']=='SHN_UNDEF'}
        forbidden={'execve','system','popen','bind','listen','connect','send','sendto','setuid','setgid'}
        if symbols&forbidden: raise ValueError('补证程序出现未批准行为符号')
        result['forbidden_behavior_symbols_absent']=True
    return result


def prepare(directory):
    directory=Path(directory).absolute()
    if directory.is_relative_to('/dev') or any(p.is_symlink() for p in (directory,*directory.parents)):
        raise ValueError('拒绝设备或链接输出')
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    run=uuid.uuid4().hex;p=paths(run)
    (directory/'ns_config.h').write_text(config_header(run))
    helper=directory/'ns-probe.arm64';helper_check=compile_target(lab.ROOT/'src/ns_probe.c',helper,directory)
    helper_sha=lab.digest(helper)
    script=("set -eu\nsum=$(/usr/bin/openssl dgst -sha256 "+p['helper']+"); "
            "[ \"${sum##* }\" = '"+helper_sha+"' ]\n/bin/busybox chmod 700 "+p['helper']+
            '\nexec '+p['helper']+' --launch\n')
    subprocess.run(['/bin/sh','-n'],input=script,text=True,check=True,capture_output=True)
    (directory/'task.sh').write_text(script)
    (directory/'root_config.h').write_text(lab.root_header(run,script,45))
    payload=directory/'isolation.arm64.so'
    payload_check=compile_target(lab.ROOT/'src/root_once.c',payload,directory,shared=True)
    lab.save(directory/'build.json',dict(helper=helper_check,payload=payload_check))
    (directory/'preload-arm.bin').write_bytes((p['payload']+'\n').encode())
    (directory/'preload-neutral.bin').write_bytes(b'\n'*512)
    for phase in ('probe','collect'):
        command=('#!/bin/bash\n# 无本次批准即退出；本文件不会生成批准或自动开启下一会话。\nset -euo pipefail\n'
                 'material='+shlex.quote(str(lab.ROOT))+'\noperation='+shlex.quote(str(directory))+'\n'
                 'python_bin='+shlex.quote(str(Path(sys.executable).absolute()))+'\n'
                 '"$python_bin" -B "$material/isolation.py" check-approval --operation "$operation" --phase '+phase+'\n'
                 'sudo -- "$python_bin" -B "$material/isolation.py" execute --operation "$operation" --phase '+phase+' --device-io\n')
        target=directory/('run-'+phase+'.command');target.write_text(command);target.chmod(0o700)
    artifacts={p.name:lab.digest(p) for p in directory.iterdir() if p.is_file()}
    operation=dict(schema='a7r5-isolation-1',kind='namespace-network-probe',run_id=run,
                   material_root=str(lab.ROOT),operation_directory=str(directory),risk=RISK,target=TARGET,
                   sources=lab.sources(),artifacts=artifacts,expected_passwd_sha256=PASSWD_SHA,
                   ssh_deployment_enabled=False,account_fields_changed=False,observer_seconds=75,
                   post_ready_persistent_writes=False,collect_is_separately_approved=True,
                   runtime={str(Path(sys.executable).resolve()):lab.digest(Path(sys.executable).resolve()),
                     '/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib':hashlib.sha256(Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').read_bytes()).hexdigest()})
    lab.save(directory/'operation.json',operation)
    for phase in ('probe','collect'):
        lab.save(directory/('approval-'+phase+'-template.json'),approval(operation,phase,False))
    return operation


def approval(operation,phase,accepted=True):
    if phase not in ('probe','collect'): raise ValueError('阶段不符')
    prior=Path(operation['operation_directory'])/'result-probe/phase-result.json'
    return dict(schema='a7r5-isolation-approval-1',run_id=operation['run_id'],phase=phase,
                operation_sha256=lab.digest(Path(operation['operation_directory'])/'operation.json'),
                accepted=accepted,risk=RISK,authentication_start=True,debug_once=phase=='probe',
                camera_fixed_file_writes=phase=='probe',private_mounts=phase=='probe',
                post_ready_persistent_writes=False,account_modification=False,start_ssh=False,
                conditional_stop_once=True,automatic_second_session=False,
                probe_screen_normal_confirmed=phase=='collect' and accepted,
                probe_receipt_sha256=lab.digest(prior) if phase=='collect' and accepted else None)


def check(directory):
    directory=lab.regular(Path(directory).absolute()/'operation.json').parent
    if lab.ROOT.stat().st_mode&0o077: raise PermissionError('材料根目录须为700')
    value=json.loads((directory/'operation.json').read_text())
    required=dict(schema='a7r5-isolation-1',kind='namespace-network-probe',material_root=str(lab.ROOT),
                  operation_directory=str(directory),risk=RISK,target=TARGET,expected_passwd_sha256=PASSWD_SHA,
                  ssh_deployment_enabled=False,account_fields_changed=False,observer_seconds=75,
                  post_ready_persistent_writes=False,collect_is_separately_approved=True)
    if any(value.get(k)!=v for k,v in required.items()): raise ValueError('操作范围或路径变化')
    paths(value['run_id'])
    if value['sources']!=lab.sources(): raise ValueError('源码变化，旧补证包失效')
    expected={'ns_config.h','ns-probe.arm64','task.sh','root_config.h','isolation.arm64.so','build.json',
              'preload-arm.bin','preload-neutral.bin','run-probe.command','run-collect.command'}
    if set(value['artifacts'])!=expected: raise ValueError('固定材料集合变化')
    if set(value['runtime'])!={str(Path(sys.executable).resolve()),'/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib'}:
        raise ValueError('运行依赖集合不符')
    for name,digest in value['artifacts'].items():
        if lab.digest(directory/name)!=digest: raise ValueError('材料摘要不符：'+name)
    for name,digest in value['runtime'].items():
        if lab.digest(Path(name).resolve())!=digest: raise ValueError('运行依赖变化')
    return value


def checked_approval(directory,phase):
    if phase not in ('probe','collect'):raise ValueError('阶段不符')
    directory=Path(directory).absolute()
    accepted=json.loads(lab.regular(directory/('approval-'+phase+'.json')).read_text())
    value=check(directory)
    if accepted!=approval(value,phase): raise PermissionError('缺少绑定本阶段的明确批准')
    if (directory/('ATTEMPT_LOCK_'+phase.upper())).exists() or (directory/('result-'+phase)).exists():
        raise FileExistsError('本阶段已有尝试或结果，不重试')
    if phase=='collect':
        prior=json.loads(lab.regular(directory/'result-probe/phase-result.json').read_text())
        if (prior.get('run_id')!=value['run_id'] or not prior.get('execution_succeeded')
                or prior.get('probe_outcome')!='READY_FOR_STOP' or not prior.get('host_recovery_verified')):
            raise PermissionError('前一会话未安全完成，禁止自动取回')
        deadline=prior['collect_not_before_unix']
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline<0:
            raise ValueError('读回等待门槛异常')
        if time.time()<deadline:
            raise PermissionError('尚未超过观察器及清理的截止时间')
    return value


def fields(raw,run,kind):
    text=raw.decode('ascii','strict')
    lines=text.splitlines()
    if len(raw)>4096 or not text.endswith('\n') or not lines or lines[0]!='A7R5_NS_RESULT '+run or lines[-1]!='END '+run:
        raise ValueError('结果不完整或会话不符')
    data={}
    for line in lines[1:-1]:
        key,sep,value=line.partition('=')
        if not sep or key in data: raise ValueError('重复或非法结果字段')
        data[key]=value
    expected={'code','errno','uid','euid','pid','ticks','child','isolation_verified','parent_unchanged',
              'passwd_unchanged','child_reaped','network_hint','samples','trace_bytes','trace_sha256','ssh_started','account_modified'}
    if set(data)!=expected: raise ValueError('结果字段集合不符')
    if not re.fullmatch('[0-9a-f]{64}',data['trace_sha256']): raise ValueError('结果摘要格式不符')
    result={k:(v if k=='trace_sha256' else int(v)) for k,v in data.items()}
    if any(v<0 for k,v in result.items() if k!='trace_sha256'): raise ValueError('负结果字段')
    if any(result[k]!=v for k,v in dict(uid=0,euid=0,parent_unchanged=1,passwd_unchanged=1,child_reaped=1,ssh_started=0,account_modified=0).items()):
        raise ValueError('root、外部原件或清理门槛未通过')
    if not 0<=result['trace_bytes']<=32768 or result['pid']<=1 or result['child']<=1 or result['ticks']<=0:
        raise ValueError('结果长度或进程身份异常')
    if result['pid']==result['child'] or result['isolation_verified'] not in (0,1) or result['network_hint'] not in (0,1) or result['samples']>32:
        raise ValueError('进程或布尔/计数字段异常')
    if kind=='complete' and (result['code']!=0 or result['isolation_verified']!=1 or result['samples']<2):
        raise ValueError('隔离或有界观察没有完成')
    if kind=='negative' and result['code']==0: raise ValueError('缺少明确的负结果原因')
    if kind=='terminal' and result['code']==0 and (result['isolation_verified']!=1 or result['samples']<2):
        raise ValueError('成功终态缺少隔离或观察样本')
    return result


def ready(raw,run):
    pattern=(r'A7R5_NS_READY '+run+r' pid=([0-9]+) ticks=([0-9]+) child=([0-9]+) uid=0 euid=0 ttl=75 '
             r'isolation=1 parent_unchanged=1 account_modified=0 ssh_started=0 passwd_sha=('+PASSWD_SHA+r') '
             r'parent_ns=(mnt:\[[0-9]+\]) child_ns=(mnt:\[[0-9]+\]) net_ns=(net:(?:\[[0-9]+\]|unavailable))\n')
    m=re.fullmatch(pattern,raw.decode('ascii','strict'))
    if not m or m[5]==m[6] or int(m[1])<=1 or int(m[2])<=0 or int(m[3])<=1 or m[1]==m[3]:
        raise ValueError('READY身份、隔离或账户摘要不符')
    return dict(pid=int(m[1]),ticks=int(m[2]),child=int(m[3]))


def heartbeat(raw,run,identity):
    m=re.fullmatch(r'A7R5_NS_ALIVE '+run+r' pid=([0-9]+) ticks=([0-9]+) child=([0-9]+) seq=([0-9]+) elapsed_ms=([0-9]+) ttl=75 parent_unchanged=1\n',raw.decode('ascii','strict'))
    if not m or dict(pid=int(m[1]),ticks=int(m[2]),child=int(m[3]))!=identity or not 0<int(m[4])<=100:
        raise ValueError('心跳已结束、进程变化或格式不符')
    if not 0<=int(m[5])<=45000: raise ValueError('观察剩余时间不足30秒，拒绝STOP')
    return int(m[4]),int(m[5])


class ProbeOperation:
    def __init__(self,directory,value,phase):
        self.directory=Path(directory);self.value=value;self.phase=phase;self.safe_to_stop=False

    def __call__(self,driver,output,log,report):
        lab.engine()
        from system_dump.restricted import Deployment,RestrictedChannel,neutral,MAX_ARTIFACT
        from system_dump.session import FileResultError
        p=paths(self.value['run_id']);run=self.value['run_id']
        ports=tuple(driver.device.port_numbers or ())
        if (not 1<=len(ports)<=5 or any(not 1<=port<=15 for port in ports)
                or (driver.device.bus<<24)|sum(port<<(20-4*i) for i,port in enumerate(ports))!=TARGET['location_id']):
            raise ValueError('物理端口变化')
        reads={'/version.txt':4096,'/etc/ld.so.preload':4096,p['state']:512,p['output']:32768,
               p['ready']:1024,p['heartbeat']:512,p['result']:4096,p['trace']:32768}
        writes={}
        if self.phase=='probe':
            payload=(self.directory/'isolation.arm64.so').read_bytes();helper=(self.directory/'ns-probe.arm64').read_bytes()
            reads.update({p['payload']:MAX_ARTIFACT,p['helper']:MAX_ARTIFACT})
            writes={p['payload']:(payload,),p['helper']:(helper,),'/etc/ld.so.preload':((p['payload']+'\n').encode(),neutral)}
        class Exact(RestrictedChannel):
            arm_attempted=False
            def put(self,path,raw):
                if path=='/etc/ld.so.preload':self.arm_attempted=True
                return super().put(path,raw)
            def read(self,path,limit):
                raw=super().read(path,limit)
                if path=='/etc/ld.so.preload' and not self.arm_attempted and raw!=neutral:
                    raise PermissionError('基线读取不是精确512换行')
                return raw
        ch=Exact(driver,writes,reads,log);deploy=None;stop_deadline=None
        try:
            if hashlib.sha256(ch.read('/version.txt',4096)).hexdigest()!=lab.VERSION_SHA: raise ValueError('版本对照不符')
            if ch.read('/etc/ld.so.preload',4096)!=neutral: raise PermissionError('非精确512换行基线')
            if self.phase=='probe':
                report['camera_file_write_commands_sent']=True
                ch.put(p['helper'],helper)
                if ch.read(p['helper'],MAX_ARTIFACT)!=helper: raise ValueError('启动器完整回读不符')
                deploy=Deployment(ch,run,payload,output,False);deploy.arm();deploy.trigger()
                deadline=time.monotonic()+65
                while True:
                    if time.monotonic()>=deadline: raise TimeoutError('未取得固定入口终态')
                    try: state=ch.read(p['state'],512)
                    except FileResultError as exc:
                        if exc.result!=0x10000006: raise
                        time.sleep(.2);continue
                    (output/'worker-last-state.txt').write_bytes(state)
                    m=re.fullmatch(rb'A7R5-ROOT-1 '+run.encode()+rb' (RUNNING|DONE|FAILED|TIMEOUT) ([0-9]+) uid=0 euid=0 bytes=([0-9]+)\n',state)
                    if not m or m[1] in (b'FAILED',b'TIMEOUT'): raise ValueError('入口失败、旧状态或非root')
                    if m[1]==b'DONE': break
                    time.sleep(.2)
                if int(m[3])>=32768: raise ValueError('入口输出超限')
                data=ch.read(p['output'],32768)
                (output/'worker-output.txt').write_bytes(data)
                if len(data)!=int(m[3]): raise ValueError('入口输出长度不符')
                if m[2]!=b'0':raise ValueError('入口非零退出：'+m[2].decode()+'；固定输出已保存，不继续操作')
                if data==(f'A7R5_NS_LAUNCH {run} outcome=NEGATIVE_CLEAN\n').encode():
                    self.read_result(ch,p,output,report,'negative');report['probe_outcome']='NEGATIVE_CLEAN'
                elif data==(f'A7R5_NS_LAUNCH {run} outcome=READY\n').encode():
                    raw=ch.read(p['ready'],1024);(output/'ready-raw.txt').write_bytes(raw);identity=ready(raw,run)
                    previous=heartbeat(ch.read(p['heartbeat'],512),run,identity)
                    until=time.monotonic()+7
                    while True:
                        if time.monotonic()>=until: raise TimeoutError('心跳没有前进')
                        time.sleep(.25)
                        current_raw=ch.read(p['heartbeat'],512);current=heartbeat(current_raw,run,identity)
                        if current[0]>previous[0] and current[1]>previous[1]:break
                        if current!=previous:raise ValueError('心跳倒退或部分更新')
                    if ch.read(p['ready'],1024)!=raw:raise ValueError('READY变化')
                    (output/'ready.txt').write_bytes(raw);report['observer_identity']=identity
                    (output/'heartbeat-before-stop.txt').write_bytes(current_raw)
                    report['observer_time_reference']=dict(guest_elapsed_ms=current[1],
                        host_read_completed_utc=datetime.now(timezone.utc).isoformat(),
                        sampling_interval_ms=5000,exact_stop_alignment_verified=False)
                    report['probe_outcome']='READY_FOR_STOP'
                    report['guest_final_result_pending']=True
                    stop_deadline=time.monotonic()+75-current[1]/1000-10
                else:raise ValueError('启动器输出不符')
                if ch.read('/etc/ld.so.preload',4096)!=neutral or ch.read(p['state'],512)!=state:
                    raise ValueError('中和或重复终态不符')
            else:
                prior=json.loads((self.directory/'result-probe/phase-result.json').read_text())
                self.read_result(ch,p,output,report,'terminal')
                if {k:report['guest_result'][k] for k in ('pid','ticks','child')}!=prior['observer_identity']:
                    raise ValueError('最终结果与观察器身份不同')
                report['probe_outcome']='COLLECTED'
                if ch.read('/etc/ld.so.preload',4096)!=neutral:raise ValueError('中和变化')
            if stop_deadline is not None and time.monotonic()>=stop_deadline:
                raise TimeoutError('终态复核耗尽观察器剩余时间，拒绝STOP')
            report.update(protocol_gate_passed=True,preload_neutral_verified=True,ssh_started=False,account_modified=False)
            report.update(communication_verified=True,firmware_version_source='version_sha256_matched')
            self.safe_to_stop=True
        finally:
            if deploy:
                if not deploy.state['debug_attempted'] and not deploy.safe_to_stop and ch.usable:
                    try:deploy.disarm_before_debug()
                    except Exception as exc:log('ns_pre_debug_disarm_failed',message=str(exc))
                report.update(deployment_state=deploy.state,preload_written=bool(deploy.state.get('arm_write_attempted')),
                              debug_commands_sent=bool(deploy.state['debug_attempted']))
            report.update(automatic_service_exit_permitted=self.safe_to_stop,action_flags_semantics='attempted_not_confirmed')

    def read_result(self,ch,p,output,report,kind):
        raw=ch.read(p['result'],4096);(output/'guest-result-raw.bin').write_bytes(raw)
        result=fields(raw,self.value['run_id'],kind)
        trace=ch.read(p['trace'],32768)
        (output/'network-trace-raw.bin').write_bytes(trace)
        if len(trace)!=result['trace_bytes'] or hashlib.sha256(trace).hexdigest()!=result['trace_sha256']:
            raise ValueError('RAM轨迹长度或摘要不符')
        if ch.read(p['result'],4096)!=raw:raise ValueError('最终结果变化')
        (output/'guest-result.txt').write_bytes(raw);(output/'network-trace.bin').write_bytes(trace)
        report['guest_result']=result
        import ipaddress
        addresses=[]
        for interface,address in re.findall(rb'^IPV4 ([A-Za-z0-9_.:-]{1,16}) ([0-9.]+)\n',trace,re.M):
            ip=ipaddress.IPv4Address(address.decode())
            if not ip.is_loopback and not ip.is_unspecified and not ip.is_multicast:
                addresses.append(dict(interface=interface.decode(),address=str(ip)))
        report['nonloopback_ipv4_observed']=addresses
        report['lan_reachability_verified']=False


def execute(directory,phase,device_io=False):
    if not device_io: raise PermissionError('本轮仅离线；缺少实机开关')
    directory=Path(directory).absolute();value=checked_approval(directory,phase)
    if sys.platform!='darwin' or os.geteuid()!=0:raise PermissionError('须在已确认的macOS Terminal完成本机认证')
    (directory/('ATTEMPT_LOCK_'+phase.upper())).mkdir(mode=0o700)
    # 只有两个显式门槛、摘要及一次性锁之后，才加载主机观察/设备后端。
    import device
    lab.engine()
    from system_dump.session import run_session
    before=device.host_snapshot();output=directory/('result-'+phase)
    report=run_session(output,'libusb',_operation=ProbeOperation(directory,value,phase))
    recovery=(device.observe_recovery(before,device.host_snapshot) if
              report.get('automatic_service_exit_permitted') and report.get('service_stop_attempts')==1 else
              dict(recovered=False,reason='gate_withheld',observations=[]))
    device.save_result(output,'host-recovery.json',recovery)
    report.update(run_id=value['run_id'],phase=phase,host_recovery_verified=recovery['recovered'],
                  execution_succeeded=bool(report.get('protocol_gate_passed') and recovery['recovered'] and not report.get('failure')),
                  screen_confirmation_pending=True,acceptance_complete=False,research_residue_cleaned=False,
                  collect_not_before_unix=time.time()+90,ssh_deployment_allowed=False)
    report['stop_events']=[json.loads(line) for line in (output/'events.jsonl').read_text().splitlines()
                           if json.loads(line).get('event') in ('stop_senser_attempted','stop_senser_control_returned','stop_senser_exception')]
    device.save_result(output,'phase-result.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    prepare_parser=sub.add_parser('prepare');prepare_parser.add_argument('--output',type=Path,required=True)
    for action in ('check','check-approval','execute'):
        p=sub.add_parser(action);p.add_argument('--operation',type=Path,required=True)
        if action!='check':p.add_argument('--phase',choices=('probe','collect'),required=True)
        if action=='execute':p.add_argument('--device-io',action='store_true')
    args=parser.parse_args()
    if args.action=='prepare':value=prepare(args.output)
    elif args.action=='check':value=check(args.operation)
    elif args.action=='check-approval':value=checked_approval(args.operation,args.phase)
    else:value=execute(args.operation,args.phase,args.device_io)
    print(json.dumps({k:v for k,v in value.items() if k not in ('sources','runtime','artifacts')},ensure_ascii=False,indent=2))
    return 3 if args.action=='execute' and value.get('execution_succeeded') is not True else 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (Exception,KeyboardInterrupt) as exc:
        print('停止：'+type(exc).__name__+': '+str(exc),file=sys.stderr);raise SystemExit(2)
