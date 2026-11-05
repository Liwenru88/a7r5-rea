"""私有刷新通知不得写入Look；其他页面／事件必须继续原处理器。"""
import ctypes as C
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
import environment
from elftools.elf.elffile import ELFFile

MODULE=environment.ROOT/'a7r5-firmware-features/native24-combined/dependencies/native12-combined'


class EventGuardContract(unittest.TestCase):
    def test_private_refresh_is_consumed_and_other_traffic_is_forwarded(self):
        with tempfile.TemporaryDirectory(prefix='e4-event-contract-',dir=environment.LAB/'build') as temporary:
            folder=Path(temporary);source=folder/'contract.c'
            source.write_text('''#include <string.h>
#define NATIVE12_E4_COMPAT_HOST
unsigned char native12_private_page_state[64];
static unsigned char controller[512];
static unsigned calls;
unsigned long native12_dispatch_original(unsigned long c,unsigned long m,unsigned long e){(void)c;(void)m;(void)e;calls++;return 17;}
#include "e4-menu-compat.c"
unsigned probe(unsigned event,unsigned owned,unsigned page,unsigned manager,unsigned active){
 memset(native12_private_page_state,0,64);memset(controller,0,512);calls=0;
 *(unsigned *)(native12_private_page_state+4)=active;
 *(unsigned long *)(native12_private_page_state+32)=owned?(unsigned long)controller:0;
 *(unsigned long *)(native12_private_page_state+48)=manager;
 *(unsigned *)(controller+0x178)=page;*(unsigned long *)(controller+0x180)=manager;
 return (unsigned)native12_e4_dispatch((unsigned long)controller,0,event);
}
unsigned original_calls(void){return calls;}
''')
            result=subprocess.run(['/usr/bin/clang','-shared','-fPIC','-O2','-I',str(MODULE),str(source),'-o',str(folder/'contract.dylib')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);lib=C.CDLL(str(folder/'contract.dylib'))
            lib.probe.argtypes=[C.c_uint]*5
            # 活动及已退休的私有对象均不得再次写原厂Look；普通页面/事件原样转发。
            for event,owned,page,manager,active,result,calls in (
                (0x20f0001,1,0xd9,3,1,1,0),(0x20f0001,1,0xd9,3,0,1,0),
                (0x20f0001,0,0xd9,3,1,17,1),(0x20f0001,1,0x40,3,1,17,1),
                (0x20f0001,1,0xd9,0,1,17,1),(0x20f0000,1,0xd9,3,1,17,1),
                (0x2010003,1,0xd9,3,1,17,1)):
                with self.subTest(event=hex(event),owned=owned,page=page,active=active):
                    self.assertEqual(lib.probe(event,owned,page,manager,active),result)
                    self.assertEqual(lib.original_calls(),calls)

    def test_overlay_is_bounded_exactly_reversible_and_rejects_unknown_image(self):
        spec=importlib.util.spec_from_file_location('e4_menu_contract',MODULE/'e4_menu_compat.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        raw=(environment.LAB/'build/native12-e4-411-frequency-20261102-01/font/appFw.so').read_bytes()
        with tempfile.TemporaryDirectory(prefix='e4-patch-contract-',dir=environment.LAB/'build') as temporary:
            folder=Path(temporary)
            with self.assertRaisesRegex(ValueError,'完整前像'):module.build(raw[:-1],folder/'bad')
            self.assertFalse((folder/'bad').exists())
            path,receipt=module.build(raw,folder/'valid');changed=path.read_bytes()
            self.assertEqual(module.sha(changed),environment.E4_AP_SHA)
            self.assertEqual(len(changed),len(raw));self.assertEqual(receipt['code_bytes'],104)
            inverse=bytearray(changed);intervals=[]
            for patch in receipt['patches']:
                at=patch['offset'];before=bytes.fromhex(patch['before']);after=bytes.fromhex(patch['after'])
                self.assertEqual(raw[at:at+len(before)],before);self.assertEqual(changed[at:at+len(after)],after)
                self.assertTrue(all(at+len(after)<=lo or hi<=at for lo,hi in intervals));intervals.append((at,at+len(after)))
                inverse[at:at+len(before)]=before
            self.assertEqual(inverse,raw)
            # 原E4与九个分派代码逐字节保持。
            elf=ELFFile(io.BytesIO(raw))
            for va in (0x348292c,*[0x350927c+64*n for n in range(9)]):
                segment=next(s for s in elf.iter_segments() if s['p_type']=='PT_LOAD' and s['p_vaddr']<=va<s['p_vaddr']+s['p_filesz'])
                at=segment['p_offset']+va-segment['p_vaddr']
                self.assertEqual(changed[at:at+64],raw[at:at+64])


if __name__=='__main__':unittest.main()
