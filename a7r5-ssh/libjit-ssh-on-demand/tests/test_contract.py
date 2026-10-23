"""契约测试：检查真实外部结果、写入次数和失败后禁止STOP。"""
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT.parents[1]/'a7r5-exec/runtime')]
import operation
import policy
import tool
from transport import FileResultError, HEADER

RUN='ab'*16
PUBLIC=b'ecdsa-sha2-nistp256 '+base64.b64encode(b'\0\0\0\x13ecdsa-sha2-nistp256'+b'\0\0\0\x08nistp256'+b'\0\0\0A\x04'+b'x'*64)+b' offline\n'
PUBLIC_SHA=hashlib.sha256(PUBLIC).hexdigest()
READY=(f'A7R5_PRIVATE_READY {RUN} parent=41 child=42 uid=0 euid=0 ttl=0 parent_unchanged=1 '
       f'private_account_changed=1 parent_ns=mnt:[100] child_ns=mnt:[200] host_public_sha={PUBLIC_SHA}\n').encode()
TERMINAL=(f'A7R5_PRIVATE_RESULT {RUN} code=0 parent_unchanged=1 child_tree_reaped=1 '
          'child_terminal_seen=1 listener_absent=1 changes_observed=0\n').encode()
CHILD=b'PRIVATE_RESULT code=0 errno=0 sshd_attempted=1 listener_observed=1 children_reaped=1 private_account_changed=1 local_banner_verified=1\n'


@pytest.fixture
def material(tmp_path):
    package=tmp_path/'package';package.mkdir(mode=0o700)
    m=package/'materials';m.mkdir()
    config=dict(interfaces={},loader_bytes=6,loader_sha256=hashlib.sha256(b'loader').hexdigest(),
                version_sha256=hashlib.sha256(b'version').hexdigest())
    (package/'config.json').write_text(json.dumps(config))
    prefix='/tmp/jiritsu/a7r5-ljssh-'+RUN
    uploads={prefix+'.service':'service.arm64',prefix+'.session':'session.arm64',prefix+'.sftp':'sftp-server.arm64'}
    for name in uploads.values():(m/name).write_bytes(name.encode())
    (m/'libJit.so').write_bytes(b'trigger')
    (m/'ticket.bin').write_bytes(('A7R5_SSH_START '+RUN+'\n').encode())
    (m/'build.json').write_text(json.dumps(dict(run_id=RUN,prefix=prefix,ram_directory='/tmp_network/a7r5-libjit-ssh-'+RUN,ttl_seconds=0,uploads=uploads)))
    state=package/'.state/start-once';state.mkdir(parents=True)
    (state/'host-public-key').write_bytes(PUBLIC)
    return package


class FakeChannel:
    fault=None
    instance=None
    def __init__(self,driver,op,log):
        self.op=op;self.writes=[];self.reads=[];self.tick=0
        type(self).instance=self
    def read(self,path,limit):
        self.reads.append(path)
        action=self.op.action;ram=self.op.ram
        if path=='/version.txt':raw=b'version'
        elif path=='/usr/lib/libJiritsu.so':raw=b'loader'
        elif path=='/etc/ld.so.preload':
            raw=policy.BASELINE
            if self.fault=='final-preload' and self.writes:raw=b'changed'
        elif path in self.op.uploads:
            if action=='load-once' and path not in dict(self.writes):raise FileResultError(0x10000006)
            raw=self.op.uploads[path]
            if self.fault=='upload' and self.writes:raw=b'wrong'
            if self.fault=='loaded' and action=='start-once':raw=b'wrong'
        elif path==self.op.prefix+'.ticket' and path in dict(self.writes):
            raw=dict(self.writes)[path]
            if self.fault=='ticket':raw=b'wrong'
        elif path==self.op.prefix+'.claim' and self.writes:raw=(self.op.materials/'ticket.bin').read_bytes()
        elif path==ram+'/ready' and (action!='start-once' or len(self.writes)==2):raw=READY
        elif path==ram+'/host-public-key':raw=PUBLIC
        elif path==ram+'/hostkey-check':raw=b'A7R5_RAM_GENERATED_HOSTKEY verified=1 mode=600 tmpfs=1 private_key_logged=0\n'
        elif path==ram+'/banner':raw=b'SSH-2.0-test\r\n'
        elif path==ram+'/started':raw=(f'A7R5_WILDCARD_STARTED {RUN} pid=43 bind=0.0.0.0:2222 listener_observed=1 banner_sha='+hashlib.sha256(b'SSH-2.0-test\r\n').hexdigest()+'\n').encode()
        elif path==ram+'/heartbeat':
            if action=='collect-once' or action=='stop-once' and self.writes:raw=b'A7R5_PRIVATE_ENDED\n'
            else:
                self.tick+=1000 if self.fault!='frozen-heartbeat' else 0
                raw=(f'A7R5_PRIVATE_ALIVE {RUN} parent=41 child=42 ttl=0 elapsed_ms={self.tick} parent_unchanged=1 changes_observed=0\n').encode()
        elif path==ram+'/result' and (action=='collect-once' or self.writes and action=='stop-once'):raw=TERMINAL
        elif path==ram+'/child-result':raw=CHILD
        else:raise FileResultError(0x10000006)
        if self.fault=='protocol' and path=='/usr/lib/libJiritsu.so':raise IOError('framing lost')
        if self.fault=='version' and path=='/version.txt':raw=b'wrong'
        if self.fault=='preload' and path=='/etc/ld.so.preload':raw=b'wrong'
        if self.fault=='ready' and path==ram+'/ready':raw=raw.replace(b'ttl=0',b'ttl=600')
        if self.fault=='public' and path==ram+'/host-public-key':raw=b'wrong'
        if self.fault=='terminal' and path==ram+'/result':raw=raw.replace(b'listener_absent=1',b'listener_absent=0')
        return raw
    def put(self,path,data):
        assert self.op.writes[path]==data
        self.writes.append((path,data))


def run(material,monkeypatch,action,fault=None):
    monkeypatch.setattr(operation.time,'sleep',lambda _:None)
    monkeypatch.setattr(FakeChannel,'fault',fault)
    op=operation.Operation(material,action,FakeChannel)
    out=material/'.state'/action/'session';out.mkdir(parents=True,exist_ok=True)
    report={}
    return op,out,report


@pytest.mark.parametrize('action,count',[('load-once',3),('start-once',2),('stop-once',1),('collect-once',0)])
def test_successful_fixed_contracts(material,monkeypatch,action,count):
    op,out,report=run(material,monkeypatch,action)
    op(None,out,lambda *a,**kw:None,report)
    assert op.safe_to_stop and report['protocol_gate_passed'] and report['fixed_writes_attempted']==count
    assert len(FakeChannel.instance.writes)==count
    assert not report['preload_written'] and not report['debug_commands_sent']
    assert not any('host_ecdsa' in p for p in FakeChannel.instance.reads)


@pytest.mark.parametrize('action,fault,count',[
    ('load-once','version',0),('load-once','preload',0),('load-once','protocol',0),
    ('load-once','upload',1),('load-once','final-preload',3),
    ('start-once','loaded',0),('start-once','ticket',1),('start-once','ready',2),
    ('start-once','public',2),('start-once','frozen-heartbeat',2),
    ('stop-once','public',0),('stop-once','terminal',1),('collect-once','terminal',0)])
def test_fault_does_not_retry_or_open_stop_gate(material,monkeypatch,action,fault,count):
    op,out,report=run(material,monkeypatch,action,fault)
    with pytest.raises((ValueError,IOError)):
        op(None,out,lambda *a,**kw:None,report)
    assert not op.safe_to_stop and report['fixed_writes_attempted']==count
    assert len(FakeChannel.instance.writes)==count


def test_default_sftp_public_key_and_changed_originals_are_not_hidden():
    assert policy.public_key(PUBLIC,PUBLIC_SHA).startswith(b'ecdsa-')
    changed=TERMINAL.replace(b'parent_unchanged=1',b'parent_unchanged=0').replace(b'changes_observed=0',b'changes_observed=1')
    assert policy.terminal(changed,CHILD,RUN)==dict(originals_unchanged=False,changes_observed=True)


@pytest.mark.parametrize('body',[b'\x00'*7,struct.pack('<HH',0x1001,15)+b'\0/etc/passwd\0'])
def test_private_reads_and_debug_cannot_cross_packet_guard(material,body):
    op=operation.Operation(material,'load-once',FakeChannel)
    packet=HEADER.pack(len(body),0x40,1,0,0,0,0)+body
    op.permitted_packet=packet
    with pytest.raises(PermissionError):op.guard_packet(packet)


def test_no_device_flag_denied_before_snapshot_or_connection(tmp_path,monkeypatch):
    monkeypatch.setattr(tool,'check',lambda _:dict(project=str(tmp_path)))
    monkeypatch.setattr(tool,'phrase',lambda *_:'ACCEPT-test')
    monkeypatch.setattr(tool,'snapshot_runtime',lambda *_:pytest.fail('must not observe devices'))
    with pytest.raises(PermissionError):tool.execute(tmp_path,'load-once')
