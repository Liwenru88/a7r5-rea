"""有批准文件才执行的一次性SSH入口；导入及--dry-run均不联网。"""
import argparse,contextlib,hashlib,json,os,re,stat,sys,tempfile
from pathlib import Path
import credentials
from native_validation import public_key,run_bounded
HERE=Path(__file__).resolve().parent
ACTIONS=('enable','disable','recover')

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def checked(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('拒绝链接包路径')
    if not path.is_file():raise ValueError('包文件不是普通文件')
    return path

def verify_package(root):
    root=Path(root).resolve();seal=checked(root/'seal.json')
    data=json.loads(seal.read_text())
    for name,expected in data['files'].items():
        if name.startswith('/') or '..' in Path(name).parts:raise ValueError('非法清单路径')
        if digest(checked(root/name))!=expected:raise ValueError('包文件摘要不符：'+name)
    op=json.loads((root/'operation.json').read_text())
    if op['target_ip']!='10.10.10.177' or op['port']!=2222 or not re.fullmatch('[a-f0-9]{32}',op['auto_id']):raise ValueError('目标绑定不符')
    return op,digest(seal)

def approval(root,path,action,op,sealsha):
    value=json.loads(checked(path).read_text())
    expected=dict(schema='a7r5-autostart-approval-v1',action=action,auto_id=op['auto_id'],seal_sha256=sealsha,
                  approved=True,accept_persistent_loader_risk=True,no_reboot=True,preserve_current_service=True)
    if value!=expected:raise PermissionError('缺少本动作精确批准；模板不能直接执行')

def preflight_script(op):
    return ("set -eu\nprintf 'A7R5_AUTO_PREFLIGHT1\\n'\n/bin/busybox cat /proc/self/status\n"
            "printf '\\n===NS===\\n'\n/bin/busybox readlink /proc/self/ns/mnt\n"
            "printf '===MOUNTS===\\n'\n/bin/busybox cat /proc/self/mountinfo\n"
            "printf '===READY===\\n'\n/bin/busybox cat "+op['ram_root']+"/ready\n"
            "printf '===PUBLIC===\\n'\n/usr/bin/ssh-keygen -y -f "+op['private_source']+"/host_ecdsa\n"
            "printf '===END===\\n'\n").encode()

def validate_mounts(raw,op):
    """只接受已验证服务的VFAT底层、私有tmpfs及只读账户绑定关系。"""
    rows={};points={}
    def path_text(value):
        escapes={'040':' ','011':'\t','012':'\n','134':'\\'}
        if re.search(r'\\(?!040|011|012|134)',value):raise ValueError('挂载路径转义不符')
        return re.sub(r'\\(040|011|012|134)',lambda m:escapes[m[1]],value)
    try:
        for line in raw.decode('ascii').splitlines():
            before,after=line.split(' - ',1);cols=before.split();fs=after.split()
            if len(cols)<6 or len(fs)!=3:raise ValueError('挂载记录字段不完整')
            if any(not re.fullmatch(r'[1-9][0-9]*',v) for v in cols[:2]):raise ValueError('挂载ID不符')
            mid,parent=map(int,cols[:2])
            if mid in rows or mid==parent or not re.fullmatch(r'[0-9]+:[0-9]+',cols[2]):raise ValueError('挂载ID或设备号重复/不符')
            row=dict(id=mid,parent=parent,device=cols[2],root=path_text(cols[3]),point=path_text(cols[4]),
                     flags=set(cols[5].split(',')),optional=cols[6:],fstype=fs[0],source=fs[1],superflags=set(fs[2].split(',')))
            if not row['point'].startswith('/') or not row['root'].startswith('/'):raise ValueError('挂载路径不是绝对路径')
            rows[mid]=row;points.setdefault(row['point'],[]).append(row)
    except (UnicodeDecodeError,IndexError) as error:raise ValueError('挂载记录格式不符') from error
    def one(point):
        found=points.get(point,[])
        if len(found)!=1:raise ValueError('挂载缺失或重复：'+point)
        return found[0]
    def access(row,mode):return row['flags']&{'ro','rw'}=={mode} and row['superflags']&{'ro','rw'}=={'rw'}
    def base_vfat(row):return row['root']=='/' and row['fstype']=='vfat' and row['source']=='/dev/nflasha10' and access(row,'rw')
    etc=one('/etc');network=one('/tmp_network');account=one('/etc/passwd')
    original=[r for r in points.get('/var',[]) if r['fstype']=='vfat']
    private=[r for r in points.get('/var',[]) if r['fstype']=='tmpfs']
    if len(points.get('/var',[]))!=2 or len(original)!=1 or len(private)!=1:raise ValueError('/var不是已知的两层挂载')
    lower,upper=original[0],private[0]
    if not base_vfat(etc) or not base_vfat(lower):raise ValueError('配置分区或/var底层不符')
    if lower['device']!=etc['device'] or lower['parent']!=etc['parent']:raise ValueError('/var底层与/etc来源关系不符')
    if upper['parent']!=lower['id'] or upper['root']!='/' or upper['fstype']!='tmpfs' or upper['source']!='a7r5-private-ssh':raise ValueError('/var私有挂载父子关系或来源不符')
    if not upper['device'].startswith('0:') or upper['device']==lower['device'] or not access(upper,'rw') or not {'nosuid','nodev'}<=upper['flags']:raise ValueError('/var私有tmpfs属性不符')
    if network['root']!='/' or network['fstype']!='tmpfs' or network['source']!='none' or not network['device'].startswith('0:') or network['device']==upper['device'] or network['parent']!=etc['parent'] or not access(network,'rw'):raise ValueError('/tmp_network不是已知独立tmpfs')
    expected=op['private_source'].removeprefix('/var')+'/passwd.view'
    if account['parent']!=etc['id'] or account['root']!=expected or account['device']!=upper['device'] or account['fstype']!='tmpfs' or account['source']!='a7r5-private-ssh' or not access(account,'ro'):raise ValueError('私有账户只读绑定关系不符')
    # 关键树不接受额外遮蔽挂载；/dev/pts叠加位于该范围外，保持原有处理。
    allowed={'/etc','/etc/passwd','/var','/tmp_network'}
    for row in rows.values():
        point=row['point']
        if any(point==p or point.startswith(p+'/') for p in ('/etc','/var','/tmp_network')):
            if point not in allowed or row['optional']:raise ValueError('关键路径存在未知子挂载或传播属性')
    return dict(policy='private-var-stack-v2',etc_mount_id=etc['id'],var_lower_id=lower['id'],var_private_id=upper['id'],
                account_bind_id=account['id'],network_mount_id=network['id'],var_parent_chain_verified=True,account_readonly_bind_verified=True)

def validate_preflight(raw,op,root):
    if not raw.startswith(b'A7R5_AUTO_PREFLIGHT1\n'):raise ValueError('预检起始标识不符')
    pattern=rb'\n===NS===\n([^\n]+)\n===MOUNTS===\n(.*?)===READY===\n(.*?)===PUBLIC===\n(.*?)===END===\n'
    match=re.search(pattern,raw,re.S)
    if not match or match.end()!=len(raw):raise ValueError('预检分段不符')
    for label in (b'Uid',b'Gid'):
        fields=re.findall(rb'^'+label+rb':\s*([^\n]+)$',raw[:match.start()],re.M)
        if len(fields)!=1 or fields[0].split()!=[b'0']*4:raise ValueError('预检不是root身份')
    ns,mounts,ready,pub=match.groups()
    if ns.decode()!=op['active_namespace']:raise ValueError('已验证私有实例发生变化，停止')
    if ready!=(root/'materials/expected-ready.bin').read_bytes():raise ValueError('READY会话不符')
    if public_key(pub)[0]!=public_key((root/'materials/trusted-host-public-key').read_bytes())[0]:raise ValueError('私有密钥与可信主机公钥不配对')
    return validate_mounts(mounts,op)

def common_options(root,op):
    return ['-F','/dev/null','-o','HostKeyAlias=a7r5-autostart-'+op['auto_id'],
        '-o','UserKnownHostsFile='+str(root/'known_hosts'),'-o','GlobalKnownHostsFile=/dev/null',
        '-o','StrictHostKeyChecking=yes','-o','HostKeyAlgorithms=ecdsa-sha2-nistp256',
        '-o','IdentityAgent=none','-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password',
        '-o','NumberOfPasswordPrompts=1','-o','ConnectionAttempts=1','-o','ConnectTimeout=10',
        '-o','ControlMaster=no','-o','ControlPath=none','-o','ClearAllForwardings=yes','-o','ForwardAgent=no']

@contextlib.contextmanager
def secret_environment(password):
    with tempfile.TemporaryDirectory(prefix='a7r5-auto-askpass-') as temp:
        temp=Path(temp);secret=temp/'password';secret.write_text(password+'\n');secret.chmod(0o600)
        ask=temp/'askpass';ask.write_text('#!/bin/sh\nexec /bin/cat "$A7R5_PASSWORD_FILE"\n');ask.chmod(0o700)
        yield dict(PATH='/usr/bin:/bin',LC_ALL='C',SSH_ASKPASS=str(ask),SSH_ASKPASS_REQUIRE='force',
                    DISPLAY='local-askpass',A7R5_PASSWORD_FILE=str(secret))

def execute(root,op,action,password,output,*,transport=run_bounded):
    if action not in ACTIONS:raise ValueError('动作不符')
    root=Path(root);output=Path(output);options=common_options(root,op);target='root@'+op['target_ip']
    report=dict(action=action,auto_id=op['auto_id'],connections=0,reboot_attempts=0,debug_attempts=0,
                camera_service_stop_attempts=0,automatic_retry=False,camera_io=True,current_service_stop_requested=False)
    def command(stage,args,data,environment,limit=8192):
        report['stage']=stage;report['connections']+=1
        code,stdout,stderr=transport(args,data,environment,seconds=45,stdout_limit=limit,stderr_limit=4096)
        for kind,raw in [('stdout',stdout),('stderr',stderr)]:
            (output/(stage+'-'+kind+'.txt')).write_bytes(raw.replace(password.encode(),b'[REDACTED]'))
        if code:raise RuntimeError(stage+'失败，停止且不重连；远端可能有残留')
        return stdout
    def ssh(script):return ['/usr/bin/ssh',*options,'-T','-p','2222',target,'/bin/busybox sh -s'],script
    try:
        with secret_environment(password) as environment:
            if action=='enable':
                argv,script=ssh(preflight_script(op));raw=command('preflight',argv,script,environment,81920)
                report['mount_evidence']=validate_preflight(raw,op,root);report['preflight_verified']=True
                script=("set -eu\numask 077\n[ ! -e "+op['stage_dir']+" ] && [ ! -L "+op['stage_dir']+" ] || exit 81\n/bin/busybox mkdir "+op['stage_dir']+"\n/bin/busybox chmod 700 "+op['stage_dir']+"\nprintf 'A7R5_AUTO_STAGE_READY1\\n'\n").encode()
                argv,script=ssh(script)
                if command('stage',argv,script,environment)!=b'A7R5_AUTO_STAGE_READY1\n':raise ValueError('暂存回执不符')
                for name in ('control.static','boot.so','ssh-service.arm64'):
                    raw=command('upload-'+name,['/usr/bin/scp',*options,'-q','-P','2222',str(root/'materials'/name),target+':'+op['stage_dir']+'/'+name],None,environment)
                    if raw:raise ValueError('SCP存在非预期标准输出')
                control=op['stage_dir']+'/control.static'
                script=("set -eu\nvalue=$(/usr/bin/openssl dgst -sha256 "+control+")\n[ \"${value##* }\" = '"+op['payloads']['control.static']['sha256']+"' ] || exit 82\n/bin/busybox chmod 700 "+control+"\nexec "+control+" enable\n").encode()
                argv,script=ssh(script);expected=('A7R5_AUTO_ENABLED1 '+op['auto_id']+' current_boot_suppressed=1 service_preserved=1 rebooted=0\n').encode()
                if command('enable',argv,script,environment)!=expected:raise ValueError('启用回执不符，需人工判断，不重跑')
                report.update(persistent_preload_armed=True,current_boot_suppressed=True,real_boot_verified=False)
            else:
                # 控制器不依赖动态加载器；已有SSH不可用时，此入口也无法建立连接。
                script=('exec '+op['auto_dir']+'/control.static '+action+'\n').encode()
                argv,script=ssh(script);raw=command(action,argv,script,environment)
                prefix='A7R5_AUTO_DISABLED1' if action=='disable' else 'A7R5_AUTO_RECOVERED1'
                allowed={(prefix+' '+op['auto_id']+' service_preserved=1\n').encode(),('A7R5_AUTO_NEUTRAL1 '+op['auto_id']+' service_preserved=1\n').encode()}
                if raw not in allowed:raise ValueError('中和回执不符，不重试')
                report['persistent_preload_neutral']=True
        report['status']='passed'
    except BaseException as error:
        report.update(status='failed',error_type=type(error).__name__,remote_state_may_be_partial=True)
        raise
    finally:
        (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=ACTIONS);parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--approval',type=Path);parser.add_argument('--credentials',type=Path)
    args=parser.parse_args(argv);op,sealsha=verify_package(HERE)
    if args.dry_run:
        print(json.dumps(dict(action=args.action,target=op['target_ip'],port=2222,seal_sha256=sealsha,
          max_connections=6 if args.action=='enable' else 1,camera_io=False,reboot=False,requires_exact_approval=True),ensure_ascii=False,indent=2));return
    if args.approval is None or args.credentials is None:raise PermissionError('必须先确认方案并提供本动作批准文件和本地受限口令文件')
    approval(HERE,args.approval,args.action,op,sealsha)
    password=credentials.load(args.credentials)
    lock=HERE/('attempt-'+args.action+'.lock')
    fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(json.dumps(dict(action=args.action,auto_id=op['auto_id']))+'\n');stream.flush();os.fsync(stream.fileno())
    output=HERE/('result-'+args.action);output.mkdir(mode=0o700)
    result=execute(HERE,op,args.action,password,output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
