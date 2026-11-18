"""宿主执行同一guard控制逻辑；MRC、地址及原服务仅作显式宿主适配，不执行ARM。"""
from pathlib import Path
import argparse, ctypes as C, hashlib, io, json, struct, subprocess, sys

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
sys.path.insert(0,str(ROOT/'a7r5-desktop/prepared/engine/site'))
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_ARM,CS_MODE_THUMB
import memory_plan as P

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--memory-plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();build=args.build.resolve();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'.local/fixed-custom-filters'):raise ValueError('只允许任务隔离输出')
    if out.exists():raise ValueError('宿主回执已存在')
    out.mkdir()
    module=json.loads((build/'verification.json').read_text())
    rx_n=module['RX_bytes'];rw_n=module['RW_bytes']
    if not 0<rx_n<=4096 or not 0<rw_n<=0x4bc or rw_n%4 or module.get('phase_address')!=hex(0x1a3ab40+rw_n):
        raise ValueError('载荷与phase范围不符')
    source=(HERE/'bootstrap/guard.c').read_text()
    replacements={
        '#define PHASE (*(volatile uint32_t *)AF_PHASE_ADDRESS)':'#define PHASE h_phase',
        '(const uint32_t *)0xce0354u':'h_table',
        '__asm__ volatile("mrc p15,0,%0,c1,c0,0":"=r"(control));':'control=h_control;',
        '__asm__ volatile("mrc p15,0,%0,c2,c0,0":"=r"(root));':'root=h_root;',
        '__asm__ volatile("mrc p15,0,%0,c2,c0,2":"=r"(split));':'split=h_split;',
        '*(volatile uint32_t *)(0x1a3c000u+0x1au*4u)':'h_l1',
        '*(volatile uint32_t *)0x1a410ecu':'h_pte',
        '(const void *)0x1a3b000u':'(const void *)h_rx',
        '(void *)0x1a3b000u':'(void *)h_rx',
        '(const void *)0x11d2000u':'(const void *)h_source',
        '(void *)0x1a3ab40u':'(void *)h_rw',
        '*(volatile uint32_t *)0x1a3ab40u':'h_rw[0]',
    }
    for old,new in replacements.items():
        if old not in source:raise ValueError('宿主适配锚点漂移: '+old)
        source=source.replace(old,new)
    prefix=f'''#include <stdint.h>
#include <string.h>
uint32_t h_phase,h_control,h_root,h_split,h_l1,h_pte,h_table[256],h_rw[{rw_n//4}];
uint8_t h_rx[{rx_n}],h_source[{rx_n}];
unsigned h_copy,h_zero,h_d,h_i;
'''
    suffix='''
void stock_copy(void *dst,const void *src,uint32_t n){ ++h_copy;memcpy(dst,src,n); }
void stock_zero(void *dst,uint32_t n){ ++h_zero;memset(dst,0,n); }
void stock_dcache(void *cache){ (void)cache;++h_d; }
void stock_icache(void *cache){ (void)cache;++h_i; }
'''
    (out/'guard-host.c').write_text(prefix+source+suffix)
    native=ROOT/'a7r5-firmware-features/custom-filters/native'
    cmd=['clang','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-I'+str(build),'-I'+str(native),
         str(out/'guard-host.c'),str(native/'af_cp_override406.c'),str(native/'af_slots.c'),'-o',str(out/'guard.dylib')]
    run=subprocess.run(cmd,capture_output=True,text=True)
    if run.returncode:raise ValueError(run.stderr)
    lib=C.CDLL(str(out/'guard.dylib'))
    def scalar(name):return C.c_uint32.in_dll(lib,'h_'+name)
    def array(name,n,t=C.c_uint8):return (t*n).in_dll(lib,'h_'+name)
    rx=array('rx',rx_n);src=array('source',rx_n);rw=array('rw',rw_n//4,C.c_uint32)
    paired=json.loads(Path(module['module_receipt']).read_text())
    expected=(ROOT/paired['payloads'][0]['path']).read_bytes()
    expected_rw=(ROOT/paired['payloads'][1]['path']).read_bytes()
    if len(expected)!=rx_n or len(expected_rw)!=rw_n:raise ValueError('宿主数组与实际ELF载荷不符')
    reader=P.load_module(ROOT/'a7r5-firmware-features/custom-filters/experiments/packaging406/check_placement.py','host_guard_fixed_cp')
    cp=reader.read_cpio(ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio',{'cp/cpapp-b.bin'})['cp/cpapp-b.bin']
    if P.sha(cp)!=P.CP_SHA:raise ValueError('宿主黄金源CP不符')
    table_bytes=cp[0xce0354-P.BASE:0xce0354-P.BASE+1024]
    values=struct.unpack('<256I',table_bytes)
    independent=[]
    for k in range(256):
        value=k<<24
        for _ in range(8):value=((value<<1)^(0x04c11db7 if value&0x80000000 else 0))&0xffffffff
        independent.append(value)
    assert values==tuple(independent)
    array('table',256,C.c_uint32)[:]=values
    cases=[]
    def reset():
        for n,v in dict(phase=2,control=1,root=0x1a3c000,split=0,l1=0x1a41011,pte=0x1a3b073,
                        copy=0,zero=0,d=0,i=0).items():scalar(n).value=v
        rx[:]=bytes([0x5a])*rx_n;src[:]=expected;rw[:]=[0xabababab]*(rw_n//4)
    def record(name):cases.append(dict(name=name,status='PASS'))
    lib.af_boot34_prepare.restype=C.c_uint32
    reset();assert lib.af_boot34_prepare()==0
    assert bytes(rx)==expected and bytes(rw)==expected_rw and scalar('phase').value==1
    assert scalar('copy').value==scalar('zero').value==1
    lib.af_boot34_cache(None);assert scalar('phase').value==2 and scalar('d').value==scalar('i').value==1
    lib.af_boot34_cache(None);assert scalar('d').value==2 and scalar('i').value==1
    record('cold_crc_copy_explicit_RW_and_cache_phase')
    for pte in (0x1a3b073,0x1a3b63e):
        reset();scalar('pte').value=pte;rx[:]=expected;src[:]=bytes(rx_n)
        assert lib.af_boot34_prepare()==0 and scalar('phase').value==1
        assert scalar('copy').value==0 and bytes(rw)==expected_rw
    record('warm_verified_RX_reused_without_source_both_supported_PTEs')
    for pte in (0x1a3b073,0x1a3b63e):
        reset();scalar('pte').value=pte;src[37]^=1;before=bytes(rx);before_rw=bytes(rw)
        assert lib.af_boot34_prepare()==0 and scalar('phase').value==0
        assert bytes(rx)==before and bytes(rw)==before_rw and not scalar('copy').value
        lib.af_boot34_cache(None);assert not scalar('i').value and scalar('phase').value==0
    record('invalid_source_or_readonly_bad_RX_no_publication')
    guards=[('control',0),('root',0x1a40000),('split',1),('l1',0),
            ('pte',0x1a3b003),('pte',0x1a3b41f),('pte',0x1a3b63f),('pte',0x1a3a073)]
    for name,value in guards:
        reset();scalar(name).value=value;before=bytes(rx);before_rw=bytes(rw)
        assert lib.af_boot34_prepare()==0 and scalar('phase').value==0
        assert bytes(rx)==before and bytes(rw)==before_rw and not scalar('copy').value and not scalar('zero').value
    record('MMU_root_split_unknown_AP_attributes_or_physical_page_rejected')
    plan=json.loads(args.memory_plan.read_text())
    # 实际118B同源窗口交给产品C校验器；不以模拟状态冒充原trylock。
    old=cp[0x5e3ed4-P.BASE:0x5e3ed4-P.BASE+8]
    assert old[:8]==bytes.fromhex('10402de90000a0e3')
    snapshot=bytes.fromhex(next(r['before'] for r in plan['patches'] if r['address']==0x89856c))
    full=bytearray(cp[0x898548-P.BASE:0x898548-P.BASE+118]);gate=next(r for r in plan['patches'] if r['address']==0x89856c)
    assert full[36:44]==snapshot;full[36:44]=bytes.fromhex(gate['after'])
    data=(C.c_uint8*118).from_buffer_copy(full)
    lib.af_cp_override406_hook_matches.argtypes=[C.c_void_p,C.c_size_t,C.c_uint32]
    assert lib.af_cp_override406_hook_matches(data,118,0xbefb35)==1
    assert lib.af_cp_override406_hook_matches(data,118,paired['symbols']['af_cp_override406_snapshot_gate'])==0
    full[45]^=1;data=(C.c_uint8*118).from_buffer_copy(full)
    assert lib.af_cp_override406_hook_matches(data,118,0xbefb35)==0
    for row in plan['patches']:
        if row['address'] in (0x5e3ed8,0x5e8178):
            decoded=list(Cs(CS_ARCH_ARM,CS_MODE_ARM).disasm(bytes.fromhex(row['after']),row['address']))
            assert len(decoded)==1 and decoded[0].mnemonic=='blx'
    record('ARM_BLX_decoded_and_actual_118B_C_gate_validation')
    result=dict(status='PASS_HOST_LOGIC_ONLY',cases=cases,guard_source_sha256=hashlib.sha256((HERE/'bootstrap/guard.c').read_bytes()).hexdigest(),
        host_adapter_sha256=hashlib.sha256((out/'guard-host.c').read_bytes()).hexdigest(),command=cmd,
        compiler_exit_code=run.returncode,CRC_table_bytes=1024,CRC_table_SHA256=hashlib.sha256(table_bytes).hexdigest(),
        target_executed=False,MMU_executed=False,cache_instructions_executed=False,CP_written=False)
    (out/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
