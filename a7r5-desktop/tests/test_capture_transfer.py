"""通过真实会话和Channel验证小粒度USB读取，不访问设备。"""
from collections import deque
import hashlib
import json
import pytest

import common
import device
from capture_operation import ExistingCaptureOperation
from capture_operation import Operation
from system_dump import session
from test_device import Wire,install_session


def test_existing_backup_uses_8KiB_IO_and_32KiB_protocol_blocks(tmp_path,baseline,monkeypatch,ram_runtime):
    package,_=device.prepare_capture(tmp_path,'7'*32,baseline)
    cfg=common.load(package/'config.json')
    cfg.update(version_sha256=hashlib.sha256(b'fixture-version').hexdigest(),loader_sha256=hashlib.sha256(b'L'*233416).hexdigest())
    (package/'config.json').write_text(json.dumps(cfg))
    image=bytes(range(256))*(25100288//256)
    digest=hashlib.sha256(image).hexdigest()
    output=(cfg['expected_output_begin']+f'A7R5_CAPTURE_COMPLETE {digest} bytes=25100288 twice=1 chunks=1532 chunk_bytes=16384\n'+cfg['expected_output_end']).encode()
    op=ExistingCaptureOperation(package);op.start=op;op.output=tmp_path/'session'
    class CaptureWire(Wire):
        def __init__(self):super().__init__(op,None);self.requests=[]
        def contents(self,path):
            if path==op.prefix+'.state':return f'A7R5-JIT-1 {op.run} DONE 0 uid=0 euid=0 bytes={len(output)} disarmed=1 children=0\n'.encode()
            if path==op.prefix+'.output':return output
            if path in dict(op.parts):
                index=int(path.rsplit('-',1)[1]);return image[index*16384:(index+1)*16384]
            return super().contents(path)
        def read(self,size):
            self.requests.append(size)
            assert size<=8192,'备份底层读取仍超过8KiB'
            block=self.queue.popleft()
            if len(block)>size:self.queue.appendleft(block[size:])
            return block[:size]
    camera=CaptureWire();controls,_=install_session(monkeypatch,op,camera)
    report=session.run_session(op.output,'libusb',_operation=op)
    assert not report.get('failure'),report.get('failure')
    assert report['capture_verified'] and report['capture_download_chunks']==1532
    assert (op.output/'partition1.logical.bin').read_bytes()==image
    assert report['file_usb_read_limit']==8192 and max(camera.requests)==8192
    assert not camera.puts and not camera.queue and report['fixed_writes_attempted']==0
    assert sum(c[1:4]==session.STOP for c in controls)==1


@pytest.mark.parametrize('fault',[None,'cleanup-failed','cleanup-response-lost'])
def test_new_backup_shares_channel_and_stops_only_after_cleanup(tmp_path,baseline,monkeypatch,ram_runtime,fault):
    package,_=device.prepare_capture(tmp_path,'8'*32,baseline)
    cfg=common.load(package/'config.json')
    cfg.update(version_sha256=hashlib.sha256(b'fixture-version').hexdigest(),loader_sha256=hashlib.sha256(b'L'*233416).hexdigest())
    (package/'config.json').write_text(json.dumps(cfg))
    op=Operation(package,sleep=lambda seconds:None);op.start=op;op.output=tmp_path/'session'
    image=bytes(range(256))*(25100288//256);digest=hashlib.sha256(image).hexdigest()
    output=(cfg['expected_output_begin']+f'A7R5_CAPTURE_COMPLETE {digest} bytes=25100288 twice=1 chunks=1532 chunk_bytes=16384\n'+cfg['expected_output_end']).encode()
    receipt=f'A7R5_CAPTURE_CLEANUP {op.run} sha256={digest} deleted=1532 bytes=25100288 directory_removed=1\n'.encode()
    class CaptureWire(Wire):
        def contents(self,path):
            if path=='/version.txt':return b'fixture-version'
            if path=='/usr/lib/libJiritsu.so':return b'L'*233416
            if path=='/etc/ld.so.preload':return b'\n'*512
            if self.triggers:
                if path==op.prefix+'.state':return f'A7R5-JIT-1 {op.run} DONE 0 uid=0 euid=0 bytes={len(output)} disarmed=1 children=0\n'.encode()
                if path==op.prefix+'.output':return output
                if path in dict(op.parts):
                    index=int(path.rsplit('-',1)[1]);return image[index*16384:(index+1)*16384]
            if self.triggers==2:
                if path==op.cleanup_prefix+'.state':
                    if fault=='cleanup-response-lost':raise TimeoutError('模拟清理回执丢失')
                    state='FAILED 71' if fault=='cleanup-failed' else 'DONE 0'
                    return f'A7R5-JIT-1 {op.run} {state} uid=0 euid=0 bytes={len(receipt)} disarmed=1 children=0\n'.encode()
                if path==op.cleanup_prefix+'.output':return receipt
            return self.files.get(path)
    camera=CaptureWire(op,None);controls,_=install_session(monkeypatch,op,camera)
    report=session.run_session(op.output,'libusb',_operation=op)
    assert report['capture_verified'] and report['backup_persisted']
    assert (op.output/'partition1.logical.bin').read_bytes()==image
    assert camera.sequences==list(range(1,len(camera.sequences)+1))
    assert camera.triggers==2 and len(camera.puts)==4
    assert sum(c[1:4]==session.STOP for c in controls)==int(fault is None)
    assert report['service_stop_attempts']==int(fault is None)
    assert op.safe_to_stop is (fault is None)
    if fault is None:assert report['capture_cleanup_verified']
    else:assert report['capture_cleanup_state']=='failed' and report['failure']
