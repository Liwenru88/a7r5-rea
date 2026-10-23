"""使用独立的文件服务夹具验证可观察的任务结果，不触及USB。"""
from pathlib import Path
import hashlib
import json
import struct
import sys
import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import operation as op
import runner
from transport import Channel,FileResultError,HEADER,READ

RUN='1234abcd'*4
BASELINE=b'\n'*512
LIBRARY=b'fixed-loader-fixture'
OUTPUT=b'A7R5_LIBJIT_INFO_BEGIN\nUid: 0 0 0 0\nA7R5_LIBJIT_INFO_END\n'

def terminal(phase='DONE',code=0,uid=0,euid=0,size=None,disarmed=1,children=0,run=RUN):
    return f'A7R5-JIT-1 {run} {phase} {code} uid={uid} euid={euid} bytes={len(OUTPUT) if size is None else size} disarmed={disarmed} children={children}\n'.encode()

def bundle(path):
    (path/'materials').mkdir(parents=True)
    (path/'materials/libJit.so').write_bytes(b'fixed-payload')
    (path/'materials/ticket.bin').write_bytes(('A7R5_LIBJIT '+RUN+'\n').encode())
    config=dict(run_id=RUN,loader_bytes=len(LIBRARY),loader_sha256=hashlib.sha256(LIBRARY).hexdigest(),
                version_sha256=hashlib.sha256(b'fixed-version').hexdigest(),task_seconds=15,
                preload_baselines=[('blank',BASELINE.hex())],interfaces={},
                expected_output_begin='A7R5_LIBJIT_INFO_BEGIN\n',expected_output_end='A7R5_LIBJIT_INFO_END\n')
    (path/'config.json').write_text(json.dumps(config));return path

class Service:
    def __init__(self,driver,operation,log):
        self.operation=operation;self.writes=[];self.states=0;self.preloads=0
        self.fault=driver;self.usable=True;operation.test_service=self
    def read(self,path,limit):
        if path=='/version.txt':return b'bad' if self.fault=='version' else b'fixed-version'
        if path=='/usr/lib/libJiritsu.so':return b'bad' if self.fault=='loader' else LIBRARY
        if path=='/etc/ld.so.preload':
            self.preloads+=1
            return b'unknown' if self.fault=='baseline' or (self.fault=='preload-changed' and self.preloads==3) else BASELINE
        if path.endswith('.ticket') and self.writes:
            return b'bad' if self.fault=='ticket' else self.operation.ticket
        if path.endswith('.state') and len(self.writes)==2:
            self.states+=1
            variants={'nonce':terminal(run='ffff'*8),'uid':terminal(uid=1),'euid':terminal(euid=1),
                      'disarm':terminal(disarmed=0),'descendant':terminal(children=1),
                      'exit':terminal(code=42),'failed':terminal('FAILED',95),'timeout':terminal('TIMEOUT',93),
                      'length':terminal(size=len(OUTPUT)+1),'running':terminal('RUNNING',size=0)}
            if self.fault=='state-changed' and self.states>1:return terminal(code=2)
            return variants.get(self.fault,terminal())
        if path.endswith('.output') and len(self.writes)==2:
            return b'foreign' if self.fault=='output' else OUTPUT
        if (self.fault=='existing-library' and path.endswith('/libJit.so')) or (self.fault=='busy' and path=='/tmp/jbusy'):
            return b'foreign'
        if self.fault=='stat-other':raise FileResultError(0x10000008)
        raise FileResultError(0x10000006)
    def put(self,path,data):
        self.writes.append((path,data))
        if self.fault=='trigger-transport' and len(self.writes)==2:
            self.usable=False;raise OSError('synthetic transfer failure')

def test_completed_fixed_task_allows_one_stop_without_debug_or_preload_write(tmp_path):
    operation=op.Operation(bundle(tmp_path/'bundle'),Service);out=tmp_path/'out';out.mkdir();report={}
    operation(None,out,lambda *a,**k:None,report)
    assert operation.safe_to_stop and report['protocol_gate_passed']
    assert report['trigger_attempts']==1 and report['fixed_writes_attempted']==2
    assert not report['debug_commands_sent'] and not report['preload_written']
    assert [p for p,_ in operation.test_service.writes]==[operation.prefix+'.ticket','/tmp/jiritsu/libJit.so']
    assert (out/'shell-output.bin').read_bytes()==OUTPUT

@pytest.mark.parametrize('case',['version:0','loader:0','baseline:0','existing-library:0','busy:0','stat-other:0',
    'ticket:1','trigger-transport:2','nonce:2','uid:2','euid:2','disarm:2','descendant:2','exit:2',
    'failed:2','timeout:2','length:2','output:2','preload-changed:2','state-changed:2'])
def test_rejected_evidence_never_opens_stop_gate_or_retries(tmp_path,case):
    fault,count=case.split(':');operation=op.Operation(bundle(tmp_path/'bundle'),Service)
    out=tmp_path/'out';out.mkdir();report={}
    with pytest.raises((ValueError,RuntimeError,OSError,PermissionError)):
        operation(fault,out,lambda *a,**k:None,report)
    assert not operation.safe_to_stop and not report['protocol_gate_passed']
    assert len(operation.test_service.writes)==int(count)
    assert operation.trigger_attempts<=1

class WireDriver:
    """独立模拟线路应答，经过生产帧编码与解析器，而非替代 Channel。"""
    def __init__(self,operation,fault=None):
        self.operation=operation;self.service=Service(None,operation,lambda *a,**k:None)
        self.reply=b'';self.selected=None;self.fault=fault;self.requests=[]
    def write(self,packet):
        self.operation.guard_packet(packet);self.requests.append(packet)
        if self.fault=='short-write':return len(packet)-1
        _,_,seq,*_=HEADER.unpack_from(packet);body=packet[HEADER.size:]
        group,cmd=struct.unpack_from('<HH',body);assert group==0x1001
        code,data=0,b''
        if cmd==15:self.selected=body[5:-1].decode().replace('/tmp/jiritsu/../..','',1)
        elif cmd==17:
            try:data=self.service.read(self.selected,self.operation.reads[self.selected])
            except FileResultError as exc:code=exc.result
        elif cmd==16:self.service.put(self.selected,body[7:])
        else:raise AssertionError('禁止其他设备命令')
        content=struct.pack('<I',code)+data
        size=len(content)
        self.reply=HEADER.pack(size,0x41 if self.fault=='function' else 0x40,
                               seq+1 if self.fault=='sequence' else seq,3,1,2,1 if self.fault=='status' else 0)+content
        if self.fault=='short-header':self.reply=b'bad'
        return len(packet)
    def read(self,size):
        result,self.reply=self.reply[:size],self.reply[size:]
        if self.fault=='transport':raise OSError('synthetic read failure')
        return result

def test_wire_level_roundtrip_preserves_raw_headers_and_never_sends_debug(tmp_path):
    operation=op.Operation(bundle(tmp_path/'bundle'));driver=WireDriver(operation)
    out=tmp_path/'out';out.mkdir();report={};events=[]
    operation(driver,out,lambda event,**details:events.append((event,details)),report)
    assert operation.safe_to_stop and report['preload_unchanged']
    commands=[struct.unpack_from('<HH',p,HEADER.size)[1] for p in driver.requests]
    assert set(commands)=={15,16,17} and commands.count(16)==2
    assert any(e=='response_header' and row['raw_hex'] for e,row in events)
    assert any(e=='stat_failed_candidate' and row['absence_proven'] is False for e,row in events)

@pytest.mark.parametrize('fault',['short-write','function','sequence','status','short-header','transport'])
def test_wire_fault_closes_channel_before_any_followup(tmp_path,fault):
    operation=op.Operation(bundle(tmp_path/'bundle'));driver=WireDriver(operation,fault)
    channel=Channel(driver,operation,lambda *a,**k:None)
    with pytest.raises((ValueError,OSError)):channel.read('/version.txt',4096)
    count=len(driver.requests)
    with pytest.raises(PermissionError):channel.read('/version.txt',4096)
    assert not channel.usable and len(driver.requests)==count==1 and operation.trigger_attempts==0

def test_runtime_task_cannot_change_writes_or_inject_debug(tmp_path):
    operation=op.Operation(bundle(tmp_path/'bundle'));driver=WireDriver(operation)
    channel=Channel(driver,operation,lambda *a,**k:None)
    for body in (struct.pack('<HH',0x1001,5)+b'\0\0\0',struct.pack('<HH',0x1001,16)+b'\0\xff\0foreign'):
        packet=HEADER.pack(len(body),0x40,1,0,0,0,0)+body;operation.permitted_packet=packet
        with pytest.raises(PermissionError):operation.guard_packet(packet)
    with pytest.raises(PermissionError):channel.put('/etc/ld.so.preload',b'bad')
    assert driver.requests==[]

def test_task_timeout_is_not_completion_or_stop_permission(tmp_path,monkeypatch):
    operation=op.Operation(bundle(tmp_path/'bundle'),Service);out=tmp_path/'out';out.mkdir();report={}
    ticks=iter(range(0,1000,10));monkeypatch.setattr(op.time,'monotonic',lambda:next(ticks));monkeypatch.setattr(op.time,'sleep',lambda _:None)
    with pytest.raises(TimeoutError):operation('running',out,lambda *a,**k:None,report)
    assert not operation.safe_to_stop and operation.trigger_attempts==1

def sealed_fixture(path):
    path.mkdir();(path/'source.py').write_text('unchanged\n')
    manifest=dict(schema='a7r5-libjit-once-1',directory=str(path),risk=runner.RISK,run_id=RUN,
                  files={'source.py':runner.sha(path/'source.py')},dependencies={})
    (path/'operation.json').write_text(json.dumps(manifest))
    return path

def test_missing_approval_rejects_before_device_or_lock(tmp_path,monkeypatch):
    path=sealed_fixture(tmp_path/'package');monkeypatch.setattr(runner,'HERE',path)
    with pytest.raises(PermissionError):runner.execute(True)
    assert not (path/'ATTEMPT_LOCK').exists() and not (path/'result').exists()

@pytest.mark.parametrize('fault',['changed-source','changed-approval','used','moved','linked'])
def test_sealed_package_rejects_tampering_and_reuse(tmp_path,monkeypatch,fault):
    path=sealed_fixture(tmp_path/'package');monkeypatch.setattr(runner,'HERE',path)
    (path/'approval.json').write_text(json.dumps(dict(accepted=True,operation_sha256=runner.sha(path/'operation.json'),risk=runner.RISK)))
    assert runner.check(True)['run_id']==RUN
    if fault=='changed-source':(path/'source.py').write_text('changed')
    if fault=='changed-approval':(path/'approval.json').write_text('{}')
    if fault=='used':(path/'ATTEMPT_LOCK').mkdir()
    if fault=='moved':
        moved=tmp_path/'moved';path.rename(moved);monkeypatch.setattr(runner,'HERE',moved)
    if fault=='linked':
        (path/'source.py').rename(path/'saved.py');(path/'source.py').symlink_to(path/'saved.py')
    with pytest.raises((ValueError,PermissionError,FileExistsError)):runner.check(True)

def test_usb_recovery_requires_two_full_media_matches_and_no_extra_devices(monkeypatch):
    import host_state
    baseline=dict(location_id=host_state.LOCATION,drivers=['MassStorage'],media=[[True,100]])
    ordinary=dict(kind='ordinary',**baseline)
    rows=iter([dict(kind='transition'),ordinary,ordinary]);calls=[]
    monkeypatch.setattr(host_state.time,'sleep',lambda _:None)
    def take(label,timeout):calls.append(label);return next(rows)
    assert host_state.observe(baseline,take)['recovered'] and len(calls)==3
    rejected=host_state.observe(baseline,lambda *a,**k:dict(kind='ordinary',location_id=host_state.LOCATION,drivers=['MassStorage'],media=[[True,100],[True,200]]))
    assert not rejected['recovered'] and rejected['reason']=='metadata_rejected'

@pytest.mark.parametrize('gate',[False,True])
def test_real_session_sends_stop_only_when_operation_gate_is_open(tmp_path,monkeypatch,gate):
    import types
    old=HERE if (HERE/'vendor/engine').exists() else HERE.parent/'a7r5-ssh/ssh-service/manual-restart/packages/restart-20261021-01'
    sys.path.insert(0,str(old/'vendor/engine/mac'))
    from system_dump import session
    import usb.core,usb.util,usb.backend.libusb1
    calls=[];state={'stage':0}
    class Device:
        idVendor=0x054c;bus=0;port_numbers=(1,);iProduct=1
        def __init__(self,pid):self.idProduct=pid
        def get_active_configuration(self):
            interface=types.SimpleNamespace()
            class Interface(list):pass
            interface=Interface([types.SimpleNamespace(bmAttributes=2,bEndpointAddress=129),types.SimpleNamespace(bmAttributes=2,bEndpointAddress=2)])
            return {(0,0):interface}
        def ctrl_transfer(self,*args,**kwargs):calls.append((self.idProduct,args))
    ordinary=Device(0x0e0a);service=Device(0x0336)
    def find(*a,**k):return [ordinary if state['stage']==0 else service]
    class Auth:
        def __init__(self,driver):self.driver=driver
        def start(self):self.driver.vendorRequestOut(*session.START)
        def authenticate(self):state['stage']+=1
    sony=types.ModuleType('pmca.usb.sony');sony.SonySenserAuthDevice=Auth
    monkeypatch.setitem(sys.modules,'pmca.usb.sony',sony)
    monkeypatch.setattr(usb.core,'find',find)
    monkeypatch.setattr(usb.backend.libusb1,'get_backend',lambda **k:object())
    monkeypatch.setattr(usb.util,'get_string',lambda *a:'ILCE-7RM5')
    monkeypatch.setattr(usb.util,'dispose_resources',lambda *a:None)
    monkeypatch.setattr(usb.util,'release_interface',lambda *a:None)
    monkeypatch.setattr(session,'unmount_camera',lambda *a:None)
    monkeypatch.setattr(session,'claim_interface',lambda *a:False)
    class FixedOperation:
        safe_to_stop=False
        def interface_checked(self,*a):pass
        def __call__(self,*a):
            if not gate:raise ValueError('synthetic failed task')
            self.safe_to_stop=True
    report=session.run_session(tmp_path/'session','libusb',_operation=FixedOperation())
    stop=[args for _,args in calls if args[1:4]==session.STOP]
    assert len(stop)==int(gate)==report['service_stop_attempts']
    assert len(calls)==2+int(gate)
    assert report.get('recovery_required',False) is (not gate)

def test_vendor_import_closure_and_crypto_without_backend_initialization():
    old=HERE if (HERE/'vendor/engine').exists() else HERE.parent/'a7r5-ssh/ssh-service/manual-restart/packages/restart-20261021-01'
    sys.path[:0]=[str(old/'vendor/engine/mac'),str(old/'vendor/engine/libs'),str(old/'vendor/engine/sources/workspaces/j/work/sony-pmca-re')]
    from pmca.usb.sony import SonySenserAuthDevice
    from Cryptodome.Hash import SHA256
    assert hasattr(SonySenserAuthDevice,'authenticate')
    assert SHA256.new(b'abc').hexdigest()==hashlib.sha256(b'abc').hexdigest()
