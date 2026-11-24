"""执行冻结上游原生请求、E4构造和九项发送，记录十二款的参数来源。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import zlib

HERE = Path(__file__).resolve().parent
FEATURE = HERE.parents[1]
sys.path.insert(0, str(FEATURE/'dependencies/native12-combined/tests'))
import runtime_support

IDS = (0x4030,0x40f3,0x40f4,0x40f5,0x4031,0x4032,0x40f6,0x40f7)
GETTERS = (0x28c5544,0x28c556c,0x28c5594,0x28c55bc,0x28c55e4,0x28c560c,0x28c5634,0x28c565c)
UPSTREAM_AP = 'bc766baaf1cd617479993afbec526bbc4dd5f6fc62a0f79bf2682abbd1adc222'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Upstream:
    def __init__(self, baseline):
        runtime_support.BASELINE = baseline
        raw = baseline/'patched/appFw.so'
        assert digest(raw) == UPSTREAM_AP
        self.ap = runtime_support.AP(raw.read_bytes())
        self.ms = 0
        self.packets = []
        self.objects = []
        self.callbacks = {}
        for name, callback in (('clock_gettime', self.clock), ('nanosleep', self.sleep)):
            at = self.ap.DATA + 0x50000 + len(self.callbacks)*16
            self.callbacks[name] = at
            self.ap.stub(at, callback)
        self.ap.stub('r5_stage411_dlsym', lambda a:self.callbacks.get(a.string(a.arg(1)),0))
        self.ap.stub('r5_session_current', lambda a:1)
        self.ap.stub('r5_filter_available_mask', lambda a:0xfff)
        for name in ('r5_native_lut_directory_api_init','r5_lut_directory_acquire',
                     'r5_lut_directory_release','r5_filter_selection_save'):
            self.ap.stub(name, lambda a:0)
        self.ap.stub('r5_native_ap_send', self.select)
        self.ap.stub('r5_osal_msg_size', lambda a:32)
        self.ap.stub(0x31a9d04, lambda a:a.DATA+0x51000)
        self.ap.stub(0x16dc130, lambda a:a.DATA+0x10000)
        self.ap.stub(0x326d098, self.enqueue)
        self.ap.stub(0x355882c, self.send)
        self.ap.stub(0x352be50, self.empty_future)
        self.ap.stub(0x352a7e8, lambda a:0)
        for at in (0x30c01dc,0x2e7d208,0x2e7cee4,0x16dcc90,0x30bf16c,
                   0x352132c,0x17fc5d4,0x17fc630,0x30bedb0,0x36951e0,
                   0x36952a0,0x369448c):
            self.ap.stub(at,lambda a:0)
        self.ap.stub(0x35b858c, self.error)
        self.ap.call('r5_filter_bank_ready', 1, 123, 0xfff)

    def clock(self, ap):
        ap.write(ap.arg(1),struct.pack('<qq',self.ms//1000,self.ms%1000*1000000))
        return 0

    def sleep(self, ap):
        sec,ns=struct.unpack('<qq',ap.read(ap.arg(0),16))
        self.ms+=sec*1000+ns//1000000
        return 0

    def select(self, ap):
        assert ap.arg(2)==32
        ack=bytearray(ap.read(ap.arg(1),32))
        ack[2]=0x81
        struct.pack_into('<I',ack,24,0)
        struct.pack_into('<I',ack,28,zlib.crc32(ack[:28]+bytes(4)))
        at=ap.DATA+0x52000
        ap.write(at,ack)
        ap.pending.append(('r5_filter_inbound',(at,0x90030001)))
        return 0

    def enqueue(self, ap):
        obj=ap.arg(1)
        self.objects.append(ap.read(obj,0x38).hex())
        ap.pending.append(('r5_filter_refresh_execute425',(obj,)))
        return 0

    def send(self, ap):
        assert ap.arg(0)==0x90030001 and ap.arg(2)==12
        self.packets.append(ap.read(ap.arg(1),12))
        return 0

    def empty_future(self, ap):
        ap.write(ap.arg(0),bytes(24))
        ap.write(ap.arg(2),bytes(16))
        return 0

    def error(self, ap):
        raise AssertionError(('原生错误处理',tuple(ap.arg(i) for i in range(3))))

    def configure(self, mode, base, values):
        ap=self.ap
        ap.write(ap.call(0x28d6fd0),struct.pack('<I',mode))
        ap.write(ap.call(0x28ae4b0),struct.pack('<I',base))
        ap.write(ap.call(0x28b2c10),struct.pack('<I',base))
        ap.write(ap.call(0x28ada88),struct.pack('<I',1))
        for getter,value in zip(GETTERS,values):
            # 写入受控的原厂工作状态；getter、模型索引和构造器保持原函数。
            for n in range(18):
                ap.write(ap.call(getter)+4*n,struct.pack('<i',value))
                ap.write(ap.call(getter+20)+24*n+16,struct.pack('<i',value))

    def choose(self, slot):
        self.packets=[]
        self.objects=[]
        assert self.ap.call('r5_filter_request',slot)==0
        self.ap.call('r5_filter_service')
        assert self.ap.call('r5_filter_command_state')==2
        assert len(self.packets)==9 and len(self.objects)==1
        delivered={struct.unpack_from('<H',p,2)[0]:struct.unpack_from('b',p,8)[0] for p in self.packets}
        return dict(slot=slot,values=[delivered[prop] for prop in IDS],
                    packets=[p.hex() for p in self.packets],object_hex=self.objects[0])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    assert not args.output.exists()
    upstream=Upstream(args.baseline)
    runtime_support.BASELINE=args.candidate
    current=runtime_support.AP((args.candidate/'appFw.so').read_bytes())
    identities={}
    for name,at,length in (('E4_constructor',0x318e5c0,0x370),
                           ('E4_executor',0x348292c,0x160),
                           ('native_parameter_getters',0x28c54cc,0x1b8)):
        original=upstream.ap.read(at,length)
        assert original==current.read(at,length),name
        identities[name]=hashlib.sha256(original).hexdigest()
    rows=[]
    scenarios=(('ST_reference',0,0,(0,0,0,0,0,4,3,1)),
               ('ST_working_changed',0,0,(2,-1,3,1,-2,6,2,4)),
               ('factory_3_working_changed',0,3,(-2,2,-3,2,1,5,4,2)),
               ('mode_1_working_changed',1,1,(1,-2,2,0,-1,7,5,3)))
    for name,mode,base,values in scenarios:
        upstream.configure(mode,base,values)
        looks=[upstream.choose(slot) for slot in range(1,13)]
        assert all(tuple(row['values'])==values for row in looks)
        rows.append(dict(name=name,native_mode_flag=mode,native_base=base,
                         controlled_working_values=list(values),filters=looks))
    os.environ['A7R5_NATIVE24_BUILD']=str(args.candidate)
    sys.path.insert(0,str(FEATURE/'tests'))
    from test_native_e4_parameters import NativeE4Replay
    from test_parameters import display_custom, parameters
    from replay import recipe
    formal=FEATURE/'dependencies/native12-combined/upstream/filters/FUJ_12_v45/R5NATIVE.BIN'
    assert digest(formal)=='19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6'
    assert formal.read_bytes()[128:]==recipe()[128:128+12*2452]

    class CapturedReplay(NativeE4Replay):
        def refresh(self, ap):
            obj=ap.DATA+0x79000
            ap.write(obj,self.source_object)
            ap.pending.extend([
                ('r5_filter_refresh_construct425',(obj,ap.arg(0)+16)),
                ('r5_filter_refresh_execute425',(obj,)),
            ])
            return 0

    # 每组状态使用全新运行态，验证首次应用。配方字节和CP参数接收保持真实。
    result_rows=[]
    for row in rows:
        replay=CapturedReplay()
        replay.source_object=bytes.fromhex(row['filters'][0]['object_hex'])
        replay.boot()
        compared=[]
        for look in row['filters']:
            slot=look['slot']
            replay.source_object=bytes.fromhex(look['object_hex'])
            display_custom(replay,slot)
            before=len(replay.native_packets)
            replay.choose(slot)
            replay.service()
            assert replay.ap.call('r5_filter_command_state')==2
            actual=replay.native_packets[before:]
            expected=[bytes.fromhex(p) for p in look['packets']]
            assert actual==expected, (row['name'],slot,'原生消息字节不同')
            assert tuple(replay.cp_values())==tuple(row['controlled_working_values'])
            assert parameters(replay,slot)==tuple(row['controlled_working_values'])
            compared.append(slot)
        result_rows.append(dict(name=row['name'],slots=compared,all_nine_packets_exact=True))
    result=dict(schema='upstream-native-eight-parameter-probe/1',status='PASS',
                upstream_AP_sha256=UPSTREAM_AP,candidate_AP_sha256=digest(args.candidate/'appFw.so'),
                unchanged_native_functions=identities,scenarios=rows,
                candidate_comparison=result_rows,
                formal_recipe_sha256=digest(formal),first_twelve_records_exact=True,
                native_E4_executions=48,native_packets=432,camera_io=False,
                boundary='真实上游AP请求、构造、执行与消息打包；配置工作状态、锁、调度队列、CP选择ACK和存储为夹具。ST_reference为受控输入，不代表读取了机身设置。',
                conclusion='十二款不各自固定八项参数，原生E4读取当前原厂外观的工作参数。')
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','native_E4_executions','native_packets','camera_io')}))


if __name__=='__main__':
    main()
