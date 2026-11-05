"""同源必要页四核原入口窄探针；只读QMP，不提供固件设备后端。"""
import argparse,fcntl,hashlib,json,os,re,socket,struct,subprocess,sys,tempfile,time
from audit_trace import audit
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'a7r5-qemu/tools'))
sys.path.insert(0,str(ROOT/'a7r5-firmware-features/custom-filters'))
from app_paths import open_vm_lock
from native_vm import sandbox_profile
SOURCE=Path(__file__).resolve().parent
D=None;BUILD=None;NEGATIVE=False;OSAL=False;RTOS=False;TOMCO=False
CP_SHA='18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
from a7filters import baseline
from a7filters.access_evidence import require_source
from loader import verify as verify_loader
from pool import execute as verify_pool
from rtos_layout import RTOS_PAGE_PLAN,TOMCO_PAGE_PLAN
from tomco import load as load_tomco,CPIO_SHA,TOMCO_SHA

PAGE_PLAN=((0x128000,0x1000,False),(0x5e3000,0x13000,True),(0x607000,0x2000,True),(0xe7d000,0x1000,False),(0xfbd000,0x1000,False),(0x1184000,0x1000,False),(0x53c000,0x2000,True),(0x5c8000,0x2000,True),(0x5dc000,0x2000,True),(0xbaa000,0x1000,True),(0x1091000,0x1000,False),(0x53b000,0x1000,True),(0x53a000,0x1000,True),(0x5c0000,0x1000,True),(0xe7a000,0x1000,False),(0xe74000,0x1000,False),(0xbee000,0x2000,True))
OSAL_PAGES=((0xc2b000,0x2000,False),(0x521000,0x1000,True),(0x5d6000,0x1000,True),(0x5fe000,0x1000,True),(0x1164000,0x1000,False),(0xba9000,0x1000,True),(0x600000,0x1000,True),(0x5fb000,0x2000,True),(0x5fd000,0x1000,True),(0x5fa000,0x1000,True),(0x148000,0x2000,True),(0x150000,0x1000,True),(0x5c5000,0x1000,True),(0x5bf000,0x1000,True),(0x5bb000,0x1000,True),(0x5cc000,0x1000,True),(0x5be000,0x1000,True),(0xe77000,0x3000,False),(0x5c6000,0x1000,True))

def prepare_pages(cp,directory,omit_pool=False,original_osal=False,original_rtos=False,tomco=None):
 require_source(cp,CP_SHA,'CP')
 if tomco is not None and (len(tomco)!=686 or hashlib.sha256(tomco).hexdigest()!=TOMCO_SHA):raise ValueError('原TOMCO内容身份不符')
 folder=directory/'source-pages';folder.mkdir(exist_ok=False)
 rows=[]
 plan=TOMCO_PAGE_PLAN if tomco is not None else RTOS_PAGE_PLAN if original_rtos else PAGE_PLAN+(OSAL_PAGES if original_osal else ())
 for address,size,executable in plan:
  if omit_pool and address==0x53b000:continue
  raw=cp[address-0x108000:address-0x108000+size]
  if len(raw)!=size:raise ValueError('原源页范围不符')
  name=f'cp-{address:08x}-{size:x}.bin';(folder/name).write_bytes(raw)
  rows.append(dict(file=name,address=address,bytes=size,sha256=hashlib.sha256(raw).hexdigest(),executable=executable))
 if tomco is not None:
  name='cp-00100000-2ae.bin';(folder/name).write_bytes(tomco)
  rows.append(dict(file=name,address=0x100000,bytes=len(tomco),sha256=TOMCO_SHA,executable=False,provenance='same CPIO cp/tomco.txt; not CP image bytes'))
 manifest=dict(schema='current-cp-narrow-pages/1',CP_sha256=CP_SHA,DAT_sha256='3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2',total_source_bytes=sum(r['bytes'] for r in rows),pages=rows,original_osal=original_osal,original_rtos=original_rtos,original_tomco=tomco is not None,complete_CP_exported=False)
 if tomco is not None:
  manifest['TOMCO_source_CPIO_sha256']=CPIO_SHA
  manifest['original_initialized_data']={'address':0x107f000,'bytes':0x117f5c,'sha256':hashlib.sha256(cp[0x107f000-0x108000:0x1196f5c-0x108000]).hexdigest(),'executable':False,'source_file_offset':0xf77000}
 (directory/'source-pages.json').write_text(json.dumps(manifest,indent=2)+'\n')
 return manifest


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run():
 manifest=json.loads((D/'source-pages.json').read_text());build=json.loads((BUILD/'receipt.json').read_text())
 assert manifest['CP_sha256']==CP_SHA and manifest['total_source_bytes']<=(0x200000 if TOMCO else 0x60000 if RTOS else 0x40000 if OSAL else 0x30000)
 assert bool(manifest.get('original_osal',False))==OSAL
 assert bool(manifest.get('original_rtos',False))==RTOS
 assert bool(manifest.get('original_tomco',False))==TOMCO
 if TOMCO:
  assert manifest['TOMCO_source_CPIO_sha256']==CPIO_SHA
  data=manifest['original_initialized_data']
  assert (data['address'],data['bytes'],data['sha256'],data['executable'])==(0x107f000,0x117f5c,'8bfed4eda1ab8adef4266b58b25e7a82fea745554873379ea456d3f1979579de',False)
 assert manifest['DAT_sha256']=='3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2'
 relative=Path(build['binary'])
 if relative.is_absolute() or '..' in relative.parts:
  raise ValueError('QEMU构建内二进制路径越界')
 binary=BUILD/relative
 if binary.is_symlink() or not binary.is_file() or binary.resolve()!=binary.absolute():
  raise ValueError('QEMU二进制不是构建内固定普通文件')
 assert sha(binary)==build['binary_sha256']
 assert build['source_sha256']=='731b5681e4bb18be313231579b8efd0296c5b015fa36dc533874b639ba838016'
 assert build['base_patch_sha256']=='29a84ae7a23897af25279f3c438bef387a01d59137767e0362631d4c294f78f8'
 assert sha(ROOT/'a7r5-qemu/source/qemu/a7r5-cp-boot.c')==build['board_sha256']
 for name,h in build['model_sources'].items():assert sha(ROOT/'a7r5-qemu/source/qemu'/name)==h
 pages=[]
 for r in manifest['pages']:
  assert re.fullmatch(r'cp-[0-9a-f]{8}-[0-9a-f]+\.bin',r['file'])
  p=D/'source-pages'/r['file'];assert not p.is_symlink() and p.stat().st_size==r['bytes'] and sha(p)==r['sha256'];pages.append((p,r['address']))
 out=Path(tempfile.mkdtemp(prefix='qemu-run-',dir=D));control=Path(tempfile.mkdtemp(prefix='a7r5-cp30-',dir='/private/tmp'))
 source_files={name:sha(SOURCE/name) for name in ('verify.py','audit_trace.py','loader.py','pool.py','rtos_layout.py','tomco.py','probe-tomco.S' if TOMCO else 'probe-rtos.S' if RTOS else 'probe-osal.S' if OSAL else 'probe.S','probe.ld')}
 lock=None;process=None;stream=None;sock=None;log=None;receipt={'schema':'same-CP-four-core-narrow-QEMU/1','CP_sha256':CP_SHA,'source_page_manifest_sha256':sha(D/'source-pages.json'),'probe_sha256':sha(D/'probe.elf'),'research_sources_sha256':source_files,'build_receipt_sha256':sha(BUILD/'receipt.json'),'QEMU_binary_sha256':sha(binary),'CP_full_boot':False,'MMIO_model_is_hardware_evidence':False,'host_barrier_or_GIC_writes':False,'camera_io':False,'output':str(out)}
 seq=[0]
 def command(execute,arguments=None):
  seq[0]+=1;req={'execute':execute,'id':seq[0]}
  if arguments is not None:req['arguments']=arguments
  stream.write(json.dumps(req).encode()+b'\n');stream.flush()
  while True:
   row=json.loads(stream.readline())
   if row.get('id')==seq[0]:
    if 'error' in row:raise RuntimeError(row['error'])
    return row.get('return')
 try:
  lock=open_vm_lock();fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  # 本次输出目录只包含自有窄页和观察器；不授权设备或任意工作区读取。
  profile=sandbox_profile(binary,D/'probe.elf',D/'probe.elf',D/'probe.elf',out,control)
  profile+='(allow file-read* (subpath '+json.dumps(str(D/'source-pages'))+'))\n'
  (out/'native.sb').write_text(profile)
  args=['/usr/bin/sandbox-exec','-f',str(out/'native.sb'),str(binary),'-machine','a7r5-cp-boot','-cpu','cortex-a35,aarch64=off,has_el2=off,has_el3=off','-smp','4','-accel','tcg','-m','128M','-nodefaults','-display','none','-monitor','none','-serial','none','-nic','none','-no-reboot','-audiodev','none,id=silent','-S','-qmp',f'unix:{control}/qmp.sock,server=on,wait=off','-d',('' if OSAL or RTOS else 'exec,')+'in_asm,int,guest_errors,unimp','-dfilter','0x0+0x1000,0x40000+0x1000,0x108000+0x10cc000','-D',str(out/'trace.log')]
  for p,address in pages:args+=['-device',f'loader,file={p},addr={address:#x},force-raw=on']
  args+=['-device',f'loader,file={D}/probe.elf,cpu-num=0']
  for core in (1,2,3):args+=['-device',f'loader,addr=0x40000,cpu-num={core}']
  receipt['command']=args;receipt['control']=str(control)
  (out/'command.json').write_text(json.dumps(args,indent=2)+'\n')
  log=(out/'console.log').open('wb');process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env={'PATH':'/usr/bin:/bin','HOME':str(control),'TMPDIR':str(control),'LC_ALL':'C'},start_new_session=True)
  deadline=time.monotonic()+5
  while not (control/'qmp.sock').exists():
   if process.poll() is not None:raise RuntimeError('QEMU在QMP前退出')
   if time.monotonic()>deadline:raise RuntimeError('QMP启动超时')
   time.sleep(.01)
  sock=socket.socket(socket.AF_UNIX);sock.settimeout(3);sock.connect(str(control/'qmp.sock'));stream=sock.makefile('rwb');assert 'QMP' in json.loads(stream.readline())
  command('qmp_capabilities');command('cont')
  # 到达明确源缺口/目标返回即暂停；不把固定短时观察当目标验证。
  from audit_trace import image_segments
  allowed=[(a,a+len(b)) for a,b in image_segments(D/'probe.elf')]
  allowed += [(r['address'],r['address']+r['bytes']) for r in manifest['pages'] if r.get('executable',False)]
  until=time.monotonic()+2;cursor=0;tail='';stop_reason='deadline';observed_stage=0;idle_samples=0
  while time.monotonic()<until:
   time.sleep(.02)
   tp=out/'trace.log'
   if tp.exists():
    with tp.open('r') as tf:tf.seek(cursor);chunk=tf.read();cursor=tf.tell()
    tail=(tail+chunk)
    actual=list(re.finditer(r'^0x()([0-9a-fA-F]+):' if OSAL or RTOS else r'^Trace (\d+): .*?\[[^/]+/([0-9a-fA-F]+)(?:/[^\]]*)?\]',tail,re.M))
    missing=next((hex(int(m[2],16)) for m in actual if not any(a<=int(m[2],16)<b for a,b in allowed)),None)
    tail=tail[-256:]
    if missing:stop_reason='unknown_source:'+missing;break
    if TOMCO and 'DFAR 0xf1388344' in chunk:stop_reason='original_wdt_MMIO_abort';break
    if cursor>32*1024*1024:stop_reason='trace_budget';break
   state=command('human-monitor-command',{'command-line':'xp /1wx 0x3000004'})
   vals=re.findall(r'0x([0-9a-fA-F]+)',state);observed_stage=int(vals[-1],16) if vals else 0
   if observed_stage==6:stop_reason='query_returned';break
   if observed_stage>=0x80:stop_reason='exception';break
   if RTOS and observed_stage==0x27:
    registers=[command('human-monitor-command',{'command-line':'info registers','cpu-index':i}) for i in range(4)]
    idle=all((match:=re.search(r'R15=([0-9a-fA-F]+)',value)) and 0x5cc248<=int(match[1],16)<0x5cc294 for value in registers)
    idle_samples=idle_samples+1 if idle else 0
    if idle_samples==3:stop_reason='four_core_original_idle';break
  command('stop');receipt['observation_stop_reason']=stop_reason;receipt['observed_primary_stage']=observed_stage
  receipt['cpus']=command('query-cpus-fast')
  receipt['registers']=[command('human-monitor-command',{'command-line':'info registers','cpu-index':core}) for core in range(4)]
  regions=[('observer.bin',0x3000000,256),('barrier.bin',0x195dfb8,48),('MMU-context.bin',0x19541e8,0x428),('L1.bin',0x1a3c000,0x4000),('L2.bin',0x1a40000,0x8000),('GIC-context.bin',0x195068c,0x1238),('heap-context.bin',0x195e1cc,0x90),('directory.bin',0x1091500,0xc0),('service-output.bin',0x3001000,16),('main-stack.bin',0x1a4ae00,0x200),('nested-lock.bin',0x119c800,0x200)]
  if OSAL or RTOS:regions += [('pool.bin',0x119c780,64),('classes.bin',0x1d20080,0x1680),('thread-contexts.bin',0x19d4000,0x12000),('callbacks.bin',0x1184000,256)]
  if RTOS:regions += [('kernel-global.bin',0x1950400,0x100),('rtos-global.bin',0x195e980,0x80)]
  if TOMCO:regions += [('timer-context.bin',0x1676ec8,0x100),('wdt-context.bin',0x10a4878,0x40),('original-tomco.bin',0x100000,686)]
  for name,address,size in regions:command('pmemsave',{'val':address,'size':size,'filename':str(out/name)})
  observer=(out/'observer.bin').read_bytes();receipt['observer']=[list(map(hex,struct.unpack_from('<12I',observer,core*64))) for core in range(4)]
  receipt['barrier_counters']=[struct.unpack_from('<I',(out/'barrier.bin').read_bytes(),core*12)[0] for core in range(4)]
  receipt['MMU_context_first_words']=list(map(hex,struct.unpack('<8I',(out/'MMU-context.bin').read_bytes()[:32])))
  receipt['status']='OBSERVED_NOT_COMPLETE_BOOT' if stop_reason not in ('trace_budget','deadline') else 'PARTIAL_BUDGET'
 except Exception as error:receipt['status']='FAILED';receipt['error']=str(error)
 finally:
  if process is not None:
   if process.poll() is None:
    try:command('quit');receipt['QMP_quit']=True
    except Exception as error:receipt['QMP_quit_error']=str(error);process.terminate()
   try:receipt['QEMU_exit_code']=process.wait(timeout=5)
   except subprocess.TimeoutExpired:process.kill();receipt['QEMU_exit_code']=process.wait();receipt['forced_exit']=True
  if stream is not None:stream.close()
  if sock is not None:sock.close()
  if log is not None:log.close()
  if lock is not None:lock.close();receipt['global_VM_lock_released']=True
  trace_text=(out/'trace.log').read_text() if (out/'trace.log').exists() else ''
  receipt['execution_source_audit']=audit(trace_text,manifest,D/'source-pages',D/'probe.elf',require_exec_references=not (OSAL or RTOS))
  if receipt['execution_source_audit']['status']!='PASS':receipt['status']='INCOMPLETE_SOURCE'
  if receipt.get('status')=='OBSERVED_NOT_COMPLETE_BOOT':
   observer=receipt.get('observer',[])
   gic=(out/'GIC-context.bin').read_bytes()
   directory=(out/'directory.bin').read_bytes()
   valid=(len(observer)==4 and all(int(row[0],16)==(0x80000000|i) for i,row in enumerate(observer)) and int(observer[0][1],16)==(0x27 if RTOS else 6) and receipt.get('barrier_counters')==([5,5,5,5] if RTOS else [3,5,5,5])
          and struct.unpack_from('<I',gic,0)[0]==0xf13a1000
          and struct.unpack_from('<I',gic,8)[0]==0xf13a2000
          and struct.unpack_from('<I',directory,0x80)[0]==0
          and 'CP_' not in trace_text and 'unimplemented' not in trace_text)
   if TOMCO:
    group=struct.unpack_from('<I',(out/'rtos-global.bin').read_bytes(),0x5c)[0]
    wdt=struct.unpack('<16I',(out/'wdt-context.bin').read_bytes())
    registers=receipt['registers'][0]
    correct_boundary=(valid and stop_reason=='original_wdt_MMIO_abort' and group==2 and 'R15=00609e18' in registers
                      and 'R04=f13883a0' in registers and 'R05=00040000' in registers
                      and struct.unpack_from('<I',(out/'rtos-global.bin').read_bytes(),0x54)[0]==1
                      and wdt[0]==7 and wdt[8]==0x60948c
                      and struct.unpack_from('<I',(out/'timer-context.bin').read_bytes(),0x7c)[0]==0x10a4880
                      and sha(out/'original-tomco.bin')==TOMCO_SHA)
    receipt['configuration_group']=group
    receipt['TOMCO_parse_evidence']='PASS' if correct_boundary else 'NOT_CLOSED'
    receipt['TOMCO_host_group_write']=False
    receipt['TOMCO_unmodified']=sha(out/'original-tomco.bin')==TOMCO_SHA
    receipt['tomco_not_loaded_in_this_prefix']=False
    receipt['packaged_group2_not_yet_parsed']=False
    receipt['original_software_timer_queue_head']=hex(struct.unpack_from('<I',(out/'timer-context.bin').read_bytes(),0x7c)[0])
    receipt['original_wdt_enabled']=struct.unpack_from('<I',(out/'rtos-global.bin').read_bytes(),0x54)[0]
    receipt['original_wdt_timeout_setting']=wdt[0]
    receipt['original_wdt_timer_callback']=hex(wdt[8])
    receipt['fault']={'original_PC':'0x609e18','DFAR':'0xf1388344','operation':'STR r5,[r4,#-0x5c]','value':'0x40000','device_model_available':False}
    receipt['status']='BLOCKED_ORIGINAL_WDT_MMIO' if correct_boundary else 'PARTIAL_NOT_CLOSED'
   elif RTOS:
    contexts=(out/'thread-contexts.bin').read_bytes();group=struct.unpack_from('<I',(out/'rtos-global.bin').read_bytes(),0x5c)[0]
    rows=[struct.unpack_from('<24I',contexts,0x1a8+i*0x878) for i in range(4)]
    valid=valid and stop_reason=='four_core_original_idle' and group==0 and all(row[0]==row[1]==0 and row[16]==1 and row[17]==0x1670ec0+i*0x2000 and row[19]==i+1 and row[20]==row[21]==1 for i,row in enumerate(rows))
    receipt['configuration_group']=group
    receipt['original_per_core_contexts']=[list(map(hex,row)) for row in rows]
    receipt['tomco_not_loaded_in_this_prefix']=True
    receipt['packaged_group2_not_yet_parsed']=True
    receipt['status']='PASS_ORIGINAL_FOUR_CORE_RTOS_IDLE_GROUP0_PREFIX' if valid else 'PARTIAL_NOT_CLOSED'
   elif OSAL:
    pool=struct.unpack('<16I',(out/'pool.bin').read_bytes())
    context=(out/'thread-contexts.bin').read_bytes()
    callbacks=(out/'callbacks.bin').read_bytes()
    callback_source=next(row for row in manifest['pages'] if row['address']==0x1184000)
    callback_before=(D/'source-pages'/callback_source['file']).read_bytes()[:256]
    callbacks_preserved=callbacks==callback_before
    valid=valid and int(observer[0][8],16)==0 and int(observer[0][9],16)!=0 and int(observer[0][10],16)==0xffffffff and pool[4:6]==(0x1bf4240,0xabdc0) and pool[2]!=0 and pool[6]>0 and struct.unpack_from('<I',context,0x1e8)[0]==1 and callbacks_preserved
    receipt['original_OSAL_tail_return']=observer[0][10]
    receipt['callback_registration_rejected_in_initialization_context']=valid
    receipt['callback_table_preserved']=callbacks_preserved
    receipt['query_output_is_resource_handle_not_grid_pointer']=True
    receipt['original_pool_words']=list(map(hex,pool[:8]))
    receipt['status']='PASS_ORIGINAL_POOL_QUERY_CALLBACK_REJECTED' if valid else 'PARTIAL_NOT_CLOSED'
   else:
    valid=valid and int(observer[0][8],16)==0xfffffc01 and int(observer[0][9],16)==0
    receipt['status']='PASS_ORIGINAL_QUERY_EMPTY_POOL_REJECTION' if valid else 'PARTIAL_NOT_CLOSED'
  if NEGATIVE and receipt.get('status')=='INCOMPLETE_SOURCE':
   gaps=receipt['execution_source_audit']['unknown_actual_TB_entries']
   if gaps and gaps[0]['address']=='0x53b50c':receipt['status']='PASS_EXPECTED_SOURCE_REJECTION'
  receipt['complete_CP_exported']=False
  receipt['MMU_GIC_results_are_model_scope_only']=True
  receipt['source_pages_preserved']=all(sha(p)==r['sha256'] for (p,a),r in zip(pages,manifest['pages']))
  receipt['observer_preserved']=sha(D/'probe.elf')==receipt['probe_sha256']
  receipt['research_sources_preserved']=all(sha(SOURCE/name)==digest for name,digest in source_files.items())
  if not receipt['source_pages_preserved'] or not receipt['observer_preserved'] or not receipt['research_sources_preserved']:
   receipt['status']='FAILED_SOURCE_DRIFT'
  if receipt.get('QEMU_exit_code')!=0 or not receipt.get('QMP_quit'):
   receipt['status']='FAILED_QEMU_EXIT'
  (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps({k:receipt[k] for k in ('output','status','error','observer','barrier_counters','MMU_context_first_words','QEMU_exit_code','global_VM_lock_released','observation_stop_reason','execution_source_audit') if k in receipt},ensure_ascii=False,indent=2))
 return 0 if receipt['status'].startswith('PASS_') else 1
def main():
 global D,BUILD,NEGATIVE,OSAL,RTOS,TOMCO
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--input',type=Path,required=True)
 parser.add_argument('--qemu-build',type=Path)
 parser.add_argument('--pool-prefix-only',action='store_true',help='独立Unicorn原池前缀验证，不启动QEMU或复用其状态')
 parser.add_argument('--original-osal-init',action='store_true',help='执行原队列/任务记录及OSAL构造，保留尾部回调登记的真实拒绝')
 parser.add_argument('--original-rtos-init',action='store_true',help='执行原四核RTOS启动前缀，核验不含TOMCO解析的group0 idle检查点')
 parser.add_argument('--original-tomco-init',action='store_true',help='原四核RTOS自然解析同源TOMCO，保留原看门狗MMIO模型缺口')
 parser.add_argument('--tomco-cpio',type=Path,help='同源原CPIO，仅提取锁定的686B cp/tomco.txt')
 parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--negative-omit-pool-page',action='store_true',help='固定漏53b代码页的拒绝验证，不作服务结果')
 args=parser.parse_args();D=args.output.absolute();BUILD=args.qemu_build.absolute() if args.qemu_build else None;NEGATIVE=args.negative_omit_pool_page;OSAL=args.original_osal_init;TOMCO=args.original_tomco_init;RTOS=args.original_rtos_init or TOMCO
 if OSAL and (args.pool_prefix_only or NEGATIVE):raise ValueError('OSAL模式不得与独立前缀或漏页负例混用')
 if RTOS and (OSAL or args.pool_prefix_only or NEGATIVE):raise ValueError('RTOS模式不得与其他探针模式混用')
 if TOMCO!=bool(args.tomco_cpio):raise ValueError('原TOMCO模式必须且仅能提供同源CPIO')
 tomco=load_tomco(args.tomco_cpio) if TOMCO else None
 if D.exists() or D.is_symlink() or D.resolve()!=D:raise ValueError('输出必须为全新非链接目录')
 if not args.pool_prefix_only and BUILD is None:raise ValueError('四核验证必须提供独立QEMU构建')
 D.mkdir(parents=True)
 captured={};original=baseline.check_component
 def capture(name,raw,expected):
  result=original(name,raw,expected)
  if name=='CP':captured[name]=raw
  return result
 baseline.check_component=capture
 try:source=baseline.audit(str(args.input))
 finally:baseline.check_component=original
 baseline.write_report(D/'baseline-audit.json',source)
 cp=captured.pop('CP')
 if args.pool_prefix_only:
  result=verify_pool(cp,D);print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['status']=='PASS_PREFIX' else 1
 prepare_pages(cp,D,NEGATIVE,OSAL,RTOS,tomco);verify_loader(cp,D);del cp
 probe_source=SOURCE/('probe-tomco.S' if TOMCO else 'probe-rtos.S' if RTOS else 'probe-osal.S' if OSAL else 'probe.S')
 compiler=['/opt/homebrew/opt/llvm/bin/clang','--target=armv7a-none-eabi','-march=armv8-a','-marm','-mfloat-abi=soft','-nostdlib','-ffreestanding','-Wl,-T,'+str(SOURCE/'probe.ld'),'-Wl,--build-id=none','--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',str(probe_source),'-o',str(D/'probe.elf')]
 built=subprocess.run(compiler,capture_output=True,text=True,timeout=30)
 (D/'compiler.log').write_text(built.stdout+built.stderr)
 (D/'build.json').write_text(json.dumps(dict(command=compiler,exit_code=built.returncode,probe_source_sha256=sha(probe_source),linker_source_sha256=sha(SOURCE/'probe.ld')),indent=2)+'\n')
 if built.returncode:raise RuntimeError('离线观察器构建失败')
 return run()

if __name__=='__main__':raise SystemExit(main())
