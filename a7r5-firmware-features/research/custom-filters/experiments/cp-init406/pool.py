"""执行原无参OSAL资源构造前缀，所有池指针由原指令生产。"""
from collections import Counter
from pathlib import Path
import hashlib,json,struct
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_INVALID,UC_PROT_READ,UC_PROT_WRITE,UC_PROT_EXEC
from unicorn import arm_const as r
from a7filters.access_evidence import CP_SHA,require_source

def execute(cp,directory):
 require_source(cp,CP_SHA,'CP');base=0x108000;u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
 end=(base+len(cp)+4095)&~4095;u.mem_map(base,end-base,UC_PROT_READ|UC_PROT_EXEC);u.mem_write(base,cp)
 u.mem_protect(0x119c000,0x1000,UC_PROT_READ|UC_PROT_WRITE)
 for a,n in ((0x1b00000,0x222000),(0x19d4000,0x1000),(0x1e21000,0x2000),(0x3000000,0x10000)):u.mem_map(a,n,UC_PROT_READ|UC_PROT_WRITE)
 u.reg_write(r.UC_ARM_REG_SP,0x300e000);u.reg_write(r.UC_ARM_REG_LR,0x300f001)
 count=Counter();fault=[];stopped=[];total=[0]
 def code(cpu,at,size,data):
  if at==0x53a606:stopped.append(hex(at));cpu.emu_stop()
 def write(cpu,access,address,size,value,data):
  total[0]+=1
  if total[0]>800000:raise ValueError('原池构造写入超预算')
  ranges=((0x119c000,0x119d000),(0x1b00000,0x1d22000),(0x19d4000,0x19d5000),(0x1e21000,0x1e23000),(0x3000000,0x3010000))
  region=next((a for a,b in ranges if a<=address and address+size<=b),None)
  if region is None:raise ValueError(f'原池前缀越出声明区域:{address:x}')
  count[hex(region)]+=1
 def invalid(cpu,access,address,size,value,data):
  fault.append({'pc':hex(cpu.reg_read(r.UC_ARM_REG_PC)),'access':access,'address':hex(address),'size':size});return False
 u.hook_add(UC_HOOK_CODE,code);u.hook_add(UC_HOOK_MEM_WRITE,write);u.hook_add(UC_HOOK_MEM_INVALID,invalid)
 error=None
 try:u.emu_start(0x53a52d,0x53a606,count=4000000)
 except Exception as e:error=str(e)
 pool=bytes(u.mem_read(0x119c780,32));words=struct.unpack('<8I',pool)
 sizes=struct.unpack_from('<180I',cp,0xc2bfc0-base);used=0x40+sum(sizes);expected_start=0x1b20000+used;expected_size=0x180000-used
 n=0;at=words[2];seen=set();valid=error is None and u.reg_read(r.UC_ARM_REG_PC)==0x53a606
 while at and n<65536:
  if at in seen or not expected_start<=at<expected_start+expected_size:valid=False;break
  seen.add(at);n+=1;at=struct.unpack('<I',u.mem_read(at,4))[0]
 valid=valid and words[4:8]==(expected_start,expected_size,expected_size,expected_size) and n==expected_size//64 and at==0
 receipt={'schema':'original-OSAL-pool-prefix/1','CP_sha256':CP_SHA,'entry':'0x53a52c','stop_before':'0x53a606','original_pool_initializer':'0xbaa3d4','error':error,'faults':fault,'pc':hex(u.reg_read(r.UC_ARM_REG_PC)),'status':'PASS_PREFIX' if valid else 'FAILED','pool_words':list(map(hex,words)),'expected_start':hex(expected_start),'expected_bytes':expected_size,'original_nodes_validated':n,'original_write_count':total[0],'writes_by_declared_region':dict(count),'ROM_sizes_sha256':hashlib.sha256(cp[0xc2bfc0-base:0xc2c290-base]).hexdigest(),'pool_bytes_sha256':hashlib.sha256(pool).hexdigest(),'full_constructor_returned':False,'host_filled_pool':False,'VM_started':False,'camera_io':False}
 (Path(directory)/'pool-prefix.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
 return receipt
