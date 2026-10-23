"""真实Operation、分块通道和会话调度器；外部设备与认证后端明确模拟。"""
from collections import deque
import hashlib
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace,ModuleType
import pytest
from operation import Operation
from transport import HEADER
from system_dump import session
import usb.core,usb.util,usb.backend.libusb1


def make_operation(tmp_path,sealed):
    tmp_path.mkdir();(tmp_path/'materials').mkdir()
    cfg=json.loads((sealed/'config.json').read_text())
    cfg['version_sha256']=hashlib.sha256(b'FIXED-VERSION').hexdigest()
    cfg['loader_sha256']=hashlib.sha256(b'L'*233416).hexdigest()
    (tmp_path/'config.json').write_text(json.dumps(cfg))
    # 夹具只模拟文件服务；原生库另外由QEMU验收。
    (tmp_path/'materials/libJit.so').write_bytes(b'fixture-payload')
    (tmp_path/'materials/ticket.bin').write_bytes(b'fixture-ticket')
    for name in ('write-plan.json','candidate.logical.img'):
        (tmp_path/'materials'/name).write_bytes((sealed/'materials'/name).read_bytes())
    tick=[0.0]
    op=Operation(tmp_path,clock=lambda:tick[0],sleep=lambda seconds:tick.__setitem__(0,tick[0]+seconds))
    return op


class Camera:
    def __init__(self,op,fault=None):
        self.op=op;self.fault=fault;self.queue=deque();self.selected=None
        self.files={};self.puts=[];self.triggers=0;self.states=0;self.preloads=0
        self.output=(op.config['expected_output_begin']+'A7R5_TRUST_COMPLETE '+op.config['candidate_sha256']+
            ' sectors=258 bytes=132096 reopened=1\n'+op.config['expected_output_end']).encode()
        rows=[('PREIMAGE_VERIFIED',0,-1)]
        for i,row in enumerate(op.plan['rows']):
            rows += [('WRITE_BEGIN',i,row['offset']),('WRITE_RETURNED',i+1,row['offset'])]
            if i in (256,257):rows += [('PHASE_SYNC_RETURNED',i+1,row['offset'])]
        rows += [('FULL_LOGICAL_READBACK_MATCH',258,-1),('REOPENED_FULL_CAPTURE_MATCH',258,-1),('COMPLETED',258,-1)]
        self.journal=''.join(f'A7R5_TRUST {op.run} {phase} completed={count} offset={offset} code=0\n' for phase,count,offset in rows).encode()

    def contents(self,path):
        if path=='/version.txt':return b'FIXED-VERSION'
        if path=='/usr/lib/libJiritsu.so':return (b'X'+b'L'*233415) if self.fault=='loader' else b'L'*233416
        if path=='/etc/ld.so.preload':
            self.preloads+=1
            if self.fault=='preload-before' or self.fault=='preload-after' and self.preloads>=3:return b'unknown'
            return bytes.fromhex(self.op.config['expected_preload_hex'])
        if path.endswith('.state') and self.triggers:
            self.states+=1;run='0'*32 if self.fault=='nonce' else self.op.run
            phase='FAILED' if self.fault=='failed' else 'RUNNING' if self.fault=='host-timeout' else 'DONE'
            code=17 if phase=='FAILED' else 1 if self.fault=='repeat-state' and self.states>1 else 0
            children=1 if self.fault=='children' else 0
            return f'A7R5-JIT-1 {run} {phase} {code} uid=0 euid=0 bytes={len(self.output)} disarmed=1 children={children}\n'.encode()
        if path.endswith('.output') and self.triggers:return b'bad' if self.fault=='output' else self.output
        if path==self.op.config['journal_path']:
            return self.journal.replace(b'PHASE_SYNC_RETURNED',b'BAD_SYNC',1) if self.fault=='journal' else self.journal
        if path==self.op.config['readback_path']:
            raw=self.op.expected_candidate
            if self.fault=='readback-digest':return b'X'+raw[1:]
            if self.fault=='readback-short':return raw[:-1]
            return raw
        if path=='/tmp/jiritsu/libJit.so' and self.fault=='existing':return b'foreign'
        return self.files.get(path)

    def write(self,packet):
        self.op.guard_packet(packet);assert not self.queue
        if self.fault=='short-write':return len(packet)-1
        size,function,sequence,*meta=HEADER.unpack_from(packet)
        body=packet[12:];assert size==len(body) and function==64 and not any(meta)
        group,command=struct.unpack_from('<HH',body);assert group==0x1001
        code=0;data=b''
        if command==15:self.selected=body[5:-1].decode().replace('/tmp/jiritsu/../..','',1)
        elif command==16:
            self.files[self.selected]=body[7:];self.puts.append(self.selected)
            if self.selected=='/tmp/jiritsu/libJit.so':self.triggers+=1
        elif command==17:
            data=self.contents(self.selected)
            if data is None:code=0x10000006;data=b''
        else:raise AssertionError('额外设备命令')
        raw=struct.pack('<I',code)+data
        self.queue.append(HEADER.pack(len(raw),64,sequence+int(self.fault=='sequence'),3,0,0,0))
        for start in range(0,len(raw),32768):
            block=raw[start:start+32768];self.queue.append(block)
            if len(block)%512==0 and self.fault!='missing-zlp':self.queue.append(b'')
        return len(packet)

    def read(self,size):
        if not self.queue:raise TimeoutError('模拟截断')
        block=self.queue.popleft();take=size if size==12 else min(size,503)
        if block[take:]:self.queue.appendleft(block[take:])
        return block[:take]


@pytest.mark.parametrize('fault',[None,'preload-before','loader','existing','short-write','sequence','missing-zlp',
    'failed','host-timeout','nonce','children','output','journal','readback-digest','readback-short','preload-after','repeat-state'])
def test_full_wire_contract_stops_at_first_failure(tmp_path,sealed,fault):
    op=make_operation(tmp_path/'run',sealed);camera=Camera(op,fault);out=tmp_path/'out';out.mkdir();report={}
    if fault is None:
        op(camera,out,lambda *a,**k:None,report)
        assert report['complete_partition_readback_verified'] and op.safe_to_stop and not camera.queue
        assert (out/'partition1.logical.bin').read_bytes()==op.expected_candidate
    else:
        with pytest.raises((ValueError,RuntimeError,TimeoutError,OSError,PermissionError)):
            op(camera,out,lambda *a,**k:None,report)
        assert not op.safe_to_stop and not report['protocol_gate_passed']
    assert camera.triggers<=1 and len(camera.puts)<=2
    assert set(camera.puts)<={op.prefix+'.ticket','/tmp/jiritsu/libJit.so'}
    assert not report['worker_timeout_kill'] and not report['preload_written'] and not report['debug_commands_sent']


@pytest.mark.parametrize('fault',[None,'journal','readback-digest'])
def test_real_session_sends_STOP_only_after_full_readback(tmp_path,sealed,monkeypatch,fault):
    op=make_operation(tmp_path/'run',sealed);op.output=tmp_path/'session';camera=Camera(op,fault)
    controls=[];stage=[0]
    class Interface(list):pass
    class Device:
        idVendor=0x054c;bus=0;port_numbers=[1];iProduct=1
        def __init__(self,pid):self.idProduct=pid
        def get_active_configuration(self):
            row=op.config['interfaces']['interface-1.json' if self.idProduct==0x0e0a else 'interface-2.json']
            interface=Interface([SimpleNamespace(bEndpointAddress=e['address'],bmAttributes=e['attributes'],wMaxPacketSize=e['max_packet'],bInterval=e['interval'])for e in row['endpoints']])
            for attr,key in [('bInterfaceNumber','number'),('bAlternateSetting','alternate'),('bInterfaceClass','interface_class'),('bInterfaceSubClass','subclass'),('bInterfaceProtocol','protocol')]:setattr(interface,attr,row[key])
            return {(0,0):interface}
        def write(self,ep,data,timeout):assert ep==2;return camera.write(data)
        def read(self,ep,n,timeout):assert ep==129;return camera.read(n)
        def ctrl_transfer(self,*args,**kwargs):controls.append(args)
    ordinary=Device(0x0e0a);service=Device(0x0336)
    class Auth:
        def __init__(self,driver):self.driver=driver
        def start(self):self.driver.vendorRequestOut(*session.START)
        def authenticate(self):stage[0]+=1
    sony=ModuleType('pmca.usb.sony');sony.SonySenserAuthDevice=Auth
    monkeypatch.setitem(sys.modules,'pmca.usb.sony',sony)
    monkeypatch.setattr(usb.core,'find',lambda **k:[ordinary if stage[0]==0 else service])
    monkeypatch.setattr(usb.backend.libusb1,'get_backend',lambda **k:object())
    monkeypatch.setattr(usb.util,'get_string',lambda *a:'ILCE-7RM5')
    monkeypatch.setattr(usb.util,'dispose_resources',lambda *a:None)
    monkeypatch.setattr(usb.util,'release_interface',lambda *a:None)
    monkeypatch.setattr(session,'claim_interface',lambda *a:False)
    monkeypatch.setattr(session,'unmount_camera',lambda *a:None)
    report=session.run_session(op.output,'libusb',_operation=op)
    assert stage[0]==2 and op.interfaces_seen==2
    assert report['service_stop_attempts']==int(fault is None)
    assert sum(c[1:4]==session.STOP for c in controls)==int(fault is None)
    assert len(controls)==2+int(fault is None)
