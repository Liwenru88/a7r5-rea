"""仅本地Unix中继+无NIC沙箱QEMU；真实Mac SSH/PTY/SCP验收。"""
from contextlib import contextmanager
import hashlib,json,os,re,secrets,shlex,socket,struct,subprocess,sys,tempfile,threading,time
from pathlib import Path
import build
ROOT=build.HERE
sys.path[:0]=[str(build.PROJECT/'a7r5-ssh'),str(build.SERVICE),str(build.PROJECT/'a7r5-qemu/tools')]
import qemu_verify, vm_session
from native_vm import NativeVM
from runtime_manifest import verified_inputs


def put(vm,path,raw,mode='600'):
    # 仅QEMU串口批量短行写入；最终以客体SHA-256验证整文件，减少往返等待。
    target=shlex.quote(path)
    vm.command('stty -echo; umask 077; : > '+target)
    for start in range(0,len(raw),48*32):
        lines=[]
        for offset in range(start,min(len(raw),start+48*32),48):
            row=''.join('\\%03o'%b for b in raw[offset:offset+48])
            lines.append('printf '+shlex.quote(row)+' >> '+target+'\n')
        vm.process.stdin.write(''.join(lines).encode());vm.process.stdin.flush()
    sha=hashlib.sha256(raw).hexdigest()
    vm.command('chmod '+mode+' '+target+'; sum=$(/usr/bin/openssl dgst -sha256 '+target+'); stty echo; test "${sum##* }" = '+sha,timeout=60)


def main(soak_seconds=605):
    out=Path(tempfile.mkdtemp(prefix='qemu-',dir=ROOT/'verification'))
    password=str(secrets.randbelow(90000000)+10000000)
    candidate=build.build(out/'candidate',build.credentials.make_hash(password),qemu_only=True)
    prefix=candidate['prefix'];ram=candidate['ram_directory'];install=prefix
    (out/'relay.c').write_text((build.SERVICE/'tests/framed_relay.c').read_text())
    qemu_verify.build_target(out/'relay.c',out/'framed-relay')
    (out/'dlopen.c').write_text('extern void *dlopen(const char *,int); extern int puts(const char *); int main(int n,char **v){if(n!=2)return 64; if(!dlopen(v[1],2))return 1; puts("DLOPEN_RETURNED");return 0;}')
    build.compile_target(out/'dlopen.c',out/'dlopen',out/'candidate',extra_libraries=[build.PROJECT/'a7r5-qemu/sdk/lib/libdl-2.25.so'])
    for source,name in [('mutate.c','mutate'),('refuse_setns.c','refuse-setns')]:build.compile_target(ROOT/'tests'/source,out/name,out/'candidate')
    vm_session.RUNS=out;vm=NativeVM('original-view-ssh',capid=True,boot_services=True)
    inputs={k:build.sha(v) for k,v in verified_inputs().items()}
    result=dict(status='failed',camera_io=False,host_tcp_connections=0,guest_nic='none',run_id=candidate['run_id'],vm=str(vm.out),requested_soak_seconds=soak_seconds)
    short=Path(tempfile.mkdtemp(prefix='a7r5-ov-',dir='/tmp')).resolve()
    secret=short/'password';secret.write_text(password+'\n');secret.chmod(0o600)
    askpass=short/'askpass';askpass.write_text('#!/bin/sh\nexec /bin/cat "$A7R5_PASSWORD_FILE"\n');askpass.chmod(0o700)
    try:
        vm.start()
        vm.command('mount -t tmpfs -o mode=0755 tmpfs /etc; mount -t tmpfs -o mode=0755 tmpfs /var; mount -t tmpfs -o mode=1777 tmpfs /tmp_network; mkdir -p /etc/ssh /tmp/jiritsu /simulation /root /dev/pts; test -e /dev/ptmx || /bin/busybox mknod /dev/ptmx c 5 2')
        reference=build.SERVICE/'recovery-code85/packages/code85-recovery-20261021-02/reference'
        originals={ '/etc/passwd':(reference/'passwd.bin').read_bytes(),'/etc/nsswitch.conf':(reference/'nsswitch.bin').read_bytes(),'/etc/ssh/sshd_config':(reference/'sshd-config.bin').read_bytes() }
        for path,data in originals.items():put(vm,path,data)
        vm.command("printf 'ORIGINAL_VAR\\n' > /var/origin-marker")
        put(vm,'/etc/ld.so.preload',b'\n'*512)
        for destination,name in candidate['uploads'].items():put(vm,destination,(out/'candidate'/name).read_bytes(),'600')
        for name in ['framed-relay','mutate','refuse-setns','dlopen']:put(vm,'/simulation/'+name,(out/name).read_bytes(),'700')
        preflight=vm.command('test ! -e '+ram+'/ready; test ! -e '+ram+'/origin.bin; test ! -e /tmp/jiritsu/libJit.so; cat /proc/net/tcp')
        (out/'loaded-not-started.txt').write_bytes(preflight)
        put(vm,prefix+'.ticket',(out/'candidate/ticket.bin').read_bytes())
        put(vm,'/tmp/jiritsu/libJit.so',(out/'candidate/libJit.so').read_bytes())
        initial=vm.command('readlink /proc/self/ns/mnt; printf ORIGINAL_UMASK:; umask; cat /proc/self/status; /simulation/dlopen /tmp/jiritsu/libJit.so; sleep 2; cat '+ram+'/ready '+ram+'/host-public-key; :')
        start_time=time.monotonic()
        (out/'launch.txt').write_bytes(initial)
        if b'A7R5_PRIVATE_READY '+candidate['run_id'].encode() not in initial:
            (out/'diagnostic.txt').write_bytes(vm.command('cat '+ram+'/result '+ram+'/child-result '+ram+'/diagnostic; :'))
            raise ValueError('新载荷未READY')
        assert b'DLOPEN_RETURNED' in initial and b'ttl=0' in initial
        vm.command('test ! -e /tmp/jiritsu/libJit.so; test ! -e '+prefix+'.ticket; test -r '+prefix+'.claim; /usr/bin/openssl dgst -sha256 /etc/ld.so.preload')
        refused=vm.command(prefix+'.service --launch-original; rc=$?; test "$rc" != 0; cat '+ram+'/ready')
        result['duplicate_start_refused']=True
        public=re.search(rb'ecdsa-sha2-nistp256 ([A-Za-z0-9+/=]+)',initial);assert public
        hosts=short/'known_hosts';hosts.write_bytes(b'a7r5-qemu ecdsa-sha2-nistp256 '+public[1]+b'\n');hosts.chmod(0o600)
        result['loaded_separately_then_dlopen_once_no_preload_write']=True
        @contextmanager
        def bridge():
            offset=vm.console.stat().st_size
            vm.process.stdin.write(b"/bin/busybox stty raw -echo; /simulation/framed-relay; /bin/busybox stty sane; printf '\\nA7R5_RELAY_EXIT\\n'\n");vm.process.stdin.flush()
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                raw=vm.console.read_bytes()[offset:]
                if b'A7R5_RELAY_READY\n' in raw:break
                time.sleep(.01)
            else:raise TimeoutError('中继未READY')
            cursor=[offset+raw.index(b'A7R5_RELAY_READY\n')+17]
            path=short/'bridge.sock';server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));server.listen(1);server.settimeout(12)
            errors=[];finished=threading.Event()
            def exact(n):
                data=b'';until=time.monotonic()+25
                while len(data)<n:
                    with vm.console.open('rb') as stream:stream.seek(cursor[0]);part=stream.read(n-len(data))
                    if part:data+=part;cursor[0]+=len(part)
                    elif time.monotonic()>until:raise TimeoutError('串口帧等待超时')
                    else:time.sleep(.005)
                return data
            def serve():
                try:
                    peer,_=server.accept();peer.settimeout(25)
                    def incoming():
                        try:
                            while True:
                                raw=peer.recv(4096)
                                vm.process.stdin.write(struct.pack('<I',len(raw))+raw);vm.process.stdin.flush()
                                if not raw:return
                        except Exception as exc:
                            if not finished.is_set():errors.append(type(exc).__name__)
                    upstream=threading.Thread(target=incoming,daemon=True);upstream.start()
                    while True:
                        count=struct.unpack('<I',exact(4))[0]
                        if count>4096:raise ValueError('串口帧失步')
                        if not count:break
                        peer.sendall(exact(count))
                    finished.set();peer.close();upstream.join(2)
                except Exception as exc:errors.append(type(exc).__name__+': '+str(exc))
                finally:finished.set()
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            try:yield path
            finally:
                worker.join(30);server.close();path.unlink(missing_ok=True)
                if worker.is_alive() or errors:raise RuntimeError('本机中继未正常退出：'+repr(errors))
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    if b'\nA7R5_RELAY_EXIT' in vm.console.read_bytes()[cursor[0]:]:break
                    time.sleep(.01)
                else:raise TimeoutError('串口未归还控制台')


        def client(program,args,stdin=None,expected=0):
            with bridge() as path:
                proxy=shlex.join([str(Path(sys.executable).absolute()),str(build.SERVICE/'tests/stdio_unix_proxy.py'),str(path)])
                common=['-F','/dev/null','-o','ProxyCommand='+proxy,'-o','HostKeyAlias=a7r5-qemu','-o','UserKnownHostsFile='+str(hosts),'-o','GlobalKnownHostsFile=/dev/null','-o','StrictHostKeyChecking=yes','-o','IdentityAgent=none','-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','NumberOfPasswordPrompts=1','-o','ConnectTimeout=10']
                env=os.environ|dict(SSH_ASKPASS=str(askpass),SSH_ASKPASS_REQUIRE='force',DISPLAY='offline',A7R5_PASSWORD_FILE=str(secret))
                completed=subprocess.run([program,*common,*args],input=stdin,capture_output=True,timeout=40,env=env)
                tag='client-'+str(len(list(out.glob('client-*.json'))))
                (out/(tag+'.stdout')).write_bytes(completed.stdout);(out/(tag+'.stderr')).write_bytes(completed.stderr)
                (out/(tag+'.json')).write_text(json.dumps(dict(program=program,exit_code=completed.returncode,expected=expected)))
                if completed.returncode!=expected:raise ValueError(tag+'退出码'+str(completed.returncode)+'，预期'+str(expected))
                return completed
        def ssh(command,**kw):return client('/usr/bin/ssh',['-T','-p','2222','root@a7r5-qemu',command],**kw)
        view=ssh("cat /var/origin-marker; /bin/busybox readlink /proc/self/ns/mnt; cat /etc/passwd; printf '%s|%s|%s\\n' \"$PATH\" \"$HOME\" \"$LC_ALL\"; pwd; printf SESSION_UMASK:; umask; cat /proc/self/status")
        (out/'original-session.txt').write_bytes(view.stdout)
        assert b'ORIGINAL_VAR\n' in view.stdout and originals['/etc/passwd'] in view.stdout
        assert b'/bin:/sbin:/usr/bin:/usr/sbin|/|C\n' in view.stdout
        ns=re.search(rb'mnt:\[[0-9]+\]',initial)[0];assert ns in view.stdout
        for key in ['CapInh','CapPrm','CapEff','CapBnd','CapAmb']:
            pattern=key.encode()+rb':\s+([0-9a-f]+)'
            assert re.search(pattern,initial)[1]==re.search(pattern,view.stdout)[1]
        assert re.search(rb'ORIGINAL_UMASK:([0-7]+)',initial)[1]==re.search(rb'SESSION_UMASK:([0-7]+)',view.stdout)[1]
        for key in ['Uid','Gid']:assert re.search(key.encode()+rb':\s+0\s+0\s+0\s+0',view.stdout)
        assert re.search(rb'Groups:\s*\n',view.stdout)
        result['original_view_root_cap_environment']=True
        result['default_ttl_zero']=True
        keycopy=vm.command('cat '+ram+'/hostkey-check')
        (out/'ram-key-check.txt').write_bytes(keycopy)
        assert b'verified=1 mode=600 tmpfs=1 private_key_logged=0' in keycopy
        result['host_key_generated_only_in_private_ram']=True
        quoted=ssh("printf '%s\\n' 'space $dollar; `literal`' 'single"+'"'+"quote'; exit 23",expected=23)
        assert b'space $dollar; `literal`\n' in quoted.stdout
        stdin=client('/usr/bin/ssh',['-T','-p','2222','root@a7r5-qemu','/bin/sh -s'],b"cat /var/origin-marker; printf 'STDIN_OK\\n'; exit 0\n")
        assert b'STDIN_OK\n' in stdin.stdout
        terminal=client('/usr/bin/ssh',['-tt','-p','2222','root@a7r5-qemu'],b"[ -t 0 ] && [ -t 1 ] && printf 'PTY_OK\\n'; /bin/busybox stty rows 31 cols 97; /bin/busybox stty size; cat /var/origin-marker; exit 0\n")
        assert b'\nPTY_OK\r\n' in terminal.stdout and b'31 97\r\n' in terminal.stdout and b'ORIGINAL_VAR\r\n' in terminal.stdout
        result['commands_stdin_exit_pty_winsize']=True
        sys.path.extend(str(p) for p in (Path.home()/'.codex/skills/ssh-skill/.venv/lib').glob('python*/site-packages'))
        import paramiko
        with bridge() as path:
            peer=socket.socket(socket.AF_UNIX);peer.connect(str(path));connection=paramiko.Transport(peer)
            try:
                connection.start_client(timeout=10)
                assert connection.get_remote_server_key().asbytes()==__import__('base64').b64decode(public[1])
                connection.auth_password('root',password)
                channel=connection.open_session(timeout=8);channel.get_pty(term='xterm',width=70,height=20)
                channel.exec_command("trap 'printf \"INT_SEEN\\n\"' INT; printf 'INT_READY\\n'; /bin/busybox sleep 20; printf 'RESIZE_READY\\n'; read next; /bin/busybox stty size; exit 0")
                transcript=b'';channel.settimeout(10)
                while b'INT_READY\r\n' not in transcript:transcript+=channel.recv(4096)
                channel.send(b'\x03')
                while b'RESIZE_READY\r\n' not in transcript:transcript+=channel.recv(4096)
                channel.resize_pty(width=101,height=33);channel.send('continue\n')
                while True:
                    part=channel.recv(4096)
                    if not part:break
                    transcript+=part
                (out/'signal-resize.stdout').write_bytes(transcript)
                assert channel.recv_exit_status()==0 and b'INT_SEEN\r\n' in transcript and b'33 101\r\n' in transcript
                channel.close()
            finally:connection.close()
        result['pty_ctrl_c_and_ssh_window_change']=True
        # 写原始/var哨兵并由原始控制台回读；私有/var不会出现该对象。
        ssh("printf 'SSH_WRITE\\n' > /var/raw-write")
        observed=vm.command('cat /var/raw-write; cat /var/origin-marker')
        assert b'SSH_WRITE' in observed
        data=bytes(range(256))*256;src=short/'binary source.bin';src.write_bytes(data);dest=short/'binary received.bin'
        remote='/var/binary transfer.bin'
        client('/usr/bin/scp',['-q','-P','2222',str(src),'root@a7r5-qemu:'+remote])
        client('/usr/bin/scp',['-q','-P','2222','root@a7r5-qemu:'+remote,str(dest)])
        assert dest.read_bytes()==data
        assert hashlib.md5(data).hexdigest().encode() in vm.command("/bin/busybox md5sum '/var/binary transfer.bin'")
        ssh("/bin/busybox ln -s '/var/binary transfer.bin' /var/transfer-link")
        dest2=short/'link received.bin';client('/usr/bin/scp',['-q','-P','2222','root@a7r5-qemu:/var/transfer-link',str(dest2)])
        assert dest2.read_bytes()==data
        result['sftp_default_scp_raw_view_bidirectional']=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),space_path=True,symlink=True)
        vm.command("mkdir /simulation/original-ro; mount -t tmpfs tmpfs /simulation/original-ro; printf 'READONLY\\n' > /simulation/original-ro/marker; mount -o remount,ro /simulation/original-ro")
        denied=ssh(': > /simulation/original-ro/new',expected=1)
        assert b'Read-only file system' in denied.stderr
        client('/usr/bin/scp',['-q','-P','2222',str(src),'root@a7r5-qemu:/simulation/original-ro/new'],expected=1)
        vm.command('test ! -e /simulation/original-ro/new')
        result['original_readonly_mount_not_remounted']=True
        background=ssh('/bin/busybox sleep 300 >/dev/null 2>&1 & printf "%s\\n" "$!"')
        background_pid=int(background.stdout.strip());vm.command('test -e /proc/'+str(background_pid))
        result['background_job_alive_after_disconnect']=True
        # 失败发生在真实入口；每次改坏证明后要求退出126且零用户命令执行。
        vm.command('cp '+ram+'/origin.bin /simulation/origin.saved')
        failures=[]
        for case in ['p','s','n','r','c','g','m']:
            vm.command('cp /simulation/origin.saved '+ram+'/origin.bin; chmod 400 '+ram+'/origin.bin; /simulation/mutate '+case)
            rejected=ssh(': > /simulation/must-not-exist',expected=126)
            assert b'A7R5_ORIGINAL_VIEW_REFUSED' in rejected.stderr
            vm.command('test ! -e /simulation/must-not-exist')
            failures.append(case)
        vm.command('cp /simulation/origin.saved '+ram+'/origin.bin; chmod 400 '+ram+'/origin.bin')
        injected=vm.command("SSH_ORIGINAL_COMMAND=': > /simulation/must-not-exist' /simulation/refuse-setns; probe_rc=$?; test \"$probe_rc\" = 126 && test ! -e /simulation/must-not-exist; printf 'SETNS_REFUSED_OK\\n'")
        assert b'SETNS_REFUSED_OK' in injected
        result['failure_zero_user_execution']=failures+['setns_injected_failure']
        # 原始配置有意更改后监督器仍存活，但必须报告变化；绝不写回。
        ssh("printf '# intentional QEMU change\\n' >> /etc/ssh/sshd_config; /bin/busybox sleep 2")
        monitor=vm.command('cat '+ram+'/heartbeat; /bin/busybox tail -n 1 /etc/ssh/sshd_config')
        assert b'parent_unchanged=0 changes_observed=1' in monitor and b'# intentional QEMU change' in monitor
        ssh('cat /var/origin-marker')
        result['user_changes_reported_without_kill_or_rollback']=True
        remaining=max(0,soak_seconds-(time.monotonic()-start_time))
        while remaining>0:
            pause=min(30,remaining)
            vm.command('sleep '+str(int(pause)+1)+'; test -r '+ram+'/ready; test ! -e '+ram+'/result',timeout=45)
            remaining=max(0,soak_seconds-(time.monotonic()-start_time))
            print(json.dumps(dict(stage='ttl-zero-soak',elapsed_seconds=round(time.monotonic()-start_time))),flush=True)
        alive=ssh('cat /var/origin-marker; printf "AFTER_SOAK_OK\\n"')
        assert b'AFTER_SOAK_OK' in alive.stdout
        result['ttl_zero_survived_seconds']=round(time.monotonic()-start_time,2)
        fresh=ssh('/bin/busybox sleep 1800 >/dev/null 2>&1 & printf "%s\\n" "$!"')
        fresh_pid=int(fresh.stdout.strip());vm.command('test -e /proc/'+str(fresh_pid))
        ended=vm.command(prefix+'.service --stop; cat '+ram+'/child-result; :',timeout=25)
        (out/'stopped.txt').write_bytes(ended)
        assert b'code=0 parent_unchanged=0 child_tree_reaped=1 child_terminal_seen=1 listener_absent=1 changes_observed=1' in ended
        assert b'PRIVATE_RESULT code=0 errno=0' in ended
        vm.command('test ! -e /proc/'+str(background_pid))
        vm.command('test ! -e /proc/'+str(fresh_pid))
        result.update(status='passed',supervisor_stop_descendants_listener_cleanup=True,active_background_descendant_reaped=True)
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc).replace(password,'[REDACTED]')
        import traceback
        (out/'failure-traceback.txt').write_text(traceback.format_exc().replace(password,'[REDACTED]'))
        try:(out/'failure-diagnostic.txt').write_bytes(vm.command('cat '+ram+'/result '+ram+'/child-result '+ram+'/diagnostic; cat /proc/self/status; ls -l /proc/*/exe; :',timeout=8))
        except Exception:pass
    finally:
        result['cleanup']=vm.close();result['runtime_inputs_unchanged']=inputs=={k:build.sha(v) for k,v in verified_inputs().items()}
        secret.unlink(missing_ok=True);askpass.unlink(missing_ok=True)
        if result['cleanup']!={'method':'qmp-quit','exit_code':0} or not result['runtime_inputs_unchanged']:result['status']='failed'
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(dict(output=str(out),**result),ensure_ascii=False),flush=True)
    return 0 if result['status']=='passed' else 1

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='无NIC QEMU真实客户端验收；默认包含605秒观察')
    parser.add_argument('--short',action='store_true',help='仅定向回归，不代替跨600秒证据')
    args=parser.parse_args()
    raise SystemExit(main(0 if args.short else 605))
