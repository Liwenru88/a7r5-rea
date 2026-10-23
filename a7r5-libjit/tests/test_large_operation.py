"""真实加载库长度的整条任务协议回归；先验证大响应，再允许两次固定上传。"""
from collections import deque
import hashlib
import json
from pathlib import Path
import pytest
from test_contract import bundle, WireDriver
from operation import Operation

ROOT=Path(__file__).resolve().parents[1]
from references import loader_path
LIBRARY=loader_path(ROOT).read_bytes()


class ChunkedService(WireDriver):
    def __init__(self,operation,fault):
        super().__init__(operation)
        self.queue=deque();self.large_read=False;self.fault_case=fault
        original=self.service.read
        def file_read(path,limit):
            if path=='/usr/lib/libJiritsu.so':
                return (b'X'+LIBRARY[1:]) if fault=='bad-content' else LIBRARY
            return original(path,limit)
        self.service.read=file_read

    def write(self,packet):
        assert not self.queue,'未消费完上一响应，不允许下一请求'
        n=super().write(packet)
        self.queue.append(self.reply[:12]);body=self.reply[12:];self.reply=b''
        for offset in range(0,len(body),32768):
            block=body[offset:offset+32768];self.queue.append(block)
            if len(block)%512==0 and self.fault_case!='missing-zlp':self.queue.append(b'')
        if len(body)==233420:self.large_read=True
        return n

    def read(self,n):
        if not self.queue:raise TimeoutError('模拟响应截断')
        raw=self.queue.popleft();count=n if n==12 else min(n,503)
        if raw[count:]:self.queue.appendleft(raw[count:])
        return raw[:count]


@pytest.mark.parametrize('fault',[None,'missing-zlp','bad-content'])
def test_large_loader_gate_precedes_any_upload(tmp_path,fault):
    assert len(LIBRARY)==233416
    assert hashlib.sha256(LIBRARY).hexdigest()=='ea2d9ba9dbeb56fc11ad88be7b5c30b6b237f8ccc55ce9f24c02546eb0ba07b1'
    path=bundle(tmp_path/'bundle');config=json.loads((path/'config.json').read_text())
    config.update(loader_bytes=len(LIBRARY),loader_sha256=hashlib.sha256(LIBRARY).hexdigest())
    (path/'config.json').write_text(json.dumps(config))
    operation=Operation(path);driver=ChunkedService(operation,fault);out=tmp_path/'out';out.mkdir()
    report={};events=[]
    def log(event,**details):events.append((event,details))
    if fault:
        with pytest.raises(ValueError):operation(driver,out,log,report)
        assert not operation.safe_to_stop and report['fixed_writes_attempted']==report['trigger_attempts']==0
        assert driver.service.writes==[]
    else:
        operation(driver,out,log,report)
        assert operation.safe_to_stop and report['fixed_writes_attempted']==2 and report['trigger_attempts']==1
        assert (out/'loader.bin').read_bytes()==LIBRARY and not driver.queue
        assert len([d for e,d in events if e=='response_block_boundary' and d['sequence']==4])==7
    assert driver.large_read and not report['preload_written'] and not report['debug_commands_sent']
