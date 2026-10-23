"""按已存PMCA契约构造32KiB分块，而不是沿用生产解析器的布局。"""
from collections import deque
import hashlib
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from transport import Channel,HEADER,READ

class Permit:
    permitted_packet=None
    def guard_packet(self,packet):assert packet==self.permitted_packet

class Segmented:
    def __init__(self,body,fault=None,short=False):
        self.requests=[];self.events=deque([HEADER.pack(len(body),0x40,1,3,0,0,0)])
        self.short=short
        for start in range(0,len(body),32768):
            chunk=body[start:start+32768];self.events.append(chunk)
            if len(chunk)%512==0:
                if fault=='boundary-nonempty':self.events.append(b'FOREIGN')
                elif fault!='missing-boundary':self.events.append(b'')
        if fault=='unexpected-empty':self.events.insert(2,b'')
        if fault=='truncated':self.events=deque(list(self.events)[:-1])
    def write(self,packet):self.requests.append(packet);return len(packet)
    def read(self,n):
        if not self.events:raise TimeoutError('synthetic truncated transfer')
        current=self.events.popleft()
        count=min(n,113) if self.short and n!=HEADER.size else n
        raw=current[:count]
        if current[count:]:self.events.appendleft(current[count:])
        return raw

@pytest.mark.parametrize('size',[4,23,512,32768,32769,65536,233420])
@pytest.mark.parametrize('short',[False,True])
def test_segmented_response_fully_consumed_without_request_retransmission(size,short):
    body=b'\0'*4+(bytes(range(256))*((size+255)//256))[:size-4]
    driver=Segmented(body,short=short);events=[]
    channel=Channel(driver,Permit(),lambda e,**d:events.append((e,d)))
    actual=channel.exchange(READ,size)
    assert hashlib.sha256(actual).digest()==hashlib.sha256(body[4:]).digest()
    assert len(driver.requests)==1 and not driver.events and channel.sequence==2

@pytest.mark.parametrize('fault',['missing-boundary','boundary-nonempty','unexpected-empty','truncated'])
def test_bad_block_boundaries_stop_without_followup_or_retransmission(fault):
    driver=Segmented(b'\0'*4+b'A'*70000,fault)
    channel=Channel(driver,Permit(),lambda *a,**k:None)
    with pytest.raises((ValueError,TimeoutError)):channel.exchange(READ,70004)
    before=len(driver.requests)
    with pytest.raises(PermissionError):channel.exchange(READ,70004)
    assert before==len(driver.requests)==1 and not channel.usable
