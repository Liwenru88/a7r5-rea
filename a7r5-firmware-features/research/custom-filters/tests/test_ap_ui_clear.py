"""实际selector保护在begin、chosen、pump前重验；原服务边界明示。"""
import struct
import pytest
from unicorn import arm64_const as regs
from test_ap_ui_lifecycle import _owner
from test_ap_ui_dynamic import modules  # noqa: F401


def _clear(raw):
 m,manager,catalog,models,state=_owner(raw);u,work=m.u,m.work
 state['selector']=19
 u.mem_write(work+0x424,bytes(4))
 m.services[m.base+0x28bfdcc]=lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,work+0x424)
 m.services[m.base+0x17ffd84]=lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,0)
 # 原current getter的服务边界：新UI实际调用自己的af_ap_current，再用真实route映射。
 m.services[m.base+0x1c05f18]=lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,state['selector'])
 m.services[m.base+0x1bdb214]=lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,0x15ec)
 for slot in (7,20):
  p=bytearray(74);p[8]=3;u.mem_write(work+0x6100,bytes(p));assert m.call('af_install',catalog,slot,work+0x6100,0)==0
 models(0x1602,0x15e7,0xd4);assert m.call('af_ap_manage_ui_open',catalog,5,0)==0
 assert m.call('af_ap_targets_available',0x15f3)==0 # C07当前槽受保护。
 assert m.call('af_ap_targets_available',0x1600)==1
 models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
 models(0x1600,0x15ec,0xd4);m.call('af_ap_refresh',manager)
 assert m.call('af_ap_targets_intent',0x1600)==0;m.call('af_ap_targets_action',0x1600)
 assert m.call('af_ap_targets_result')==-24
 models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
 models(0x1601,0x15ec,0xd4);m.call('af_ap_refresh',manager)
 assert m.call('af_ap_targets_stage')==3 and m.call('af_ap_manage_ui_state')==3
 return m,manager,catalog,models,state


@pytest.mark.parametrize('change',['none','before-chosen','before-pump','unknown-before-pump','restricted-before-pump','reset-before-pump','menu-cancel'])
def test_clear_current_slot_rechecked_at_each_actual_ui_boundary(modules,change):
 m,manager,catalog,models,state=_clear(modules);u,work=m.u,m.work;owner=m.symbols['af_ap_manager']
 before=bytes(u.mem_read(catalog,6888));job=work+0x6400
 if change=='menu-cancel':
  models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
  assert m.call('af_ap_targets_result')==-23 and m.call('af_ap_manage_take',owner,job)==-2
  assert bytes(u.mem_read(catalog,6888))==before
  return
 if change=='before-chosen':state['selector']=32
 models(0x1600,0x15ec,0xd4)
 assert m.call('af_ap_targets_intent',0x1600)==0;m.call('af_ap_targets_action',0x1600)
 if change=='before-chosen':
  assert m.call('af_ap_targets_result')==-5 and m.call('af_ap_manage_take',owner,job)==-2
 elif change in ('before-pump','unknown-before-pump','restricted-before-pump','reset-before-pump'):
  state['selector']={'before-pump':32,'unknown-before-pump':999,'restricted-before-pump':0,'reset-before-pump':16}[change]
  if change=='restricted-before-pump':u.mem_write(work+0x424,struct.pack('<I',1))
  m.call('af_ap_refresh',manager)
  assert m.call('af_ap_manage_take',owner,job)==-2
  # 接收失败回执，不调用后台I/O，且catalog原字节不动。
  assert m.call('af_ap_manage_cancel',owner,1)==-5
 else:
  assert m.call('af_ap_manage_take',owner,job)==0
  assert struct.unpack('<Q4I',u.mem_read(job,24))==(1,5,0,20,1)
  raw=bytes(u.mem_read(job+8,176))
  assert raw[16:]==bytes(160) # 无名称、媒体、基底或默认八参数。
 assert bytes(u.mem_read(catalog,6888))==before and state['scan']==state['read']==0
