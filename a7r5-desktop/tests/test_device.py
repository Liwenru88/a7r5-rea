from collections import deque
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
from types import ModuleType, SimpleNamespace
import pytest
import common
import device
import host
import ssh_operation
from transport import HEADER
from system_dump import session


class Wire:
    """模拟文件服务和分块边界，执行真正的Channel与Operation。"""
    def __init__(self, operation, fault):
        self.op=operation;self.start=operation.start;self.fault=fault;self.queue=deque();self.files={};self.selected=None
        self.puts=[];self.triggers=0;self.heartbeats=0;self.sequences=[]
        raw=b'\0\0\0\x13ecdsa-sha2-nistp256'+b'P'*81
        self.public=b'ecdsa-sha2-nistp256 '+base64.b64encode(raw)+b'\n'
        self.banner=b'SSH-2.0-fixture\r\n'
    def contents(self,path):
        s=self.start;run=s.run
        if path=='/version.txt':return b'fixture-version'
        if path=='/usr/lib/libJiritsu.so':return b'L'*233416
        if path=='/etc/ld.so.preload':return b'\n'*512
        if self.triggers:
            if path==s.prefix+'.claim':return (s.materials/'ticket.bin').read_bytes()
            if path==s.ram+'/ready':return (f'A7R5_PRIVATE_READY {"0"*32 if self.fault=="nonce" else run} parent=10 child=11 uid=0 euid=0 ttl=0 parent_unchanged=1 private_account_changed=1 parent_ns=mnt:[1] child_ns=mnt:[2] host_public_sha={hashlib.sha256(self.public).hexdigest()}\n').encode()
            if path==s.ram+'/host-public-key':return b'bad' if self.fault=='public' else self.public
            if path==s.ram+'/hostkey-check':return b'A7R5_RAM_GENERATED_HOSTKEY verified=1 mode=600 tmpfs=1 private_key_logged=0\n'
            if path==s.ram+'/banner':return self.banner
            if path==s.ram+'/started':return f'A7R5_WILDCARD_STARTED {run} pid=12 bind=0.0.0.0:2222 listener_observed=1 banner_sha={hashlib.sha256(self.banner).hexdigest()}\n'.encode()
            if path==s.ram+'/heartbeat':
                self.heartbeats+=1
                return f'A7R5_PRIVATE_ALIVE {run} parent=10 child=11 ttl=0 elapsed_ms={1 if self.fault=="heartbeat" else self.heartbeats} parent_unchanged=1 changes_observed=0\n'.encode()
        value=self.files.get(path)
        if value is not None and self.fault=='upload-readback' and path.endswith('.service'):return b'bad'
        return value
    def write(self,packet):
        assert not self.queue
        self.op.guard_packet(packet)
        size,function,sequence,*meta=HEADER.unpack_from(packet);self.sequences.append(sequence)
        body=packet[12:];assert size==len(body) and function==64 and not any(meta)
        group,command=struct.unpack_from('<HH',body);assert group==0x1001
        code=0;data=b''
        if command==15:self.selected=body[5:-1].decode().replace('/tmp/jiritsu/../..','',1)
        elif command==16:
            self.puts.append(self.selected)
            if self.fault=='upload-open' and self.selected.endswith('.service'):
                code=0x10000008
            else:
                self.files[self.selected]=body[7:]
                if self.selected=='/tmp/jiritsu/libJit.so':self.triggers+=1
        elif command==17:
            data=self.contents(self.selected)
            if data is None:code=0x10000006;data=b''
        else:raise AssertionError('未授权指令')
        raw=struct.pack('<I',code)+data
        self.queue.append(HEADER.pack(len(raw),64,sequence+int(self.fault=='sequence'),0,0,0,0))
        for offset in range(0,len(raw),32768):
            block=raw[offset:offset+32768];self.queue.append(block)
            if len(block)%512==0 and self.fault!='boundary':self.queue.append(b'')
        return len(packet)
    def read(self,size):
        if not self.queue:raise TimeoutError('模拟传输截断')
        block=self.queue.popleft();take=size if size==12 else min(size,503)
        if block[take:]:self.queue.appendleft(block[take:])
        return block[:take]


def install_session(monkeypatch,op,camera):
    import usb.core,usb.util,usb.backend.libusb1
    controls=[];auth=[0]
    class Interface(list):pass
    class USB:
        idVendor=0x054c;bus=0x14;port_numbers=[1];iProduct=1
        def __init__(self,pid):self.idProduct=pid
        def get_active_configuration(self):
            row=op.start.config['interfaces']['interface-1.json' if self.idProduct==0x0e0a else 'interface-2.json']
            interface=Interface([SimpleNamespace(bEndpointAddress=e['address'],bmAttributes=e['attributes'],wMaxPacketSize=e['max_packet'],bInterval=e['interval'])for e in row['endpoints']])
            for attr,key in [('bInterfaceNumber','number'),('bAlternateSetting','alternate'),('bInterfaceClass','interface_class'),('bInterfaceSubClass','subclass'),('bInterfaceProtocol','protocol')]:setattr(interface,attr,row[key])
            return {(0,0):interface}
        def write(self,ep,data,timeout):assert ep==2;return camera.write(data)
        def read(self,ep,n,timeout):assert ep==129;return camera.read(n)
        def ctrl_transfer(self,*a,**k):controls.append(a)
    ordinary=USB(0x0e0a);service=USB(0x0336)
    class Auth:
        def __init__(self,driver):self.driver=driver
        def start(self):self.driver.vendorRequestOut(*session.START)
        def authenticate(self):auth[0]+=1
    sony=ModuleType('pmca.usb.sony');sony.SonySenserAuthDevice=Auth
    monkeypatch.setitem(sys.modules,'pmca.usb.sony',sony)
    monkeypatch.setattr(usb.core,'find',lambda **k:[ordinary if auth[0]==0 else service])
    monkeypatch.setattr(usb.backend.libusb1,'get_backend',lambda **k:object())
    monkeypatch.setattr(usb.util,'get_string',lambda *a:'ILCE-7RM5')
    monkeypatch.setattr(usb.util,'dispose_resources',lambda *a:None)
    monkeypatch.setattr(usb.util,'release_interface',lambda *a:None)
    monkeypatch.setattr(session,'claim_interface',lambda *a,**k:False)
    monkeypatch.setattr(session,'unmount_camera',lambda *a:None)
    return controls,auth


@pytest.mark.parametrize('fault',[None,'upload-readback','sequence','boundary','nonce','public','heartbeat'])
def test_combined_ssh_uses_real_session_and_one_channel(tmp_path,baseline,monkeypatch,fault):
    job=tmp_path.resolve();package,op=device.prepare_ssh(job,'1'*32,baseline,common.load(common.ROOT/'templates.json')['hash_marker'])
    cfg=common.load(package/'config.json');cfg.update(version_sha256=hashlib.sha256(b'fixture-version').hexdigest(),loader_sha256=hashlib.sha256(b'L'*233416).hexdigest())
    (package/'config.json').write_text(json.dumps(cfg));op=device.JoinedSSH(package);op.output=job/'session'
    camera=Wire(op,fault);controls,auth=install_session(monkeypatch,op,camera)
    monkeypatch.setattr(ssh_operation.time,'sleep',lambda seconds:None)
    report=session.run_session(op.output,'libusb',_operation=op)
    assert auth[0]==2
    stopped=sum(c[1:4]==session.STOP for c in controls)
    assert stopped==int(fault is None)==report['service_stop_attempts']
    assert camera.triggers<=1 and len(camera.puts)<=5
    if fault is None:
        assert op.safe_to_stop and report['service_ready'] and len(camera.puts)==5 and camera.triggers==1
        assert camera.sequences==list(range(1,len(camera.sequences)+1))
        assert op.load.interfaces_seen==op.start.interfaces_seen==2
        assert not camera.queue
    else:
        assert not op.safe_to_stop and report['failure']
        if fault in ('upload-readback','sequence','boundary'):assert camera.triggers==0


def test_ssh_open_failure_preserves_actual_upload_stage_and_never_starts_or_stops(tmp_path,baseline,monkeypatch):
    package,_=device.prepare_ssh(tmp_path,'1'*32,baseline,common.load(common.ROOT/'templates.json')['hash_marker'])
    cfg=common.load(package/'config.json')
    cfg.update(version_sha256=hashlib.sha256(b'fixture-version').hexdigest(),loader_sha256=hashlib.sha256(b'L'*233416).hexdigest())
    (package/'config.json').write_text(json.dumps(cfg))
    op=device.JoinedSSH(package);op.output=tmp_path/'session'
    camera=Wire(op,'upload-open');controls,_=install_session(monkeypatch,op,camera)
    report=session.run_session(op.output,'libusb',_operation=op)
    assert report['camera_file_write_commands_sent'] is True
    assert report['ssh_start_state']=='not_attempted'
    assert report['upload_failure']==dict(stage='load-once',path=op.load.prefix+'.service',
        action='write',result='0x10000008',system_errno=None)
    assert len(camera.puts)==1 and camera.triggers==0
    assert report['fixed_writes_attempted']==1 and report['trigger_attempts']==0
    assert report['service_stop_attempts']==0 and not any(c[1:4]==session.STOP for c in controls)
    assert not op.safe_to_stop and not (op.output/'start-phase.json').exists()
    assert '0x10000008' in report['failure']


def test_update_rejects_simulated_and_modified_backup(tmp_path,baseline):
    for index,change in enumerate((dict(simulation=True),dict(backup_sha256='0'*64),dict(task_complete=False))):
        record=dict(kind='backup',task_complete=True,device_IO=True,simulation=False,backup_sha256=common.SOURCE_SHA,**{})
        record.update(change);p=tmp_path/f'{index}.json';common.save(p,record)
        with pytest.raises(ValueError):device.prepare_update(tmp_path,'2'*32,baseline,p)


def test_current_port_and_host_recovery_are_strict(baseline):
    assert host.physical_port(0x14100000)==(0x14,[1])
    for location in (0,0x14010000,0x14100001):
        with pytest.raises(ValueError):host.physical_port(location)
    tick=[0];proof=host.observe(baseline,lambda *a,**k:baseline,clock=lambda:tick[0],sleep=lambda n:tick.__setitem__(0,tick[0]+n))
    assert proof['recovered'] and len(proof['observations'])==2 and proof['camera_protocol_requests']==0
    bad=dict(baseline,media=[[True,100001]])
    with pytest.raises(ValueError):host.observe(baseline,lambda *a,**k:bad)


def test_no_msc_never_prepares_or_enters_usb(tmp_path,monkeypatch):
    fake=SimpleNamespace(snapshot=lambda *a:dict(kind='absent'))
    with pytest.raises(ValueError,match='未开始'):device.run(dict(run_id='3'*32,kind='backup'),tmp_path,session_module=SimpleNamespace(),host_module=fake)
    assert not (tmp_path/'ATTEMPT_LOCK').exists()


@pytest.mark.parametrize('fault',[None,'missing-native','missing-host','wrong-format','incomplete'])
def test_force_sector_completion_requires_both_native_and_host_evidence(tmp_path,baseline,ram_runtime,fault):
    observations=[]
    def simulated(output,transport,_operation):
        report=dict(protocol_gate_passed=True,preload_unchanged=True,fixed_writes_attempted=2,
            trigger_attempts=1,service_stop_attempts=1,service_stop_result='returned',
            native_write_complete=True,native_full_readback_verified=True,native_reopened_readback_verified=True,
            planned_sector_readback_verified=True,complete_partition_readback_verified=False,
            trust_readback_format='planned-sectors-v2',trust_readback_scope='planned-sectors',
            trust_readback_completed_chunks=9,trust_readback_total_chunks=9,trust_readback_bytes=132096,patch_sectors=258)
        if fault=='missing-native':report.pop('native_full_readback_verified')
        if fault=='missing-host':report['planned_sector_readback_verified']=False
        if fault=='wrong-format':report['trust_readback_format']='full-16k-v1'
        if fault=='incomplete':report['trust_readback_completed_chunks']=8
        return report
    def observe(*args):observations.append(1);return dict(recovered=True,observations=[baseline,baseline])
    result=device.run(dict(kind='update',run_id='7'*32,force_install=True),tmp_path.resolve(),
        session_module=SimpleNamespace(__name__='simulation',run_session=simulated),
        host_module=SimpleNamespace(snapshot=lambda *a:baseline,observe=observe))
    assert result['task_complete'] is (fault is None) and bool(observations) is (fault is None)
    assert result['report']['complete_partition_readback_verified'] is False


def test_STOP_transport_error_never_claims_complete_or_allows_replug(tmp_path,baseline):
    def simulated(output,transport,_operation):
        return dict(protocol_gate_passed=True,preload_unchanged=True,fixed_writes_attempted=5,
                    trigger_attempts=1,service_stop_attempts=1,service_stop_result='error',
                    service_stop_error='退出请求超时',service_ready=True)
    fake=SimpleNamespace(__name__='simulation',run_session=simulated)
    observed=SimpleNamespace(snapshot=lambda *args:baseline)
    request=dict(run_id='4'*32,kind='ssh_start',password_hash=common.load(common.ROOT/'templates.json')['hash_marker'])
    value=device.run(request,tmp_path.resolve(),session_module=fake,host_module=observed)
    assert not value['task_complete'] and not value['can_replug'] and value['simulation']
    assert value['error']=='退出请求超时' and not value['USB_recovered']


@pytest.mark.parametrize('outcome,recovered,payload_ok', [
    ('stalled',True,True), ('stalled',False,True),
    ('error',True,True), ('stalled',True,False),
])
def test_backup_stop_stall_requires_verified_payload_and_stable_msc(tmp_path,baseline,outcome,recovered,payload_ok,ram_runtime):
    image=b'x'*common.PARTITION_BYTES
    observed=[]
    def simulated(output,transport,_operation):
        output.mkdir()
        (output/'partition1.logical.bin').write_bytes(image)
        return dict(protocol_gate_passed=payload_ok,preload_unchanged=True,fixed_writes_attempted=4,
                    trigger_attempts=2,service_stop_attempts=1,service_stop_result=outcome,
                    service_stop_error='模拟STOP错误',service_stop_backend_error_code=-9 if outcome=='stalled' else -7,
                    capture_verified=payload_ok,backup_persisted=payload_ok,capture_cleanup_verified=payload_ok,
                    capture_sha256=hashlib.sha256(image).hexdigest(),
                    expected_preload_hex=(b'\n'*512).hex())
    def observe(before,take):
        observed.append(before)
        # MSC观察器本身已有端口、媒体、驱动的独立测试，此处核对调用门槛。
        return dict(recovered=recovered,camera_protocol_requests=0,observations=[baseline,baseline])
    result=device.run(dict(run_id='5'*32,kind='backup'),tmp_path.resolve(),
                      session_module=SimpleNamespace(__name__='simulation',run_session=simulated),
                      host_module=SimpleNamespace(snapshot=lambda *args:baseline,observe=observe))
    assert len(observed)==int(outcome=='stalled' and payload_ok)
    assert result['task_complete'] is (outcome=='stalled' and recovered and payload_ok)
    assert result['USB_recovered'] is (outcome=='stalled' and recovered and payload_ok)
    assert result['report']['service_stop_attempts']==1
    assert result['report']['service_stop_error']=='模拟STOP错误'
    if payload_ok:
        assert result['backup_complete'] and result['backup_sha256']==hashlib.sha256(image).hexdigest()
    else:
        assert 'backup_relative' not in result


def test_real_stop_stall_preserves_backend_error_and_never_repeats(tmp_path,baseline,monkeypatch):
    import usb.core
    package,op=device.prepare_ssh(tmp_path.resolve(),'6'*32,baseline,
                                 common.load(common.ROOT/'templates.json')['hash_marker'])
    cfg=common.load(package/'config.json')
    cfg.update(version_sha256=hashlib.sha256(b'fixture-version').hexdigest(),
               loader_sha256=hashlib.sha256(b'L'*233416).hexdigest())
    (package/'config.json').write_text(json.dumps(cfg));op=device.JoinedSSH(package)
    camera=Wire(op,None);controls,auth=install_session(monkeypatch,op,camera)
    memory_usb=type(usb.core.find()[0]);original=memory_usb.ctrl_transfer
    def control(self,*args,**kwargs):
        original(self,*args,**kwargs)
        if args[1:4]==session.STOP:raise usb.core.USBError('模拟STOPSTALL',-9,32)
    monkeypatch.setattr(memory_usb,'ctrl_transfer',control)
    monkeypatch.setattr(ssh_operation.time,'sleep',lambda seconds:None)
    op.output=tmp_path/'session'
    report=session.run_session(tmp_path/'session','libusb',_operation=op)
    assert report['protocol_gate_passed'] and not report.get('failure')
    assert report['service_stop_attempts']==1 and sum(c[1:4]==session.STOP for c in controls)==1
    assert report['service_stop_result']=='stalled' and report['service_stop_backend_error_code']==-9
    assert '模拟STOPSTALL' in report['service_stop_error']


@pytest.mark.parametrize('failure_stage,cleanup_fails', [(1,False),(1,True),(2,False)])
def test_real_claim_failure_keeps_phase_and_safe_recovery_boundary(tmp_path, baseline, monkeypatch, failure_stage, cleanup_fails):
    import usb.core
    import usb.util
    from system_dump import usb_adapter
    from policy import pre_service_failure
    seed = tmp_path/'seed';seed.mkdir()
    password_hash = common.load(common.ROOT/'templates.json')['hash_marker']
    _, op = device.prepare_ssh(seed, '9'*32, baseline, password_hash)
    camera = Wire(op, None)
    controls, auth = install_session(monkeypatch, op, camera)
    memory_usb = type(usb.core.find()[0])
    monkeypatch.setattr(memory_usb, 'is_kernel_driver_active', lambda *a: True, raising=False)
    monkeypatch.setattr(memory_usb, 'detach_kernel_driver', lambda *a: None, raising=False)
    def attach(*args):
        if cleanup_fails:
            raise RuntimeError('模拟驱动回收错误')
    monkeypatch.setattr(memory_usb, 'attach_kernel_driver', attach, raising=False)
    claims = []
    def claim(usb_device, interface):
        claims.append(usb_device.idProduct)
        if auth[0] == failure_stage-1:
            raise usb.core.USBError('模拟接管失败', -99)
    monkeypatch.setattr(usb.util, 'claim_interface', claim)
    monkeypatch.setattr(usb_adapter.sys, 'platform', 'darwin')
    monkeypatch.setattr(usb_adapter.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(session, 'claim_interface', usb_adapter.claim_interface)
    folder = (tmp_path/'run').resolve();folder.mkdir()
    result = device.run(dict(kind='ssh_start', run_id='9'*32, password_hash=password_hash), folder,
                        session_module=session, host_module=SimpleNamespace(snapshot=lambda *a: baseline))
    report = result['report']
    assert report['backend_error_code'] == -99 and report['failure_phase'] == 'interface_claim'
    assert 'USBError' in report['failure_traceback'] and '模拟接管失败' in result['error']
    assert not result['task_complete'] and not result['USB_recovered']
    assert not camera.puts and camera.triggers == 0 and report['service_stop_attempts'] == 0
    if failure_stage == 1:
        assert claims == [0x0e0a]*3 and not controls and auth[0] == 0
        assert report['camera_protocol_requests'] == 0 and pre_service_failure(result)
        assert result['recovery_kind'] == 'pre_service_failure' and result['can_replug']
    else:
        assert claims == [0x0e0a, 0x0336] and auth[0] == 1
        assert len(controls) == report['camera_protocol_requests'] == 1
        assert not pre_service_failure(result) and not result['can_replug']
    if cleanup_fails:
        assert 'kernel_driver_reattach_failed' in (folder/'session/events.jsonl').read_text()
