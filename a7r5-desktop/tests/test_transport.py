"""按PMCA的1MiB响应帧和32KiB逻辑块契约构造独立内存响应。"""
from collections import deque
import hashlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest
from transport import Channel, FileResultError, HEADER, READ


def test_ssh_upload_packets_match_successful_legacy_transport():
    # 固定对照由旧成功包生成；数据是合成字节，不包含程序、账户或口令。
    fixture=json.loads((Path(__file__).parent/'fixtures/ssh-upload-wire-legacy.json').read_text())
    for row in fixture['cases']:
        size=row['payload_bytes'];path=row['path']
        payload=(bytes(range(256))*((size+255)//256))[:size]
        queue=deque([HEADER.pack(4,64,1,0,0,0,0),struct.pack('<I',0),
                     HEADER.pack(4,64,2,0,0,0,0),struct.pack('<I',0)])
        writes=[]
        driver=SimpleNamespace(read=lambda n:queue.popleft(),write=lambda b:writes.append(b) or len(b))
        operation=SimpleNamespace(writes={path:payload},guard_packet=lambda packet:None)
        Channel(driver,operation,lambda *a,**k:None).put(path,payload)
        assert not queue and len(writes)==2
        assert writes[0].hex()==row['select_hex']
        assert hashlib.sha256(writes[1]).hexdigest()==row['upload_sha256']


def response_driver(payload, fault=None):
    raw = struct.pack('<I', 0) + payload
    queue = deque()
    for at in range(0, len(raw), 0x100000):
        sequence = 2 if at and fault == 'sequence' else 1
        remaining = len(raw)-at
        queue.append(HEADER.pack(remaining, 0x40, sequence, 3, 0, 0, 0))
        frame = raw[at:at+0x100000]
        for start in range(0, len(frame), 0x8000):
            block = frame[start:start+0x8000]
            queue.append(block)
            if len(block) % 512 == 0:
                queue.append(b'')
    writes, requests = [], []
    def read(size):
        requests.append(size)
        if not queue:
            raise TimeoutError('响应已结束，不能额外读取')
        block = queue.popleft()
        if len(block) > size:
            queue.appendleft(block[size:])
        return block[:size]
    return SimpleNamespace(read=read, requests=requests,
                           write=lambda packet: writes.append(packet) or len(packet)), queue, writes


def test_complete_partition_response_uses_continuation_headers():
    payload = bytes(range(256)) * (25100288//256)
    driver, queue, writes = response_driver(payload)
    operation = SimpleNamespace(guard_packet=lambda packet: None)
    channel = Channel(driver, operation, lambda *a, **k: None)
    assert channel.exchange(READ, len(payload)+4) == payload
    assert channel.usable and channel.sequence == 2 and not queue and len(writes) == 1
    # 与封存PMCA的原有解帧器交叉验证同一响应，避免测试和实现共享错误假设。
    from pmca.usb.sony import SonySenserDevice
    reference, remaining, _ = response_driver(payload)
    reference.reset = lambda: None
    reference.getId = lambda: (0x054c, 0x0336)
    status, raw = SonySenserDevice(reference).sendSenserPacket(0x40, READ)
    assert status == 0 and raw == struct.pack('<I', 0)+payload and not remaining
    # 相同字节结果不足以证明真实USB行为一致，同时核对参考实现的读取边界。
    assert driver.requests == reference.requests


def test_invalid_continuation_keeps_partial_and_blocks_resend(tmp_path):
    payload = b'x' * (0x100000+17)
    driver, _, writes = response_driver(payload, 'sequence')
    operation = SimpleNamespace(guard_packet=lambda packet: None, output=tmp_path)
    channel = Channel(driver, operation, lambda *a, **k: None)
    with pytest.raises(ValueError):
        channel.exchange(READ, len(payload)+4)
    assert not channel.usable
    partial = (tmp_path/'response-001-partial.bin').read_bytes()
    assert partial == struct.pack('<I', 0) + payload[:0x100000-4]
    with pytest.raises(PermissionError):
        channel.exchange(READ, len(payload)+4)
    assert len(writes) == 1


@pytest.mark.parametrize('action,result,meaning', [
    ('write', 0x10000008, '打开目标文件失败'),
    ('write', 0x10000009, '写入长度不符'),
    ('read', 0x10000006, '元数据查询失败'),
    ('read', 0x10000008, '读取请求被拒绝'),
    ('read', 0x12345678, '未知文件错误'),
])
def test_file_failure_reports_action_path_without_payload_or_retry(action, result, meaning):
    # 固定响应直接来自协议字节，不由待测异常类构造。
    path, secret = '/tmp/jiritsu/a7r5-jit-test.ticket', b'not-for-logs'
    queue = deque([HEADER.pack(4, 0x40, 1, 0, 0, 0, 0), struct.pack('<I', 0),
                   HEADER.pack(4, 0x40, 2, 0, 0, 0, 0), struct.pack('<I', result)])
    writes, logs = [], []
    driver = SimpleNamespace(read=lambda size: queue.popleft(),
                             write=lambda packet: writes.append(packet) or len(packet))
    operation = SimpleNamespace(reads={path: 128}, writes={path: secret}, guard_packet=lambda packet: None)
    channel = Channel(driver, operation, lambda event, **fields: logs.append(dict(event=event, **fields)))
    with pytest.raises(FileResultError) as caught:
        channel.put(path, secret) if action == 'write' else channel.read(path, 128)
    error = caught.value
    assert error.result == result and error.action == action and error.path == path
    assert meaning in str(error) and path in str(error) and f'0x{result:08x}' in str(error)
    assert '不证明不存在' not in str(error) and secret.decode() not in repr(logs)
    failure = next(row for row in logs if row['event'] == 'file_result' and row['result'] != '0x0')
    assert failure['action'] == action and failure['path'] == path
    assert len(writes) == 2 and not queue and channel.usable


@pytest.mark.parametrize('action,path,work_hint',[
    ('write','/tmp/jiritsu/libJit.so',True),
    ('write','/tmp_wbshd/a7r5-control-test.ticket',False),
    ('read','/tmp/jiritsu/libJit.so',False),
])
def test_work_area_hint_does_not_misdiagnose_RAM_or_reads(action,path,work_hint):
    message=str(FileResultError(0x10000008,action=action,path=path))
    assert ('目录项' in message) is work_hint
    assert '0x10000008' in message and path in message
    assert '已满' not in message and '需要格式化' not in message


def test_native_partial_timeout_is_saved_and_no_more_reads_or_packets_are_sent(tmp_path):
    import usb.core
    payload=bytes(range(256))*1024
    real,queue,writes=response_driver(payload)
    reads=[];blocks=0
    error=usb.core.USBTimeoutError('fixture',-7,60)
    def read(size):
        nonlocal blocks
        reads.append(size)
        if size==32768:
            blocks+=1
            if blocks==8:
                error.usb_partial_data=queue.popleft()[:24576]
                error.usb_requested_bytes=32768
                raise error
        return real.read(size)
    operation=SimpleNamespace(guard_packet=lambda packet:None,output=tmp_path)
    channel=Channel(SimpleNamespace(read=read,write=real.write),operation,lambda *a,**k:None)
    with pytest.raises(usb.core.USBTimeoutError):channel.exchange(READ,len(payload)+4)
    saved=(tmp_path/'response-001-partial.bin').read_bytes()
    # 与实测相同：已收253952字节，结果码为0；仍缺8196字节，不能接受为完整响应。
    assert len(saved)==253952 and saved==struct.pack('<I',0)+payload[:253948]
    assert not channel.usable and len(writes)==1
    count=len(reads)
    with pytest.raises(PermissionError):channel.exchange(READ,len(payload)+4)
    assert len(reads)==count and len(writes)==1
