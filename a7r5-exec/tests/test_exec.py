"""两条生产操作都通过独立分块设备夹具，断言无额外触发或恢复写入。"""
from collections import deque
import hashlib
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
import core
import controller
from libjit_operation import Operation as LibJit
from kit_operation import Operation as Kit
from transport import HEADER
PROFILE=json.loads((ROOT/'runtime/profile.json').read_text())
LIBRARY=(ROOT/'sdk/libJiritsu.so').read_bytes()


def operation(tmp,engine,fault=None):
    tmp.mkdir();(tmp/'materials').mkdir()
    cfg=dict(PROFILE,run_id='aabbccdd'*4,engine=engine,task_seconds=1,
             expected_output_begin='BEGIN\n',expected_output_end='END\n')
    (tmp/'config.json').write_text(json.dumps(cfg))
    for name in ['payload.so','libJit.so']:(tmp/'materials'/name).write_bytes(b'fixed-payload')
    (tmp/'materials/ticket.bin').write_bytes(b'fixed-ticket')
    return (LibJit if engine=='libjit' else Kit)(tmp)


class Camera:
    def __init__(self,op,engine,fault=None):
        self.op=op;self.engine=engine;self.fault=fault;self.queue=deque();self.requests=[];self.puts=[];self.triggers=0
        self.preloads=0;self.states=0;self.output=b'BEGIN\nfixed-read-only-result\nEND\n'
        self.preload=bytes.fromhex(PROFILE['preload_baselines'][0 if engine=='kit' else 1][1])
        self.files={};self.selected=None;self.armed=False

    def contents(self,path):
        if path=='/version.txt':return b'fixed-version'
        if path=='/usr/lib/libJiritsu.so':return (b'X'+LIBRARY[1:]) if self.fault=='loader' else LIBRARY
        if path=='/etc/ld.so.preload':
            self.preloads+=1
            if self.fault=='unknown-preload':return b'unknown'
            if self.fault=='boot-hook' and self.engine=='kit':return bytes.fromhex(PROFILE['preload_baselines'][1][1])
            if self.fault=='preload-changed' and self.preloads>=3:return b'changed'
            return self.preload
        if path.endswith('.state') and self.triggers:
            self.states+=1
            run=self.op.run if self.fault!='nonce' else '0'*32
            phase='TIMEOUT' if self.fault=='timeout' else 'DONE'
            code=42 if self.fault=='exit' else 0;uid=1 if self.fault=='uid' else 0
            if self.fault=='state-changed' and self.states>1:code=1
            if self.engine=='libjit':return f'A7R5-JIT-1 {run} {phase} {code} uid={uid} euid=0 bytes={len(self.output)} disarmed=1 children={1 if self.fault=="children" else 0}\n'.encode()
            return f'A7R5-ROOT-1 {run} {phase} {code} uid={uid} euid=0 bytes={len(self.output)}\n'.encode()
        if path.endswith('.output') and self.triggers:return b'foreign' if self.fault=='output' else self.output
        if self.fault=='existing' and (path==self.op.prefix+'.so' or path=='/tmp/jiritsu/libJit.so'):return b'foreign'
        return self.files.get(path)

    def write(self,packet):
        # 与实际session.Driver一致再次核对同一报文，捕获双层守卫不一致。
        self.op.guard_packet(packet)
        assert not self.queue
        self.requests.append(packet)
        if self.fault=='short-write':return len(packet)-1
        _,func,seq,*meta=HEADER.unpack_from(packet);assert func==64 and not any(meta)
        body=packet[12:];group,command=struct.unpack_from('<HH',body);assert group==0x1001
        code=0;raw=b''
        if command==15:self.selected=body[5:-1].decode().replace('/tmp/jiritsu/../..','',1)
        elif command==17:
            raw=self.contents(self.selected)
            if raw is None:code=0x10000006;raw=b''
        elif command==16:
            raw=body[7:];self.puts.append((self.selected,raw));self.files[self.selected]=raw
            if self.selected=='/etc/ld.so.preload':self.preload=raw;self.armed=True
            if self.selected=='/tmp/jiritsu/libJit.so':self.triggers+=1
            raw=b''
        elif command==5:
            assert self.engine=='kit' and self.armed
            self.triggers+=1;self.preload=b'\n'*512
        else:raise AssertionError('额外设备命令')
        data=struct.pack('<I',code)+raw
        self.queue.append(HEADER.pack(len(data),64,seq+int(self.fault=='sequence'),3,0,0,0))
        for off in range(0,len(data),32768):
            block=data[off:off+32768];self.queue.append(block)
            if len(block)%512==0 and self.fault!='missing-zlp':self.queue.append(b'')
        return len(packet)

    def read(self,n):
        if not self.queue:raise TimeoutError('模拟截断')
        row=self.queue.popleft();count=n if n==12 else min(n,503)
        if row[count:]:self.queue.appendleft(row[count:])
        return row[:count]


@pytest.mark.parametrize('engine',['libjit','kit'])
def test_both_routes_complete_one_trigger_and_preserve_preload_policy(tmp_path,engine):
    op=operation(tmp_path/'run',engine);op.config['version_sha256']=hashlib.sha256(b'fixed-version').hexdigest()
    driver=Camera(op,engine);out=tmp_path/'out';out.mkdir();report={}
    op(driver,out,lambda *a,**k:None,report)
    assert op.safe_to_stop and report['protocol_gate_passed'] and driver.triggers==1 and len(driver.puts)==2
    assert report['debug_commands_sent'] is (engine=='kit') and report['preload_written'] is (engine=='kit')
    assert driver.preload==bytes.fromhex(PROFILE['preload_baselines'][0 if engine=='kit' else 1][1])
    assert set(struct.unpack_from('<HH',p,12)[1] for p in driver.requests)<={15,16,17,5}
    assert not driver.queue and (out/'loader.bin').read_bytes()==LIBRARY


@pytest.mark.parametrize('engine',['libjit','kit'])
@pytest.mark.parametrize('fault',['short-write','sequence','loader','missing-zlp','unknown-preload','existing','nonce','uid','timeout','exit','output','preload-changed','state-changed'])
def test_any_failure_withholds_stop_and_never_retriggers_or_restores(tmp_path,engine,fault):
    op=operation(tmp_path/'run',engine);op.config['version_sha256']=hashlib.sha256(b'fixed-version').hexdigest()
    driver=Camera(op,engine,fault);out=tmp_path/'out';out.mkdir();report={}
    with pytest.raises((ValueError,PermissionError,TimeoutError,RuntimeError,OSError)):
        op(driver,out,lambda *a,**k:None,report)
    assert not op.safe_to_stop and not report['protocol_gate_passed'] and driver.triggers<=1 and len(driver.puts)<=2
    if fault in ['short-write','sequence','loader','missing-zlp','unknown-preload','existing']:assert not driver.puts
    if engine=='kit':assert not any(raw==b'\n'*512 for _,raw in driver.puts)


def test_kit_boot_pointer_never_gets_overwritten(tmp_path):
    op=operation(tmp_path/'run','kit');op.config['version_sha256']=hashlib.sha256(b'fixed-version').hexdigest()
    driver=Camera(op,'kit','boot-hook');out=tmp_path/'out';out.mkdir()
    with pytest.raises(PermissionError):op(driver,out,lambda *a,**k:None,{})
    assert not driver.puts and driver.triggers==0 and not op.safe_to_stop


def test_libjit_active_descendant_is_not_success(tmp_path):
    op=operation(tmp_path/'run','libjit');op.config['version_sha256']=hashlib.sha256(b'fixed-version').hexdigest()
    out=tmp_path/'out';out.mkdir()
    with pytest.raises(ValueError):op(Camera(op,'libjit','children'),out,lambda *a,**k:None,{})
    assert not op.safe_to_stop


def test_missing_approval_blocks_before_device_or_attempt_lock(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'HERE',tmp_path)
    monkeypatch.setattr(core,'load',lambda _:dict(engine='kit'))
    with pytest.raises(PermissionError):controller.execute(tmp_path/'run',True)
    assert not (tmp_path/'run/ATTEMPT_LOCK').exists()


def test_prepare_syntax_check_does_not_execute_user_command(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'check_tool',lambda:None)
    monkeypatch.setattr(core,'HERE',tmp_path)
    marker=tmp_path/'should-not-exist'
    def compiler(*args):raise RuntimeError('停止在构建之前')
    monkeypatch.setattr(core,'compile_payload',compiler)
    with pytest.raises(RuntimeError):core.prepare('libjit','touch '+str(marker)+'; echo "$(id)"',1)
    assert not marker.exists()


@pytest.mark.parametrize('text,seconds',[('',1),('id\r\n',1),('id\0',1),('id',0),('id',61),('"',1)])
def test_invalid_task_rejected_before_build_or_new_run(tmp_path,monkeypatch,text,seconds):
    monkeypatch.setattr(core,'check_tool',lambda:None);monkeypatch.setattr(core,'HERE',tmp_path)
    with pytest.raises(ValueError):core.prepare('libjit',text,seconds)
    assert not (tmp_path/'runs').exists()


def test_pending_failure_blocks_new_run_before_usb_or_new_attempt(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'HERE',tmp_path);monkeypatch.setattr(core,'approved',lambda _:dict(run_id='new',engine='kit'))
    monkeypatch.setattr(core,'load',lambda _:dict(engine='kit'))
    monkeypatch.setattr(controller.sys,'platform','darwin');monkeypatch.setattr(controller.os,'geteuid',lambda:0)
    (tmp_path/'PENDING_RECOVERY.json').write_text('{}')
    with pytest.raises(PermissionError):controller.execute(tmp_path/'new',True)
    assert not (tmp_path/'new/ATTEMPT_LOCK').exists()


def test_global_execution_lock_rejects_concurrent_session(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'HERE',tmp_path)
    with controller.exclusive():
        with pytest.raises(BlockingIOError):
            with controller.exclusive():pass
