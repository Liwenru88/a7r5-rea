"""原键盘已离页且D4实际已呈现后，父组失配须拒绝并还原；不模拟open前失败。"""
import struct
from test_ap_ui_dynamic import modules  # noqa: F401
from test_ap_ui_rename import _keyboard, SIZES


def test_rename_restores_after_actual_d4_but_parent_group_was_replaced(modules):
 m,manager,catalog,models,state=_keyboard(modules);u,work=m.u,m.work
 value=b'Never Commit In Wrong Parent';u.mem_write(state['addresses'][1],value+bytes(256-len(value)))
 u.mem_write(manager+0x1e8,struct.pack('<I',0x4cf));m.call('af_ap_rename_done_1',state['controllers'][1])
 u.mem_write(state['previous'],struct.pack('<I',0x2ed));m.call('af_ap_rename_leave_1',state['controllers'][1],state['previous'])
 assert m.call('af_ap_rename_state')==3
 models(0x2b36,0x15e7,0x2ed);m.call('af_ap_refresh',manager)
 assert m.call('af_ap_manage_ui_state')==7 and state['opens'][-1]==(0x2ed,0xd4)
 assert struct.unpack('<I',u.mem_read(state['addresses'][6],4))[0]==11
 # 已观察到D4真实物理状态；仅逻辑父组不同，不是仍在Main等待原open消费。
 models(0x2b36,0x1e7,0xd4);m.call('af_ap_refresh',manager)
 assert m.call('af_ap_rename_state')==0
 assert m.call('af_ap_manage_ui_state')==0 and m.call('af_ap_manage_ui_result')==-5
 assert b''.join(bytes(u.mem_read(a,n)) for a,n in zip(state['addresses'],SIZES))==state['original']
 assert bytes(u.mem_read(catalog,6888))==state['catalog_before']
 assert m.call('af_ap_manage_take',m.symbols['af_ap_manager'],work+0x6400)==-2
 # 收尾之后允许正常关闭研究开关，不再因泄漏会话一直BUSY。
 assert m.call('af_ap_research_enable',0)==0
