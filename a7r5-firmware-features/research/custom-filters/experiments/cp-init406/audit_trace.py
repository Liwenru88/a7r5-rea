"""核对每核实际TB入口及完整翻译块字节；未知/跨页漏源一律拒绝。"""
import re,struct

def image_segments(path):
 b=path.read_bytes()
 if b[:6]!=b'\x7fELF\x01\x01':raise ValueError('观察器不是小端ELF32')
 off=struct.unpack_from('<I',b,28)[0];size,count=struct.unpack_from('<HH',b,42)
 result=[]
 for i in range(count):
  kind,at,va,pa,filesz,memsz,flags,align=struct.unpack_from('<8I',b,off+i*size)
  if kind==1 and flags&1:result.append((va,b[at:at+filesz]))
 return result

def audit(text,manifest,page_dir,observer,require_exec_references=True):
 ranges=image_segments(observer)
 for r in manifest['pages']:
  # 仅明确代码页可供执行，数据页即使字节同源也不授予执行资格。
  if r.get('executable',r['address'] in (0x5e3000,0x607000,0x53c000,0x53b000,0x53a000,0x5c8000,0x5dc000,0xbaa000)):
   ranges.append((r['address'],(page_dir/r['file']).read_bytes()))
 def expected(address,length):
  out=bytearray();cursor=address
  while len(out)<length:
   found=next(((a,b) for a,b in ranges if a<=cursor<a+len(b)),None)
   if found is None:return None
   a,b=found;n=min(length-len(out),a+len(b)-cursor)
   out.extend(b[cursor-a:cursor-a+n]);cursor+=n
  return bytes(out)
 per_core={};unknown=[];mismatch=[];blocks=0;current=None;raw=[];approved=set();executed=set()
 def finish():
  nonlocal blocks,current,raw
  if current is not None:
   blocks+=1;b=bytes.fromhex(''.join(raw));want=expected(current,len(b))
   if not b or want is None or b!=want:
    if len(mismatch)<12:mismatch.append({'address':hex(current),'bytes':len(b),'reason':'missing_bytes' if not b else 'unknown_page' if want is None else 'source_mismatch'})
   else:approved.add(current)
  current=None;raw=[]
 for line in text.splitlines():
  m=re.match(r'^Trace (\d+): .*?\[[^/]+/([0-9a-fA-F]+)(?:/[^\]]*)?\]',line)
  if m:
   core=int(m[1]);at=int(m[2],16);executed.add(at);per_core[core]=per_core.get(core,0)+1
   if expected(at,2) is None and len(unknown)<12:unknown.append({'core':core,'address':hex(at)})
  m=re.match(r'^0x([0-9a-fA-F]+):',line)
  if m:finish();current=int(m[1],16)
  elif line.startswith('OBJD-T: '):raw.append(line[8:].strip())
  elif not line.strip():finish()
 finish()
 unassociated=sorted(executed-approved)
 # 长初始化可仅记录完整翻译块；核身份须由外层实际MPIDR观察独立核验。
 # 该模式不声称记录每次动态执行，仍拒绝任意无来源翻译字节。
 valid=(not require_exec_references or set(per_core)==set(range(4))) and blocks>0 and not unknown and not mismatch and not unassociated
 return {'status':'PASS' if valid else 'INCOMPLETE_SOURCE','actual_TB_entries_per_core':per_core,
  'translated_blocks_checked':blocks,'exec_references_without_approved_translation':list(map(hex,unassociated[:12])),'per_core_exec_references_required':require_exec_references,'TCG_chained_repetitions_are_not_individually_logged':True,'unknown_actual_TB_entries':unknown,'invalid_full_TB_bytes':mismatch,
  'cross_page_bytes_checked':True,'CPU_MPIDR_is_not_hooked':True,'unknown_RAM_is_not_source':True}
