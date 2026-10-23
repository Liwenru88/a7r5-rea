"""固定文件通道；有完整响应才恢复同步标志，异常不重传。"""
import struct
import hashlib
HEADER=struct.Struct('<IHHBBBB')
READ=struct.pack('<HH',0x1001,17)+b'\0\xff\0'

class FileResultError(ValueError):
    def __init__(self,result):
        self.result=result;super().__init__(f'文件结果0x{result:08x}，不证明不存在')

def wire(path):
    return (path if path.startswith('/tmp/jiritsu/') else '/tmp/jiritsu/../..'+path).encode()

class Channel:
    def __init__(self,driver,operation,log):
        self.driver,self.operation,self.log=driver,operation,log
        self.sequence,self.usable=1,True
    def exchange(self,body,limit):
        if not self.usable or self.sequence>512:raise PermissionError('失步或报文超限，不再发送')
        self.usable=False
        packet=HEADER.pack(len(body),0x40,self.sequence,0,0,0,0)+body
        self.operation.permitted_packet=packet
        try:
            self.operation.guard_packet(packet)
            if self.driver.write(packet)!=len(packet):raise OSError('短写，不重传')
        finally:self.operation.permitted_packet=None
        raw=self.driver.read(HEADER.size)
        self.log('response_header',raw_hex=raw.hex(),sequence=self.sequence,limit=limit)
        if len(raw)!=HEADER.size:raise ValueError('响应头长度异常')
        size,function,sequence,version,micon,offset,status=HEADER.unpack(raw)
        if function!=0x40 or sequence!=self.sequence or not 4<=size<=limit or status:raise ValueError('响应头字段异常')
        data=bytearray()
        try:
            # Senser0336契约：每个最多0x8000字节逻辑块独立结束，整512块后必须消费ZLP。
            while len(data)<size:
                block_start=len(data)
                block_end=min(block_start+0x8000,size)
                while len(data)<block_end:
                    requested=min(4096,block_end-len(data))
                    chunk=self.driver.read(requested)
                    self.log('response_body_fragment',sequence=self.sequence,offset=len(data),
                             requested=requested,received=len(chunk),block_end=block_end)
                    if not chunk or len(chunk)>requested:raise ValueError('响应体边界异常')
                    data.extend(chunk)
                block_size=block_end-block_start
                if block_size%512==0:
                    boundary=self.driver.read(512)
                    self.log('response_block_boundary',sequence=self.sequence,offset=len(data),received=len(boundary))
                    if boundary!=b'':raise ValueError('缺少分块空边界包')
        except BaseException as exc:
            self.log('response_body_failed',sequence=self.sequence,received=len(data),expected=size,
                     partial_sha256=hashlib.sha256(data).hexdigest(),error=type(exc).__name__+': '+str(exc))
            output=getattr(self.operation,'output',None)
            if output is not None:(output/f'response-{self.sequence:03}-partial.bin').write_bytes(data)
            raise
        self.sequence+=1;self.usable=True
        result,=struct.unpack_from('<I',data)
        self.log('file_result',result=hex(result),bytes=size-4,version=version,micon=micon,offset=offset)
        if result:raise FileResultError(result)
        return bytes(data[4:])
    def select(self,path):self.exchange(struct.pack('<HH',0x1001,15)+b'\0'+wire(path)+b'\0',4)
    def read(self,path,limit):
        if self.operation.reads.get(path)!=limit:raise PermissionError('不是固定读取')
        self.select(path);return self.exchange(READ,limit+4)
    def put(self,path,data):
        if self.operation.writes.get(path)!=data:raise PermissionError('不是固定写入')
        self.select(path)
        if self.exchange(struct.pack('<HH',0x1001,16)+b'\0\xff\0'+data,4):raise ValueError('额外写入回执')
