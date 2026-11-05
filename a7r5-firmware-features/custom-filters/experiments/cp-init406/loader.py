"""原loader窗口实际计算.data映射参数，不补造复制或锁初值。"""
import hashlib,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_PROT_ALL,UC_PROT_READ
from unicorn.arm_const import UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R4,UC_ARM_REG_R10
from a7filters.access_evidence import CP_SHA,require_source

def verify(cp,directory):
 require_source(cp,CP_SHA,'CP');base=0x108000
 u=Uc(UC_ARCH_ARM,UC_MODE_ARM)
 u.mem_map(0x108000,0x1000,UC_PROT_ALL);u.mem_write(0x108000,cp[:0x1000])
 u.mem_map(0x128000,0x1000,UC_PROT_READ);u.mem_write(0x128000,cp[0x20000:0x21000])
 u.mem_map(0x3000000,0x10000);u.reg_write(UC_ARM_REG_SP,0x300e000)
 # 原窗口自行复制header并从header+16c加载影像基址到SL。
 u.emu_start(0x1083a4,0x1083c4,count=100000)
 assert u.reg_read(UC_ARM_REG_R4)==0x108da0
 assert bytes(u.mem_read(0x108da0,0x17c))==cp[0x20000:0x2017c]
 image_base=u.reg_read(UC_ARM_REG_R10);assert image_base==0x128000
 u.emu_start(0x1084f4,0x108508,count=32)
 args=[u.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
 assert args==[0x107f000,0x117f5c,0x107f000,0xc]
 ranges=[]
 for name,address,size in (('service_directory_data_page',0x1091000,0x1000),('A7L6',0x11952c0,0x1c9a)):
  relative=address-args[0];physical=args[2]+relative;file_offset=physical-base
  assert physical==address
  raw=cp[file_offset:file_offset+size]
  ranges.append({'name':name,'virtual':hex(address),'physical':hex(physical),'CP_file_offset':hex(file_offset),'bytes':size,'sha256':hashlib.sha256(raw).hexdigest()})
 result={'schema':'original-loader-data-window/1','CP_sha256':CP_SHA,'original_header_copy_entry':'0x1083a4','original_header_copy_function':'0x108a04','original_image_base_load':'0x1083c0','image_base':hex(image_base),'original_data_argument_window':['0x1084f4','0x108508'],'mapper_arguments':dict(zip(('destination_virtual','bytes','source_physical','flags'),map(hex,args))),
  'header_source_field':'0xf57000','source_semantics':'offset relative to original image base128000, not standalone VA or CP-file-zero offset','CP_file_source_offset':'0xf77000','data_virtual_equals_physical':True,'data_copied_by_this_probe':False,'lock119c8c8':{'raw_64_sha256':hashlib.sha256(cp[0x119c8a8-base:0x119c8e8-base]).hexdigest(),'all_zero':not any(cp[0x119c8a8-base:0x119c8e8-base]),'BSS_start':'0x1197000','A7L6_end':'0x1196f5a','overlap':False},'ranges':ranges,'full_boot_proven':False}
 (Path(directory)/'loader-data-window.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 return result
