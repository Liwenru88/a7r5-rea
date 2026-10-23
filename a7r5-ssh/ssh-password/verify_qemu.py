"""原厂sshd密码认证集成；仅QEMU RAM和串口，无NIC/相机/SD直通。"""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from unittest.mock import patch

import build
import credentials
import operation as op
import verify_reference
import isolation_qemu
import qemu_verify
op.dependencies()
import paramiko
sys.path.insert(0,str(build.LAB.parent/'a7r5-qemu/tools'))
import vm_session
from native_vm import NativeVM
from runtime_manifest import verified_inputs


def write_secret(path,password):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='ascii') as f:f.write(password+'\n')


def main():
    out=Path(tempfile.mkdtemp(prefix='password-qemu-',dir=build.ROOT/'verification'))
    vm_session.RUNS=out
    vm=NativeVM('password-ssh',capid=True,boot_services=True)
    before={k:build.sha(v) for k,v in verified_inputs().items()}
    password,hashed=credentials.generate()
    candidate=build.build(out/'candidate',hashed,'0.0.0.0',45,qemu_only=True)
    negative=build.build(out/'shadow-candidate',hashed,'0.0.0.0',20,qemu_only=True)
    result=dict(status='failed',camera_io=False,host_tcp_connections=0,guest_nic='none',candidate=candidate,
                sources=op.sources(),note='串口替换socket；真实Wi-Fi/TCP及600秒寿命未验证')
    ram=candidate['ram_directory']
    real_transport=paramiko.Transport
    try:
        vm.start()
        vm.command('mount -t tmpfs -o mode=0755 tmpfs /etc; mount -t tmpfs -o mode=0755 tmpfs /var; mount -t tmpfs -o mode=1777 tmpfs /tmp_network; mkdir -p /etc/ssh /tmp/jiritsu /simulation /root; test ! -e /etc/shadow')
        fixture=build.LAB/'analysis/network-20261020-v1'
        provenance=json.loads((fixture/'sources.json').read_text())
        originals={'/etc/passwd':verify_reference.original_passwd()}
        for name in ('original/etc/nsswitch.conf','original/etc/ssh/sshd_config'):
            raw=(fixture/name).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=provenance['files'][name]['sha256']:raise ValueError('原件摘要变化')
            originals['/etc/'+name.removeprefix('original/etc/')]=raw
        for path,raw in originals.items():isolation_qemu.put(vm,path,raw)
        for name,value in (('helper',candidate),('shadow-helper',negative)):
            isolation_qemu.put(vm,'/simulation/'+name,Path(value['binary']).read_bytes(),'700')
        # 仅在QEMU新建的/etc tmpfs注入假shadow，验证不会覆盖或忽略未知认证来源。
        isolation_qemu.put(vm,'/etc/shadow',b'root:!:0:0:99999:7:::\n')
        rejected=vm.command('/simulation/shadow-helper --launch; r=$?; echo SHADOW_EXIT=$r; test "$r" = 68; test ! -d '+negative['ram_directory'])
        (out/'shadow-rejected.txt').write_bytes(rejected)
        if b'SHADOW_EXIT=68' not in rejected or b' READY' in rejected:raise ValueError('未知shadow未被拒绝')
        result['existing_shadow_rejected']=True
        vm.command('/bin/busybox rm /etc/shadow; test ! -e /etc/shadow')
        relay=build.LAB/'verification/qemu-jx_1vzc1/ssh-relay'
        if build.sha(relay)!='b2e94f220556e3bdc68e5ad3ea47a6386fe6cc4a83d9844e3713b869806d6dea':raise ValueError('中继摘要变化')
        isolation_qemu.put(vm,'/simulation/ssh-relay',relay.read_bytes(),'700')
        launch=vm.command('/usr/bin/openssl dgst -sha256 /simulation/helper; /simulation/helper --launch; cat '+ram+'/host-public-key')
        (out/'launch.txt').write_bytes(launch)
        if candidate['binary_sha256'].encode() not in launch or ('A7R5_PRIVATE_LAUNCH '+candidate['run_id']+' READY').encode() not in launch:raise ValueError('密码候选未READY')
        match=re.search(rb'ecdsa-sha2-nistp256 ([A-Za-z0-9+/=]+)(?: [^\r\n]*)?',launch)
        if not match:raise ValueError('没有可信主机公钥')
        trusted=b'ecdsa-sha2-nistp256 '+match[1]+b'\n'
        host_key=base64.b64decode(match[1],validate=True)

        @contextmanager
        def relay_connection():
            offset=vm.console.stat().st_size;vm.ssh_relay_active=True
            vm.process.stdin.write(b"/bin/busybox stty raw -echo; /simulation/ssh-relay; /bin/busybox stty sane; printf '\\nA7R5_RELAY_EXIT\\n'\n");vm.process.stdin.flush()
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                raw=vm.console.read_bytes()[offset:]
                if b'A7R5_RELAY_READY\n' in raw:break
                time.sleep(.02)
            else:raise TimeoutError('串口中继未就绪')
            serial_offset=offset+raw.index(b'A7R5_RELAY_READY\n')+len(b'A7R5_RELAY_READY\n')
            connections=[]
            class Adapter(qemu_verify.SerialSocket):
                def connect(self,address):
                    if address!=('10.10.10.177',2222):raise ValueError('客户端改变目标')
                    connections.append(address)
                def shutdown(self,how):self.closed=True
            class SerialTransport(real_transport):
                def close(self):
                    # 串口无TCP FIN，以下只补足测试适配器关闭语义。
                    if self.is_active():
                        message=paramiko.Message();message.add_byte(paramiko.common.cMSG_DISCONNECT)
                        message.add_int(11);message.add_string('offline password test');message.add_string('')
                        self._send_user_message(message)
                    super().close()
            adapter=Adapter(vm,serial_offset)
            try:
                with patch('socket.socket',return_value=adapter),patch.object(paramiko,'Transport',SerialTransport):
                    yield adapter,SerialTransport,connections
            finally:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    if b'\nA7R5_RELAY_EXIT' in vm.console.read_bytes()[offset:]:
                        vm.ssh_relay_active=False;break
                    time.sleep(.02)
                else:raise TimeoutError('串口未归还')

        # 正确/错误密码走同一个准备用于Mac的客户端，不打印或记录口令。
        for name,secret in (('wrong-password','W'*32),('correct-password',password)):
            evidence=out/name;evidence.mkdir(mode=0o700)
            write_secret(evidence/'client-password',secret)
            (evidence/'host-public-key').write_bytes(trusted)
            report=dict(host_public_sha256=hashlib.sha256(trusted).hexdigest())
            value=dict(target_ip=op.TARGET_IP,port=2222,ssh_command=op.FIXED_COMMAND,directory=str(evidence))
            with relay_connection() as (_,_,connections):
                try:op.client_once(value,evidence,report)
                except paramiko.AuthenticationException:
                    if name=='correct-password':raise
                    report['expected_rejection']=True
            if len(connections)!=1:raise ValueError('连接次数不为1')
            if name=='correct-password' and not report.get('ssh_root_login_verified'):raise ValueError('密码root固定命令未通过')
            if name=='wrong-password' and not report.get('expected_rejection'):raise ValueError('错误密码被接受')
            result[name]=report
        print('正确密码root命令与错误密码拒绝通过；继续核对空密码/公钥拒绝和到期清理',flush=True)
        for name in ('empty-password','public-key'):
            with relay_connection() as (adapter,transport_class,_):
                transport=transport_class(adapter);transport.banner_timeout=8;transport.auth_timeout=8
                try:
                    transport.start_client(timeout=8)
                    if transport.get_remote_server_key().asbytes()!=host_key:raise ValueError('主机公钥不符')
                    try:
                        if name=='empty-password':transport.auth_password('root','',fallback=False)
                        else:transport.auth_publickey('root',paramiko.ECDSAKey.generate())
                    except paramiko.AuthenticationException:pass
                    if transport.is_authenticated():raise ValueError('禁止的认证方式被接受')
                    result[name+'_rejected']=True
                finally:transport.close()
        final=vm.command('sleep 48; cat '+ram+'/result '+ram+'/child-result; /usr/bin/openssl dgst -sha256 /etc/passwd /etc/nsswitch.conf /etc/ssh/sshd_config; test ! -e /etc/shadow; test ! -e /var/run/a7r5-ssh-'+candidate['run_id'],timeout=58)
        (out/'final.txt').write_bytes(final);clean=final.replace(b'\r',b'')
        if not re.search(rb'A7R5_PRIVATE_RESULT '+candidate['run_id'].encode()+rb' code=0 parent_unchanged=1 child_tree_reaped=1 child_terminal_seen=1 listener_absent=1\n',clean):raise ValueError('最终父视图/后代/监听核验失败')
        if b'PRIVATE_RESULT code=0 errno=0 sshd_attempted=1 listener_observed=1 children_reaped=1 private_account_changed=1 local_banner_verified=1\n' not in clean:raise ValueError('子清理终态失败')
        for raw in originals.values():
            if hashlib.sha256(raw).hexdigest().encode() not in clean:raise ValueError('原件变化')
        result.update(status='passed',parent_originals_unchanged=True,cleanup_receipt_verified=True)
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc).replace(password,'[REDACTED]')
        raise
    finally:
        result['cleanup']=vm.close()
        result['runtime_inputs_unchanged']=before=={k:build.sha(v) for k,v in verified_inputs().items()}
        # 明文仅存在指定0600文件，不能出现在串口、日志、二进制或JSON回执中。
        leaks=[str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name!='client-password' and password.encode() in p.read_bytes()]
        result['plaintext_password_leaks']=leaks
        if leaks:result['status']='failed'
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(dict(output=str(out),status=result['status'],error=result.get('error'),cleanup=result['cleanup']),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
