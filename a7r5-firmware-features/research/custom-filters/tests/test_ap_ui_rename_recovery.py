"""资格丢失/HELP后的原离页收尾；只验证隔离模块，不运行VM或真实设置。"""
import struct
import pytest
from unicorn import arm64_const as r
from test_ap_ui_dynamic import modules  # noqa: F401
from test_ap_ui_rename import _keyboard, SIZES, DS, VT


@pytest.mark.parametrize('anomaly',['group','purpose','help'])
def test_rename_lost_qualification_and_help_restore_models_without_submitting(modules,anomaly):
 m,manager,catalog,models,state=_keyboard(modules);u,work=m.u,m.work
 # 同一类型但不是本会话owner必须完整委派，不能抢占/清理私有会话。
 foreign=work+0x39000;m.map(foreign,0x600)
 u.mem_write(foreign,struct.pack('<Q',m.base+VT[1]));u.mem_write(foreign+0x178,struct.pack('<I',DS[1]));u.mem_write(foreign+0x180,struct.pack('<Q',manager))
 u.mem_write(state['previous'],struct.pack('<I',0x2ed))
 before=b''.join(bytes(u.mem_read(a,n)) for a,n in zip(state['addresses'],SIZES))
 m.call('af_ap_rename_leave_1',foreign,state['previous'])
 assert state['leave'][-1]==(1,foreign) and m.call('af_ap_rename_state')==2
 assert b''.join(bytes(u.mem_read(a,n)) for a,n in zip(state['addresses'],SIZES))==before

 if anomaly=='help':
  value=b'Candidate Before Help';u.mem_write(state['addresses'][1],value+bytes(256-len(value)));u.mem_write(manager+0x1e8,struct.pack('<I',0x4cf))
  m.call('af_ap_rename_done_1',state['controllers'][1])
  u.mem_write(state['previous'],struct.pack('<I',0x259));m.call('af_ap_rename_leave_1',state['controllers'][1],state['previous'])
  assert m.call('af_ap_rename_state')==2
  # 保持原草稿的显式夹具，不能依赖HELP返回恰好重置文本来挡陈旧Done。
  models(0x2b36,0x15e7,0xcd);m.call('af_ap_rename_init_1',state['controllers'][1],state['previous']);layout=1;group=0x15e7
 else:
  group=0x7f if anomaly=='group' else 0x15e7
  if anomaly=='purpose':u.mem_write(state['addresses'][6],struct.pack('<I',14))
  models(0x2b36,group,0xcd)
  # 资格变化后先换CF；稳定owner仍须跟踪，原leave服务必须看见用途11。
  u.mem_write(state['previous'],struct.pack('<I',0xcf));m.call('af_ap_rename_leave_1',state['controllers'][1],state['previous'])
  assert state['leave'][-1]==(1,state['controllers'][1])
  assert struct.unpack('<I',u.mem_read(state['addresses'][6],4))[0]==11
  models(0x2b36,group,0xcf);m.call('af_ap_rename_init_2',state['controllers'][2],state['previous']);layout=2
  assert m.call('af_ap_rename_state')==2
  # 用途已由保护写回11，group若恢复也不能消除本会话的tainted状态。
  group=0x15e7;models(0x2b36,group,0xcf)
  value=b'No Commit After Lost Owner Gate';u.mem_write(state['addresses'][1],value+bytes(256-len(value)));u.mem_write(manager+0x1e8,struct.pack('<I',0x4cf))
  m.call('af_ap_rename_done_2',state['controllers'][2])

 u.mem_write(state['previous'],struct.pack('<I',0x2ed));m.call('af_ap_rename_leave_'+str(layout),state['controllers'][layout],state['previous'])
 assert m.call('af_ap_rename_state')==3
 assert struct.unpack('<I',u.mem_read(state['addresses'][6],4))[0]==11
 models(0x2b36,0x15e7,0x2ed);m.call('af_ap_refresh',manager)
 assert state['opens'][-1]==(0x2ed,0xd4)
 # 原parent呈现前不得提前还原用途；apply后一次性还原全部548字节。
 assert struct.unpack('<I',u.mem_read(state['addresses'][6],4))[0]==11
 models(0x1603,0x15e7,0xd4);m.call('af_ap_refresh',manager)
 assert m.call('af_ap_rename_state')==0 and m.call('af_ap_manage_ui_state')==0
 assert b''.join(bytes(u.mem_read(a,n)) for a,n in zip(state['addresses'],SIZES))==state['original']
 assert bytes(u.mem_read(catalog,6888))==state['catalog_before']
 assert m.call('af_ap_manage_take',m.symbols['af_ap_manager'],work+0x6400)==-2


def test_rename_restores_when_poll_misses_the_keyboard_between_original_init_and_leave(modules):
 m,manager,catalog,models,state=_keyboard(modules,skip_presented_poll=True);u=m.u
 u.mem_write(state['previous'],struct.pack('<I',0x2ed))
 m.call('af_ap_rename_leave_1',state['controllers'][1],state['previous'])
 assert m.call('af_ap_rename_state')==3
 models(0x2b36,0x15e7,0x2ed);m.call('af_ap_refresh',manager)
 assert m.call('af_ap_manage_ui_state')==6
 m.call('af_ap_refresh',manager);assert state['opens'][-1]==(0x2ed,0xd4)
 models(0x1603,0x15e7,0xd4);m.call('af_ap_refresh',manager)
 assert m.call('af_ap_rename_state')==0 and m.call('af_ap_manage_ui_state')==0
 assert b''.join(bytes(u.mem_read(a,n)) for a,n in zip(state['addresses'],SIZES))==state['original']
 assert bytes(u.mem_read(catalog,6888))==state['catalog_before']
 assert m.call('af_ap_manage_take',m.symbols['af_ap_manager'],m.work+0x6400)==-2
