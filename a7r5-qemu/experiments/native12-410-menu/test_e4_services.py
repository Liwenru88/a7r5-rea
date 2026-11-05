"""回放真实缺失请求，验证动态上下文、拒绝和消息交付失败的状态语义。"""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest
import environment

HARNESS=r'''
#include <stdio.h>
#include <string.h>
static unsigned char area[1],reply[64];
static void *n12_mailbox=area;
static unsigned input_size,input_source,sends,request_frees,reply_frees,reply_source;
static int send_error;
static int pending_notify_mode;
static void *current;
static char *test_env(const char *name){return !strcmp(name,"A7R5_N12_E4_SERVICES")||(!strcmp(name,"A7R5_N12_PENDING_NOTIFY")&&pending_notify_mode)?"1":0;}
#define getenv test_env
static unsigned msg_size(void *p){(void)p;return input_size;}
static unsigned get_source(void *p){(void)p;return input_source;}
static int allocate(unsigned q,void **p,unsigned n,unsigned count){if(q!=input_source||(n!=12&&n!=16)||count!=1)return -98;*p=reply;return 0;}
static void source(void *p,unsigned s){if(p==reply)reply_source=s;}
static int send(unsigned q,void *p){if(q!=input_source||p!=reply)return -97;sends++;return send_error;}
static int release(unsigned q,void *p){(void)q;if(p==current)request_frees++;else if(p==reply)reply_frees++;return 0;}
static unsigned (*real_msg_size)(void *)=msg_size,(*real_get_source)(void *)=get_source;
static int (*real_allocate_msg)(unsigned,void **,unsigned,unsigned)=allocate;
static void (*real_set_source)(void *,unsigned)=source;
static int (*real_send_msg)(unsigned,void *)=send,(*real_free_msg)(unsigned,void *)=release;
static void record(const char *a,const char *b){(void)a;(void)b;}
#include "e4-services.inc"
static int handled;
int invoke(void *p,unsigned n,unsigned src,unsigned dest){current=p;input_size=n;input_source=src;sends=request_frees=reply_frees=reply_source=0;memset(reply,0,sizeof reply);return native12_native_send(dest,p,&handled);}
unsigned stat(unsigned n){unsigned v[]={handled,sends,request_frees,reply_frees,reply_source,n12_touch_enabled,n12_imaging_locks,n12_notify_pending!=0};return n<8?v[n]:0;}
void reset(void){send_error=pending_notify_mode=0;n12_notify_pending=0;n12_aux_configured=n12_touch_enabled=n12_imaging_locks=n12_output_selection=n12_output_configured=0;}
void enable_pending(void){pending_notify_mode=1;}
void fail_delivery(void){send_error=-99;}
void read_reply(void *p){memcpy(p,reply,12);}
'''


class NativeE4ServiceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='native12-e4-contract-',dir=environment.LAB/'build')
        folder=Path(cls.temp.name);source=folder/'service.c';source.write_text(HARNESS)
        result=subprocess.run(['/usr/bin/clang','-shared','-fPIC','-O2','-I',str(Path(__file__).parent),str(source),'-o',str(folder/'service.dylib')],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr)
        cls.lib=C.CDLL(str(folder/'service.dylib'))
        cls.lib.invoke.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.c_uint]
        cls.lib.stat.argtypes=[C.c_uint];cls.lib.stat.restype=C.c_uint
        cls.lib.read_reply.argtypes=[C.c_void_p]

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):self.lib.reset()

    def request(self,hexadecimal,source=0x80020002,dest=0x90040193):
        raw=bytes.fromhex(hexadecimal);p=C.create_string_buffer(raw)
        rc=self.lib.invoke(p,len(raw),source,dest);reply=C.create_string_buffer(12);self.lib.read_reply(reply)
        return rc,bytes(reply),[self.lib.stat(i) for i in range(7)]

    def test_observed_touch_and_dynamic_imaging_context_are_accepted(self):
        rc,reply,s=self.request('0d2046010a0001800100',0x81cf6197,0x92840747)
        self.assertEqual((rc,reply,s[:3],s[5]),(0,bytes.fromhex('0d2046110c00018000000000'),[1,1,1],1))
        for context in (2,3):
            with self.subTest(context=context):
                raw=f'05003d40{context:02x}0000800080000001000000'
                rc,reply,s=self.request(raw)
                self.assertEqual((rc,reply,s[:3],s[6]),(0,bytes.fromhex('110000003d40000000f00000'),[1,1,1],0x8000))

    def test_bad_input_or_foreign_queue_never_changes_state_or_sends_completion(self):
        for packet,source in [('05003d40030000800100000001000000',0x80020002),
                              ('05003d40030000800080000002000000',0x80020002),
                              ('05003d40000000000080000001000000',0x80020002),
                              ('05003d40030000800080000001000000',0x80020003)]:
            with self.subTest(packet=packet,source=source):
                rc,_,s=self.request(packet,source)
                self.assertNotEqual(rc,0);self.assertEqual((s[1],s[2],s[6]),(0,0,0))
        _,_,s=self.request('05003e40030000800080000001000000')
        self.assertEqual(s[:3],[0,0,0])

    def test_delivery_failure_preserves_state_and_request_ownership(self):
        self.lib.fail_delivery()
        rc,_,s=self.request('0d2046010a0001800100',0x81cf6197,0x92840747)
        self.assertEqual((rc,s[1:4],s[5]),(-99,[1,0,1],0))

    def test_observed_virtual_display_and_auxiliary_requests_deliver_owned_completions(self):
        cases=[
            ('00250a010c00010000000000',0x81cf619b,0x909a015a,'00250a810c00010000000000'),
            ('00250101100001000000000006000000',0x81cf619b,0x909a015a,'002501810c00010000000000'),
            ('002517010c00010002110211',0x81cf619b,0x909a015a,'002517810c00010000000000'),
            ('0d2049010a0001800100',0x81cf619b,0x92840747,'0d2049110c00018000000000'),
            ('0d2021030c00018000000000',0x81cf619b,0x92840747,'0d2021130c00018000000000'),
            ('0d2034030e000180000200000000',0x81cf619b,0x92840747,'0d2034130c00018000000000'),
            ('0d202b031a000180000001000101010100000000000000000000',0x81cf619b,0x92840747,'0d202b130c00018000000000'),
            ('00002c300400008000000000000000000000000000000000',0x80020002,0x90030001,'110000002c30000000f00000'),
            ('050073400400008000000000',0x80020002,0x90030001,'110000007340000000f00000'),
            ('000003300400008000000000000000000000000000000000',0x80020002,0x90030001,'110000000330000000f00000')]
        for packet,source,dest,completion in cases:
            with self.subTest(packet=packet):
                rc,reply,s=self.request(packet,source,dest)
                self.assertEqual((rc,reply,s[:3]),(0,bytes.fromhex(completion),[1,1,1]))

    def test_unsupported_notify_on_and_malformed_output_never_return_success(self):
        cases=[('050073400400008001000000',0x80020002,0x90030001),
               ('00002c300000000000000000000000000000000000000000',0x80020002,0x90030001),
               ('002517010c00010002110311',0x81cf619b,0x909a015a),
               ('00250a010c00010004000000',0x81cf619b,0x909a015a),
               ('0d202b031a000180000001000101010100000000000000000001',0x81cf619b,0x92840747)]
        for packet,source,dest in cases:
            with self.subTest(packet=packet):
                rc,_,s=self.request(packet,source,dest)
                self.assertNotEqual(rc,0);self.assertEqual(s[:4],[1,0,0,0])

    def test_explicit_pending_model_retains_only_one_exact_request_without_completion(self):
        self.lib.enable_pending()
        rc,reply,s=self.request('050073400400008001000000',0x80020002,0x90030001)
        self.assertEqual((rc,reply,s[:4],self.lib.stat(7)),(0,bytes(12),[1,0,0,0],1))
        rc,_,s=self.request('050073400500008001000000',0x80020002,0x90030001)
        self.assertEqual((rc,s[:4],self.lib.stat(7)),(-1024,[1,0,0,0],1))
        for packet,source in [('050073400400008001000000',0x80020003),
                              ('050073400000008001000000',0x80020002),
                              ('050073400400008001000001',0x80020002)]:
            self.lib.reset();self.lib.enable_pending()
            rc,_,s=self.request(packet,source,0x90030001)
            self.assertNotEqual(rc,0);self.assertEqual((s[1:4],self.lib.stat(7)),([0,0,0],0))

    def test_output_config_accepts_both_observed_field9_forms_only(self):
        for field,expected in ((0,0),(1,0),(2,-1024)):
            raw=bytearray.fromhex('0d201801160001800301000000000000000000000100');raw[9]=field
            rc,_,s=self.request(raw.hex(),0x81cf6185,0x92840747)
            self.assertEqual(rc,expected)
            self.assertEqual(s[1],int(field<2))


if __name__=='__main__':unittest.main()
