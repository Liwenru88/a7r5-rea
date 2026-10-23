#!/usr/bin/env python3
"""目标 sshd 在 QEMU 内回环测试；SSH 字节经已有串口，不增加主机监听或网卡。"""
import base64
import hashlib
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time

import lab
ROOT=lab.ROOT
QEMU=ROOT.parent/'a7r5-qemu'


def build_target(source, output):
    libc=ROOT/'vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    command=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu',
        '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-nostdlib','-fno-stack-protector','-fno-builtin',
        '-O2','-Wall','-Wextra','-Werror','-Wl,--no-undefined','-Wl,-e,_start',
        '-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1',str(ROOT/'src/start.S'),str(source),str(libc),'-o',str(output)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=60)
    if result.returncode: raise RuntimeError(result.stderr)
    return dict(command=command,sha256=lab.digest(output),bytes=output.stat().st_size)


def put(vm,path,data,mode='600'):
    vm.command('umask 077; : > '+shlex.quote(path))
    # 固件 BusyBox 不含 base64；短行八进制 printf 不依赖额外 applet。
    for i in range(0,len(data),48):
        encoded=''.join('\\%03o'%b for b in data[i:i+48])
        vm.command('printf '+shlex.quote(encoded)+' >> '+shlex.quote(path))
    vm.command('/bin/busybox chmod '+mode+' '+shlex.quote(path))


class SerialSocket:
    def __init__(self,vm,offset): self.vm=vm; self.offset=offset; self.timeout=10; self.closed=False
    @property
    def _closed(self): return self.closed
    def settimeout(self,value): self.timeout=value
    def gettimeout(self): return self.timeout
    def send(self,data):
        if self.closed: return 0
        self.vm.process.stdin.write(data); self.vm.process.stdin.flush(); return len(data)
    def recv(self,size):
        deadline=time.monotonic()+(self.timeout or 10)
        while time.monotonic()<deadline:
            with self.vm.console.open('rb') as f: f.seek(self.offset); data=f.read(size)
            if data: self.offset+=len(data); return data
            if self.closed or self.vm.process.poll() is not None: return b''
            time.sleep(.005)
        raise socket.timeout('模拟串口读取超时')
    def close(self): self.closed=True
    def getpeername(self): return ('qemu-loopback-via-serial',2222)


def connection(vm,paramiko,key,host_key,expect_auth=True):
    start=vm.console.stat().st_size
    vm.ssh_relay_active=True
    vm.process.stdin.write(b"/bin/busybox stty raw -echo; /simulation/ssh-relay; /bin/busybox stty sane; printf '\\nA7R5_RELAY_EXIT\\n'\n");vm.process.stdin.flush()
    marker=b'A7R5_RELAY_READY\n'; deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        raw=vm.console.read_bytes()[start:]
        if marker in raw: break
        time.sleep(.02)
    else: raise TimeoutError('客体回环中继没有就绪')
    offset=start+raw.index(marker)+len(marker)
    transport=paramiko.Transport(SerialSocket(vm,offset)); transport.banner_timeout=8; transport.auth_timeout=8
    output=b''; authenticated=False
    try:
        transport.start_client(timeout=10)
        if transport.get_remote_server_key().asbytes()!=host_key:
            raise ValueError('SSH主机指纹不符')
        try: transport.auth_publickey('root',key)
        except paramiko.AuthenticationException:
            if expect_auth: raise
        authenticated=transport.is_authenticated()
        if expect_auth:
            channel=transport.open_session(timeout=8);channel.settimeout(8)
            channel.exec_command('id')
            while True:
                part=channel.recv(4096)
                if not part: break
                output+=part
            status=channel.recv_exit_status()
            if status!=0 or not __import__('re').search(rb'^Uid:\s+0\s+0\s+0\s+0\s*$',output,__import__('re').M):
                raise ValueError('固定命令没有返回root身份：'+repr(output))
            channel.close()
        elif authenticated: raise ValueError('错误公钥被接受')
    finally:
        # 串口适配器没有TCP FIN，先发送协议断开，避免只停客户端线程留下连接。
        if transport.is_active():
            message=paramiko.Message()
            message.add_byte(paramiko.common.cMSG_DISCONNECT)
            message.add_int(11);message.add_string('offline test complete');message.add_string('')
            transport._send_user_message(message)
        transport.close()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if b'\nA7R5_RELAY_EXIT' in vm.console.read_bytes()[offset:]:
                vm.ssh_relay_active=False
                break
            time.sleep(.02)
        else: raise TimeoutError('SSH会话没有结束并归还串口')
    return dict(authenticated=authenticated,output=output.decode(errors='replace'))


def main():
    # 复用已安装的 SSH 技能依赖，仅在本次 Python 进程加入搜索路径。
    candidates=list((Path.home()/'.codex/skills/ssh-skill/.venv/lib').glob('python*/site-packages'))
    sys.path.extend(str(p) for p in candidates)
    import paramiko
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
    sys.path.insert(0,str(QEMU/'tools'))
    from native_vm import NativeVM
    from runtime_manifest import verified_inputs
    inputs=verified_inputs()
    output=Path(tempfile.mkdtemp(prefix='qemu-',dir=ROOT/'verification'))
    builds={name:build_target(ROOT/'src'/source,output/name) for name,source in [('ssh-supervisor','supervisor.c'),('ssh-relay','relay.c')]}
    result=dict(camera_io=False,original_images_accessed=False,host_network=False,
        guest_network='loopback only; existing -nic none unchanged',default_runtime_modified=False,
        builds=builds,input_sha256={k:lab.digest(v) for k,v in inputs.items()},status='failed')
    import vm_session
    vm_session.RUNS=output
    vm=NativeVM('ssh',capid=True,boot_services=True)
    try:
        vm.start()
        (output/'busybox-applets.txt').write_bytes(vm.command('/bin/busybox --list'))
        vm.command('mount -t tmpfs tmpfs /etc; mount -t tmpfs -o mode=0755 tmpfs /tmp_network; mkdir -p /var/empty /var/run/sshd /dev/pts /root /simulation /tmp/jiritsu; chmod 755 /var/empty /var/run/sshd /root; mount -t devpts devpts /dev/pts')
        vm.command("printf 'root:*:0:0:root:/root:/bin/sh\\nsshd:*:77:77:sshd:/var/empty:/bin/false\\n' > /etc/passwd; printf 'root:x:0:\\nsshd:x:77:\\n' > /etc/group; printf 'passwd: files\\ngroup: files\\nshadow: files\\n' > /etc/nsswitch.conf")
        for name in builds: put(vm,'/simulation/'+name,(output/name).read_bytes(),'700')
        run='a7'*16; d='/tmp_network/a7r5-ssh-'+run
        private=ed25519.Ed25519PrivateKey.generate()
        public=private.public_key().public_bytes(serialization.Encoding.OpenSSH,serialization.PublicFormat.OpenSSH).decode()
        # 测试客户端私钥仅保存在主机内存，不写入客体或材料包。
        import io
        private_pem=private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.OpenSSH,serialization.NoEncryption()).decode()
        key=paramiko.Ed25519Key.from_private_key(io.StringIO(private_pem))
        wrong=paramiko.ECDSAKey.generate()
        sup='/tmp/jiritsu/a7r5-'+run+'.supervisor'
        put(vm,sup,(output/'ssh-supervisor').read_bytes(),'700')
        script=lab.smoke_script(run,'127.0.0.1',public,builds['ssh-supervisor']['sha256'],30)
        (output/'tested-smoke-script.sh').write_text(script)
        put(vm,'/simulation/prepare-ssh-smoke.sh',script.encode(),'700')
        vm.command('/bin/sh /simulation/prepare-ssh-smoke.sh > /tmp_network/ssh-supervisor-test.log 2>&1 & echo SSH_TEST_JOB=$!')
        setup=vm.command('sleep 2; cat /tmp_network/ssh-supervisor-test.log; cat /proc/net/tcp')
        if b'SUPERVISOR_SPAWNED' not in setup: raise ValueError('受限候选脚本没有启动监督器')
        result['target_sshd_config_test']=True
        hostpub=vm.command('cat '+d+'/host_ecdsa.pub').decode(errors='replace')
        match=__import__('re').search(r'ecdsa-sha2-nistp256 ([A-Za-z0-9+/=]+)',hostpub)
        if not match: raise ValueError('无法从客体串口取得本次主机公钥')
        hostkey=base64.b64decode(match[1])
        result['fixed_root_command']=connection(vm,paramiko,key,hostkey)
        result['wrong_key']=connection(vm,paramiko,wrong,hostkey,expect_auth=False)
        # 等待有限寿命结束，不通过名称或外部PID杀进程。
        stopped=vm.command('sleep 30; cat /tmp_network/ssh-supervisor-test.log; if /bin/busybox grep -q "0100007F:08AE .* 0A " /proc/net/tcp; then false; fi',timeout=45)
        if b'SUPERVISOR_STOPPED_NO_OWNED_CHILDREN' not in stopped: raise ValueError('没有完整监督停止回执')
        result['bounded_stop']=True
        # 同一固定预检载荷在客体RAM实际触发，验证动态加载与空间查询。
        prepared=output/'preflight-target-test'; operation=lab.build_preflight(prepared)
        prefix='/tmp/jiritsu/a7r5-'+operation['run_id']
        put(vm,prefix+'.so',(prepared/'preflight.arm64.so').read_bytes(),'700')
        put(vm,'/etc/ld.so.preload',(prefix+'.so\n').encode())
        vm.command("/bin/sh -c '/bin/date -s 070421422017.26'")
        state=vm.command('sleep 1; cat '+prefix+'.state; cat '+prefix+'.output')
        (output/'target-preflight-output.txt').write_bytes(state)
        clean=state.replace(b'\r',b'')
        import re
        begin=clean.index(('A7R5_SSH_PREFLIGHT_BEGIN '+operation['run_id']+'\n').encode())
        end=clean.index(('A7R5_SSH_PREFLIGHT_COMPLETE '+operation['run_id']+'\n').encode(),begin)+len('A7R5_SSH_PREFLIGHT_COMPLETE '+operation['run_id']+'\n')
        result['target_preflight']=lab.parse_preflight(clean[begin:end],operation['run_id'])
        if not re.search(('A7R5-ROOT-1 '+operation['run_id']+' DONE 0 uid=0 euid=0 bytes=').encode(),clean):
            raise ValueError('实际预检载荷没有DONE0回执')
        result['statvfs_query_verified']=b'FS_SPACE /tmp_network available_bytes=' in clean
        neutral=vm.command('/bin/busybox wc -c /etc/ld.so.preload; /bin/busybox md5sum /etc/ld.so.preload')
        if hashlib.md5(b'\n'*512).hexdigest().encode() not in neutral: raise ValueError('客体预加载未中和')
        result['target_preload_neutral']=True
        result['status']='passed'
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        if 'd' in locals() and not getattr(vm,'ssh_relay_active',False):
            try: (output/'server-diagnostic.txt').write_bytes(vm.command('cat /tmp_network/ssh-supervisor-test.log',timeout=5))
            except Exception as diagnostic_error: result['diagnostic_error']=str(diagnostic_error)
        elif getattr(vm,'ssh_relay_active',False):
            result['diagnostic_withheld']='串口仍属于SSH中继，不再发送shell命令'
        raise
    finally:
        result['cleanup']=vm.close()
        result['console_sha256']=lab.digest(vm.console)
        result['run']=str(vm.out)
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
