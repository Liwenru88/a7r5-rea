"""限制每次文件响应，使用真实Channel验证1532块和失步停止。"""
import hashlib
import json
from collections import deque

import pytest

import common
import device
from capture_operation import ExistingCaptureOperation
from transport import HEADER


@pytest.mark.parametrize('fault',[None,'timeout'])
def test_new_layout_avoids_long_responses_and_preserves_failed_checkpoint(tmp_path,baseline,ram_runtime,fault):
    package,_=device.prepare_capture(tmp_path,'9'*32,baseline)
    cfg=common.load(package/'config.json')
    cfg.update(version_sha256=hashlib.sha256(b'v').hexdigest(),loader_sha256=hashlib.sha256(b'l').hexdigest())
    (package/'config.json').write_text(json.dumps(cfg))
    image=bytes(range(256))*(25100288//256);digest=hashlib.sha256(image).hexdigest()
    native=(cfg['expected_output_begin']+f'A7R5_CAPTURE_COMPLETE {digest} bytes=25100288 twice=1 chunks=1532 chunk_bytes=16384\n'+cfg['expected_output_end']).encode()
    op=ExistingCaptureOperation(package);op.output=tmp_path/'session';op.output.mkdir()
    selected=None;queue=deque();sequences=[];part_requests=[]
    class Driver:
        def write(self,packet):
            nonlocal selected
            op.guard_packet(packet)
            _,_,sequence,*_=HEADER.unpack_from(packet);sequences.append(sequence)
            command=int.from_bytes(packet[14:16],'little');raw=b''
            if command==15:selected=packet[17:-1].decode().replace('/tmp/jiritsu/../..','',1)
            else:
                assert command==17
                if selected=='/version.txt':raw=b'v'
                elif selected=='/usr/lib/libJiritsu.so':raw=b'l'
                elif selected=='/etc/ld.so.preload':raw=b'\n'*512
                elif selected==op.prefix+'.state':raw=f'A7R5-JIT-1 {op.run} DONE 0 uid=0 euid=0 bytes={len(native)} disarmed=1 children=0\n'.encode()
                elif selected==op.prefix+'.output':raw=native
                else:
                    index=int(selected.rsplit('-',1)[1]);part_requests.append(index)
                    raw=image[index*16384:(index+1)*16384]
            raw=b'\0'*4+raw
            assert len(raw)<=16388,'仍在使用可能卡住的256KiB长响应'
            queue.append(HEADER.pack(len(raw),64,sequence,3,0,0,0));queue.append(raw)
            return len(packet)
        def read(self,size):
            if fault=='timeout' and part_requests and part_requests[-1]==5 and len(queue)==1:
                raise TimeoutError('模拟第6块超时')
            raw=queue.popleft()
            if len(raw)>8192:queue.appendleft(raw[8192:]);return raw[:8192]
            return raw
    report={}
    if fault:
        with pytest.raises(TimeoutError):op(Driver(),op.output,lambda *a,**k:None,report)
        assert not op.safe_to_stop and report['capture_download_chunks']==5
        saved=common.load(op.output/'download-checkpoint.json')
        assert saved['completed_chunks']==5 and saved['native_sha256']==digest
        assert not (op.output/'partition1.logical.bin').exists()
        assert part_requests==list(range(6))
        assert not report.get('capture_verified') and not report.get('backup_persisted')
        assert saved['completed_bytes']==5*16384
        assert saved['completed_sha256']==hashlib.sha256(image[:5*16384]).hexdigest()
    else:
        op(Driver(),op.output,lambda *a,**k:None,report)
        assert report['capture_verified'] and report['capture_download_chunks']==1532
        assert (op.output/'partition1.logical.bin').read_bytes()==image and op.safe_to_stop
    assert sequences==list(range(1,len(sequences)+1))


def test_request_budget_is_fixed_and_paths_remain_bound(tmp_path,baseline,ram_runtime):
    from libjit_operation import Operation as BaseOperation
    from transport import Channel,READ,wire
    import struct
    package,_=device.prepare_capture(tmp_path,'1'*32,baseline)
    new=ExistingCaptureOperation(package)
    ordinary=BaseOperation(package)
    assert new.packet_limit==4096 and ordinary.packet_limit==512
    for op,last in ((new,4096),(ordinary,512)):
        body=struct.pack('<HH',0x1001,15)+b'\0'+wire('/version.txt')+b'\0'
        op.permitted_packet=HEADER.pack(len(body),64,last,0,0,0,0)+body
        op.guard_packet(op.permitted_packet)
        op.permitted_packet=HEADER.pack(len(body),64,last+1,0,0,0,0)+body
        with pytest.raises(PermissionError):op.guard_packet(op.permitted_packet)
        class Forbidden:
            def write(self,*a):pytest.fail('预算耗尽后禁止继续发送')
        channel=Channel(Forbidden(),op,lambda *a,**k:None);channel.sequence=last+1
        with pytest.raises(PermissionError):channel.exchange(READ,4)
    # 扩大请求次数不扩大路径范围；不存在第1533块。
    body=struct.pack('<HH',0x1001,15)+b'\0'+wire(new.config['capture_path']+'.part-1532')+b'\0'
    new.permitted_packet=HEADER.pack(len(body),64,513,0,0,0,0)+body
    with pytest.raises(PermissionError):new.guard_packet(new.permitted_packet)


@pytest.mark.parametrize('fault',['unknown-format','old-payload','old-cleanup'])
def test_mixed_layout_is_rejected_before_any_io(tmp_path,baseline,ram_runtime,legacy_capture_payload,fault):
    from capture_operation import Operation
    package,_=device.prepare_capture(tmp_path,'2'*32,baseline)
    cfg=common.load(package/'config.json')
    if fault=='unknown-format':cfg['capture_format']='arbitrary'
    elif fault=='old-cleanup':cfg['capture_cleanup_policy']='verified-current-ram-v1'
    else:(package/'materials/libJit.so').write_bytes(legacy_capture_payload)
    (package/'config.json').write_text(json.dumps(cfg))
    with pytest.raises(ValueError):Operation(package)
