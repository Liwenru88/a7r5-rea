"""独立原键盘会话契约；模型/原生命周期为明确服务边界，不代替Qt。"""
import struct
import pytest
from unicorn import arm64_const as r
from test_ap_ui_dynamic import modules  # noqa: F401
from test_ap_ui_lifecycle import _owner

VALUES=[0x7f83560,0x7f83770,0x7f83980,0x7f839a0,0x7f839c0,0x7f839e0,0x7f83a00,0x7f83a48]
GETTERS=[0x28cb488,0x28cb4b0,0x28cb4d8,0x28cb500,0x28cb528,0x28cb550,0x28cb578,0x28cb5a0]
SIZES=[256,256,4,4,4,4,4,16]
DS=[0xcc,0xcd,0xcf,0xce]
VT=[0x58d8308,0x58d8370,0x58d83d8,0x58d8440]
CLOSE=[0x219712c,0x21998ec,0x219bdbc,0x219e29c]


def _keyboard(raw,old='原有完整中文滤镜名称',skip_presented_poll=False):
 m,manager,catalog,models,state=_owner(raw);u,base,work=m.u,m.base,m.work
 state.update(selector=19,init=[],leave=[],close=[],notify=[],journal=[])
 def ret(cpu,value=0):cpu.reg_write(r.UC_ARM64_REG_X0,value)
 m.services[base+0x1c05f18]=lambda cpu:ret(cpu,state['selector'])
 u.mem_write(work+0x424,bytes(4))
 m.services[base+0x17ffd84]=lambda cpu:ret(cpu)
 m.services[base+0x28bfdcc]=lambda cpu:ret(cpu,work+0x424)
 m.services[base+0x1bd54d8]=lambda cpu:ret(cpu,0x200aa01)
 def enqueue(cpu):
  assert cpu.reg_read(r.UC_ARM64_REG_X0)==manager
  source,target=[struct.unpack('<I',u.mem_read(cpu.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))),4))[0] for i in (1,2)]
  assert source==0x2ed and target in (0xcd,0xd4)
  state['opens'].append((source,target))
 m.services[base+0x1cdbb08]=enqueue
 metas=[];addresses=[base+v for v in VALUES]
 for i,(getter,address,size) in enumerate(zip(GETTERS,addresses,SIZES)):
  m.map(address,size);m.services[base+getter]=lambda cpu,address=address:ret(cpu,address)
  meta=work+0x40000+i*0x40;shadow=work+0x41000+i*0x100
  m.map(meta,32);m.map(shadow,256);u.mem_write(meta,struct.pack('<3Q',shadow if i==7 else 0,shadow if 2<=i<7 else 0,0));metas.append(meta)
  m.services[base+getter+0x14]=lambda cpu,meta=meta:ret(cpu,meta)
  data=(('Existing text '+str(i)).encode()+bytes(size))[:size] if i<2 else struct.pack('<I',i+20) if i<7 else bytes(range(16))
  u.mem_write(address,data);u.mem_write(shadow,data)
 original=b''.join(bytes(u.mem_read(a,n)) for a,n in zip(addresses,SIZES))
 def scope(cpu):u.mem_write(cpu.reg_read(r.UC_ARM64_REG_X0),bytes(16))
 m.services[base+0x23d5818]=scope;m.services[base+0x23d583c]=lambda cpu:None
 m.services[base+0x3693c0c]=lambda cpu:state['journal'].append(('bytes',cpu.reg_read(r.UC_ARM64_REG_X1)))
 def journal(cpu):
  id=cpu.reg_read(r.UC_ARM64_REG_X1);size=cpu.reg_read(r.UC_ARM64_REG_X4)
  assert id==0x19b5 and size==16;state['journal'].append(('typed16',id))
 m.services[base+0x3694f64]=journal
 m.services[base+0x252d80c]=lambda cpu:state['notify'].append(cpu.reg_read(r.UC_ARM64_REG_X0))
 def setter(cpu):
  c=cpu.reg_read(r.UC_ARM64_REG_X0);v=cpu.reg_read(r.UC_ARM64_REG_X1)&0xffffffff
  live,meta,id=struct.unpack('<QQI',u.mem_read(c,20));assert 0x19b0<=id<=0x19b4
  shadow=struct.unpack('<Q',u.mem_read(meta+8,8))[0]
  u.mem_write(live,struct.pack('<I',v))
  if shadow:u.mem_write(shadow,struct.pack('<I',v))
  u.mem_write(c+20,bytes([1,bool(shadow)]))
 m.services[base+0x219a5d8]=setter
 def finalizer(cpu):
  c=cpu.reg_read(r.UC_ARM64_REG_X0);state['notify'].append(struct.unpack('<I',u.mem_read(c+16,4))[0])
 m.services[base+0x23d58d0]=m.services[base+0x23d5b8c]=finalizer
 controllers=[]
 for i in range(4):
  c=work+0x30000+i*0x1000;m.map(c,0x600);u.mem_write(c,struct.pack('<Q',base+VT[i]));u.mem_write(c+0x178,struct.pack('<IQ',DS[i],manager));controllers.append(c)
  # 对齐180字段显式独立写入，不依赖Python压缩结构布局。
  u.mem_write(c+0x180,struct.pack('<Q',manager))
  def stock_init(cpu,i=i):state['init'].append((i,cpu.reg_read(r.UC_ARM64_REG_X0)))
  def stock_leave(cpu,i=i):
   assert struct.unpack('<I',u.mem_read(addresses[6],4))[0]==11
   state['leave'].append((i,cpu.reg_read(r.UC_ARM64_REG_X0)))
  m.services[m.symbols['af_stock_rename_init_'+str(i)]]=stock_init
  m.services[m.symbols['af_stock_rename_leave_'+str(i)]]=stock_leave
  def close(cpu,i=i):
   state['close'].append((i,cpu.reg_read(r.UC_ARM64_REG_X0)))
   if not state.get('reject_close'):u.mem_write(manager+0x1e8,struct.pack('<I',DS[i]))
  m.services[base+CLOSE[i]]=close
 p=bytearray(74);p[8]=3;p[2]=2;u.mem_write(work+0x6100,bytes(p));assert m.call('af_install',catalog,7,work+0x6100,0)==0
 u.mem_write(catalog+6*344+224,struct.pack('<Q',1));assert m.call('af_edit',catalog,7,0,3)==0
 text=old.encode();u.mem_write(work+0x6200,text);assert m.call('af_labels_publish',m.symbols['af_ap_labels'],7,1,work+0x6200,len(text))==0
 before=bytes(u.mem_read(catalog,6888))
 models(0x1603,0x15e7,0xd4);assert m.call('af_ap_manage_ui_open',catalog,6,0)==0
 assert b''.join(bytes(u.mem_read(a,n)) for a,n in zip(addresses,SIZES))==original
 assert m.call('af_ap_research_enable',0)==-4
 models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
 assert state['opens']==[(0x2ed,0xcd)] and m.call('af_ap_manage_ui_state')==5
 assert bytes(u.mem_read(addresses[0],256))==(old.encode()+bytes(256-len(old))) if old.isascii() and len(old)<=46 else bytes(u.mem_read(addresses[0],256))==bytes(256)
 assert struct.unpack('<I',u.mem_read(addresses[6],4))[0]==11
 previous=work+0x6300;u.mem_write(previous,struct.pack('<I',0x2ed))
 models(0x2b36,0x15e7,0xcd);m.call('af_ap_rename_init_1',controllers[1],previous)
 if not skip_presented_poll:m.call('af_ap_refresh',manager)
 assert m.call('af_ap_rename_state')==2 and m.call('af_ap_manage_ui_state')==(5 if skip_presented_poll else 6)
 state.update(addresses=addresses,original=original,catalog_before=before,controllers=controllers,previous=previous)
 return m,manager,catalog,models,state


def _return(m,manager,models,state,layout=1,target=0x2ed):
 u,work=m.u,m.work;u.mem_write(state['previous'],struct.pack('<I',target))
 m.call('af_ap_rename_leave_'+str(layout),state['controllers'][layout],state['previous'])
 assert m.call('af_ap_rename_state')==3
 # 原leave返回也不立即恢复；等待真实管理页apply（本测试是显式模型夹具）。
 assert struct.unpack('<I',u.mem_read(state['addresses'][6],4))[0]==11
 models(0x2b36,0x15e7,target);m.call('af_ap_refresh',manager)
 if target==0x2ed:
  assert state['opens'][-1]==(0x2ed,0xd4)
  assert struct.unpack('<I',u.mem_read(state['addresses'][6],4))[0]==11
  models(0x1603,0x15e7,0xd4);m.call('af_ap_refresh',manager)
 assert m.call('af_ap_rename_state')==0
 assert b''.join(bytes(u.mem_read(a,n)) for a,n in zip(state['addresses'],SIZES))==state['original']
 assert bytes(u.mem_read(m.symbols['af_ap_catalog'],6888))==state['catalog_before']


@pytest.mark.parametrize('outcome',['done','cancel','empty','unchanged','broken-utf8','slot-change','current-change','close-rejected','done-then-cancel'])
def test_private_rename_requires_successful_done_leave_and_parent_then_restores_typed_models(modules,outcome):
 old='Film Original' if outcome=='unchanged' else '原有完整中文滤镜名称'
 m,manager,catalog,models,state=_keyboard(modules,old);u,work=m.u,m.work;target=state['addresses'][1]
 value=b'Film New'
 if outcome=='empty':value=b''
 elif outcome=='unchanged':value=old.encode()
 elif outcome=='broken-utf8':value=b'\xe6\x9a'
 u.mem_write(target,value+bytes(256-len(value)));u.mem_write(manager+0x1e8,struct.pack('<I',0x4cf))
 state['reject_close']=outcome=='close-rejected'
 if outcome!='cancel':m.call('af_ap_rename_done_1',state['controllers'][1])
 if outcome in ('cancel','done-then-cancel'):u.mem_write(target,bytes(u.mem_read(state['addresses'][0],256)))
 if outcome=='slot-change':
  assert m.call('af_edit',catalog,7,0,4)==0;state['catalog_before']=bytes(u.mem_read(catalog,6888))
 if outcome=='current-change':state['selector']=0
 _return(m,manager,models,state)
 job=work+0x6400;result=m.call('af_ap_manage_take',m.symbols['af_ap_manager'],job)
 if outcome=='done':
  assert result==0 and struct.unpack('<Q4I',u.mem_read(job,24))==(1,6,7,7,0)
  assert struct.unpack('<I',u.mem_read(job+24,4))[0]==len(value)
 else:assert result==-2


def test_layout_owner_epoch_and_title_delegate_while_all_four_original_layouts_remain_covered(modules):
 m,manager,catalog,models,state=_keyboard(modules);u,work=m.u,m.work
 assert m.call('af_ap_rename_title',0x15e7)==0x7fcf0001
 assert m.call('af_ap_rename_title',0x1e6)==0x200aa01
 old=state['controllers'][1];u.mem_write(state['previous'],struct.pack('<I',0xce))
 m.call('af_ap_rename_leave_1',old,state['previous']);assert m.call('af_ap_rename_state')==2
 m.call('af_ap_rename_done_1',old);assert m.call('af_ap_rename_state')==2
 # 等待CE时，迟到的CD init也不能重新取得owner。
 m.call('af_ap_rename_init_1',old,state['previous'])
 models(0x2b36,0x15e7,0xce);m.call('af_ap_rename_init_3',state['controllers'][3],state['previous'])
 for layout,nextlayout in ((3,0),(0,2)):
  u.mem_write(state['previous'],struct.pack('<I',DS[nextlayout]));m.call('af_ap_rename_leave_'+str(layout),state['controllers'][layout],state['previous'])
  models(0x2b36,0x15e7,DS[nextlayout]);m.call('af_ap_rename_init_'+str(nextlayout),state['controllers'][nextlayout],state['previous'])
 u.mem_write(state['addresses'][1],b'Four Layouts'+bytes(244));u.mem_write(manager+0x1e8,struct.pack('<I',0x4cf))
 m.call('af_ap_rename_done_2',state['controllers'][2]);_return(m,manager,models,state,2)
 assert m.call('af_ap_manage_take',m.symbols['af_ap_manager'],work+0x6400)==0
 assert m.call('af_ap_rename_title',0x15e7)==0x200aa01


@pytest.mark.parametrize('change',['current','working'])
def test_rename_queue_rechecks_actual_current_and_full_working_snapshot_before_pump(modules,change):
 m,manager,catalog,models,state=_keyboard(modules);u,work=m.u,m.work
 request=work+0x6400;name=b'Queued Name';raw=bytearray(176)
 struct.pack_into('<6I',raw,0,6,7,7,0,len(name),0);raw[106:106+len(name)]=name;u.mem_write(request,bytes(raw))
 assert m.call('af_ap_manage_submit',m.symbols['af_ap_manager'],catalog,request)==0
 if change=='current':state['selector']=0
 else:assert m.call('af_edit',catalog,7,0,4)==0
 state['catalog_before']=bytes(u.mem_read(catalog,6888))
 m.call('af_ap_refresh',manager)
 assert m.call('af_ap_manage_take',m.symbols['af_ap_manager'],request)==-2
 assert m.call('af_ap_manage_cancel',m.symbols['af_ap_manager'],1)==-5
 _return(m,manager,models,state)


def test_nonprivate_init_and_leave_keep_two_original_arguments_and_never_touch_keyboard_models(modules):
 from test_ap_ui_dynamic import Machine
 m=Machine(modules);m.registered();events=[]
 for kind in ('init','leave'):
  for index in range(4):
   def service(cpu,kind=kind,index=index):events.append((kind,index,cpu.reg_read(r.UC_ARM64_REG_X0),cpu.reg_read(r.UC_ARM64_REG_X1)))
   m.services[m.symbols[f'af_stock_rename_{kind}_{index}']]=service
   m.call(f'af_ap_rename_{kind}_{index}',m.work,m.work+0x100)
 assert events==[(kind,i,m.work,m.work+0x100) for kind in ('init','leave') for i in range(4)]
 assert m.call('af_ap_rename_state')==0
