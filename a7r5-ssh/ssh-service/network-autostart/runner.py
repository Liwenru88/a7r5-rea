"""独立批准的一次性SSH调度；默认仅核对离线材料。"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import credentials
from native_validation import public_key,run_bounded
from mount_policy import validate_mounts

HERE=Path(__file__).resolve().parent
ACTIONS=('install','rollback','neutralize')
RISK=('通过已有SSH一次安装网络触发自启，仅匹配root及系统父挂载视图的wpa_supplicant；'
      '复用旧启动器和密钥，不改原账户，不停止当前SSH，不启动第二实例，不重启。'
      '新增独立/etc目录及RAM暂存/抑制凭证，将已知旧预加载指针原子切换为network.so；'
      '当前开机抑制网络触发，后续仅在RAM可用、无旧实例/残留且端口空闲时允许一次尝试。'
      '静态回滚恢复旧指针，静态中和恢复512换行；均不停止已运行服务。'
      '仍有全局预加载损坏、启动受影响、固定root密码和0.0.0.0:2222常驻监听及独立恢复受限风险。'
      '失败不自动重试、回滚、清理、断电，不操作SD卡；安装与开关机验收分别确认。')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def regular(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():raise ValueError('拒绝链接或非普通材料')
    return path
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def verify(root):
    root=Path(root).resolve();seal=json.loads(regular(root/'seal.json').read_text())
    for name,digest in seal['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or sha(regular(root/name))!=digest:raise ValueError('材料摘要不符：'+name)
    op=json.loads((root/'operation.json').read_text())
    if (op['target_ip']!='10.10.10.177' or op['port']!=2222 or op['trigger']!='/usr/bin/wpa_supplicant'
            or not re.fullmatch('[a-f0-9]{32}',op['net_id'])):raise ValueError('目标绑定不符')
    for path,digest in op['dependencies'].items():
        if sha(regular(path))!=digest:raise ValueError('运行依赖改变')
    return op,sha(root/'seal.json')


def approved(root,path,action,op,sealed):
    expected=dict(schema='a7r5-network-autostart-approval-v1',action=action,net_id=op['net_id'],seal_sha256=sealed,
                  approved=True,risk=RISK,no_reboot=True,preserve_current_service=True)
    if json.loads(regular(path).read_text())!=expected:raise PermissionError('缺少本动作的独立批准')
    if (root/('attempt-'+action+'.lock')).exists() or (root/('result-'+action)).exists():raise FileExistsError('本动作已使用，不重试')


def common(root,op):
    return ['-F','/dev/null','-o','HostKeyAlias=a7r5-netstart-'+op['net_id'],
        '-o','UserKnownHostsFile='+str(root/'known_hosts'),'-o','GlobalKnownHostsFile=/dev/null',
        '-o','StrictHostKeyChecking=yes','-o','HostKeyAlgorithms=ecdsa-sha2-nistp256','-o','IdentityAgent=none',
        '-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','NumberOfPasswordPrompts=1',
        '-o','ConnectionAttempts=1','-o','ConnectTimeout=10','-o','ControlMaster=no','-o','ControlPath=none',
        '-o','ClearAllForwardings=yes','-o','ForwardAgent=no']


@contextlib.contextmanager
def secret_env(password):
    with tempfile.TemporaryDirectory(prefix='a7r5-netstart-') as temp:
        temp=Path(temp);secret=temp/'password';secret.write_text(password+'\n');secret.chmod(0o600)
        ask=temp/'askpass';ask.write_text('#!/bin/sh\nexec /bin/cat "$A7R5_PASSWORD_FILE"\n');ask.chmod(0o700)
        yield dict(PATH='/usr/bin:/bin',LC_ALL='C',SSH_ASKPASS=str(ask),SSH_ASKPASS_REQUIRE='force',DISPLAY='local',A7R5_PASSWORD_FILE=str(secret))


def preflight(op):
    ram=op['service_ram']
    script="set -eu\nprintf 'A7R5_NET_PREFLIGHT1\\n'\n/bin/busybox cat /proc/self/status\n"
    for label,command in [('NS','/bin/busybox readlink /proc/self/ns/mnt'),('MOUNTS','/bin/busybox cat /proc/self/mountinfo'),
        ('READY','/bin/busybox cat '+ram+'/ready'),('PUBLIC','/bin/busybox cat '+ram+'/host-public-key'),
        ('HEART1','/bin/busybox cat '+ram+'/heartbeat'),('HEART2','/bin/busybox sleep 2\n/bin/busybox cat '+ram+'/heartbeat'),
        ('PRELOAD','/bin/busybox cat /etc/ld.so.preload')]:
        script+="printf '\\n===%s===\\n' '"+label+"'\n"+command+'\n'
    script+="printf '\\n===ORIGINAL_HASHES===\\n'\n/usr/bin/openssl dgst -sha256 /proc/1/root/etc/passwd /proc/1/root/etc/nsswitch.conf /proc/1/root/etc/ssh/sshd_config\nprintf '===END===\\n'\n"
    return script.encode()


def validate_preflight(raw,op,root):
    if not raw.startswith(b'A7R5_NET_PREFLIGHT1\n'):raise ValueError('预检起始标记不符')
    labels=['NS','MOUNTS','READY','PUBLIC','HEART1','HEART2','PRELOAD','ORIGINAL_HASHES']
    pattern=b''.join(rb'\n==='+s.encode()+rb'===\n(.*?)' for s in labels)+rb'===END===\n'
    m=re.search(pattern,raw,re.S)
    if not m or m.end()!=len(raw):raise ValueError('预检分段不完整')
    for name in (b'Uid',b'Gid'):
        values=re.findall(rb'^'+name+rb':\s*([^\n]+)$',raw[:m.start()],re.M)
        if len(values)!=1 or values[0].split()!=[b'0']*4:raise ValueError('预检不是root')
    ns,mounts,ready,pub,first,last,preload,hashes=m.groups()
    if ns!=op['active_namespace'].encode()+b'\n' or ready!=(root/'materials/expected-ready.bin').read_bytes():raise ValueError('当前私有实例变化')
    if public_key(pub)[0]!=public_key((root/'materials/trusted-host-public-key').read_bytes())[0]:raise ValueError('主机公钥变化')
    # 每个分段前增加一个换行；去掉分隔符后这里保留的只是文件自身换行。
    for name,value in [('ready',ready),('first',first),('last',last)]:
        if not value.endswith(b'\n'):raise ValueError('回执缺少换行：'+name)
    identity=re.fullmatch(rb'A7R5_PRIVATE_READY '+op['service_run'].encode()+rb' parent=(\d+) child=(\d+) uid=0 euid=0 ttl=0 parent_unchanged=1 private_account_changed=1 parent_ns=(mnt:\[\d+\]) child_ns=(mnt:\[\d+\]) host_public_sha=([0-9a-f]{64})\n',ready)
    if not identity or min(int(identity[1]),int(identity[2]))<=1 or identity[1]==identity[2] or identity[3]==identity[4] or identity[4]+b'\n'!=ns:raise ValueError('READY隔离身份不符')
    def heartbeat(value):
        row=re.fullmatch(rb'A7R5_PRIVATE_ALIVE '+op['service_run'].encode()+rb' parent='+identity[1]+rb' child='+identity[2]+rb' ttl=0 elapsed_ms=(\d{1,16}) parent_unchanged=1\n',value)
        if not row:raise ValueError('心跳身份不符')
        return int(row[1])
    if heartbeat(last)<=heartbeat(first):raise ValueError('心跳未前进')
    if preload!=(root/'materials/preload.previous').read_bytes():raise ValueError('旧预加载指针变化')
    parsed={}
    for line in hashes.decode().splitlines():
        row=re.fullmatch(r'SHA(?:2-)?256\(([^)]+)\)= ([0-9a-f]{64})',line)
        if not row or row[1] in parsed:raise ValueError('原件摘要格式不符')
        parsed[row[1]]=row[2]
    if parsed!=op['original_hashes']:raise ValueError('原账户、NSS或配置发生变化')
    return validate_mounts(mounts,op)


def execute(root,op,action,password,output,transport=run_bounded):
    root=Path(root);output=Path(output)
    report=dict(action=action,net_id=op['net_id'],connections=0,uploads=0,camera_usb_requests=0,
                debug_attempts=0,reboot_attempts=0,current_service_stop_requested=False,automatic_retry=False,
                real_boot_verified=False,network_trigger_verified=False)
    def command(stage,argv,data,environment,limit=8192):
        report.update(stage=stage,connections=report['connections']+1)
        code,stdout,stderr=transport(argv,data,environment,seconds=40,stdout_limit=limit,stderr_limit=8192)
        for suffix,value in [('stdout',stdout),('stderr',stderr)]:
            (output/(stage+'-'+suffix+'.txt')).write_bytes(value.replace(password.encode(),b'[REDACTED]'))
        if code:raise RuntimeError(stage+'失败；停止，不重连，机身可能有残留')
        return stdout
    options=common(root,op);target='root@'+op['target_ip']
    def ssh(script):return ['/usr/bin/ssh',*options,'-T','-p','2222',target,'/bin/busybox sh -s'],script
    try:
        with secret_env(password) as environment:
            if action=='install':
                argv,data=ssh(preflight(op));raw=command('preflight',argv,data,environment,131072)
                report['mount_evidence']=validate_preflight(raw,op,root)
                directory=op['stage_dir']
                script=('set -eu\numask 077\n[ ! -e '+directory+' ] && [ ! -L '+directory+' ] || exit 81\n/bin/busybox mkdir '+directory+'\n/bin/busybox chmod 700 '+directory+'\nprintf "A7R5_NET_STAGE1\\n"\n').encode()
                argv,data=ssh(script)
                if command('stage',argv,data,environment)!=b'A7R5_NET_STAGE1\n':raise ValueError('暂存回执不符')
                for name in ('network.so','control.static'):
                    report['uploads']+=1
                    if command('upload-'+name,['/usr/bin/scp',*options,'-q','-P','2222',str(root/'materials'/name),target+':'+directory+'/'+name],None,environment):raise ValueError('上传有非预期输出')
                control=directory+'/control.static'
                script=('set -eu\nvalue=$(/usr/bin/openssl dgst -sha256 '+control+')\n[ "${value##* }" = '+op['payloads']['control.static']['sha256']+' ] || exit 82\n/bin/busybox chmod 700 '+control+'\nexec '+control+' install\n').encode()
                argv,data=ssh(script)
                if command('install',argv,data,environment)!=('A7R5_NET_INSTALLED1 '+op['net_id']+' current_boot_suppressed=1 service_preserved=1 rebooted=0\n').encode():raise ValueError('安装回执不符，不能重跑')
                script=('set -eu\nprintf "A7R5_NET_POST1\\n"\n/bin/busybox cat /etc/ld.so.preload\n/bin/busybox cat '+op['service_ram']+'/ready\n/bin/busybox cat '+op['net_dir']+'/enabled\nprintf "A7R5_NET_POST_END1\\n"\n').encode()
                argv,data=ssh(script)
                expected=b'A7R5_NET_POST1\n'+(op['net_dir']+'/network.so\n').encode()+(root/'materials/expected-ready.bin').read_bytes()+(op['net_id']+'\nA7R5_NET_POST_END1\n').encode()
                if command('postflight',argv,data,environment)!=expected:raise ValueError('安装后当前实例或指针不符')
                report.update(current_service_ready_unchanged=True,current_boot_suppressed=True,persistent_pointer='network')
            elif action in ('rollback','neutralize'):
                control=op['net_dir']+'/control.static'
                script=('set -eu\nvalue=$(/usr/bin/openssl dgst -sha256 '+control+')\n[ "${value##* }" = '+op['payloads']['control.static']['sha256']+' ] || exit 82\nexec '+control+' '+action+'\n').encode()
                argv,data=ssh(script)
                prefix='A7R5_NET_ROLLED_BACK1' if action=='rollback' else 'A7R5_NET_NEUTRAL1'
                if command(action,argv,data,environment)!=(prefix+' '+op['net_id']+' service_preserved=1\n').encode():raise ValueError('恢复回执不符，不重跑')
                report['persistent_pointer']='previous' if action=='rollback' else 'neutral'
            else:raise ValueError('未知动作')
        report['status']='passed'
    except BaseException as exc:
        report.update(status='failed',error_type=type(exc).__name__,remote_state_may_be_partial=True)
        raise
    finally:save(output/'result.json',report)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=ACTIONS)
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--approval',type=Path);parser.add_argument('--credentials',type=Path)
    args=parser.parse_args(argv);op,sealed=verify(HERE)
    if args.dry_run:
        print(json.dumps(dict(action=args.action,target=op['target_ip'],port=2222,max_connections=6 if args.action=='install' else 1,
            payload_uploads=2 if args.action=='install' else 0,camera_io=False,requires_exact_approval=True,real_boot_verified=False),ensure_ascii=False,indent=2));return
    if args.approval is None or args.credentials is None:raise PermissionError('必须提供本动作批准及包外受限凭据')
    approved(HERE,args.approval,args.action,op,sealed);password=credentials.load(args.credentials)
    lock=HERE/('attempt-'+args.action+'.lock')
    fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(dict(action=args.action,net_id=op['net_id']),f);f.flush();os.fsync(f.fileno())
    output=HERE/('result-'+args.action);output.mkdir(mode=0o700)
    print(json.dumps(execute(HERE,op,args.action,password,output),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
