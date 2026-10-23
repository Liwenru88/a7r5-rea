"""新增固定入口不接受页面编号、脚本或未结构化的功能键。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from menu_bridge import validate_request
from menu_live import KEYS,RESEARCH_KEYS,key_command
from emu_session import EmulatorSession


class FunctionProtocol(unittest.TestCase):
    def test_fixed_setup_request_rejects_arbitrary_data(self):
        good={'id':'a'*32,'action':'initial_setup','key':None}
        validate_request(good)
        for change in ({'key':'ENTER'},{'key':0x1e3},{'screen':0x1e3},{'command':'anything'},{'action':'shell'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_request(dict(good,**change))

    def test_display_is_verified_wheel_up_and_http_cannot_send_raw_function_keys(self):
        self.assertEqual(KEYS['DISP'],KEYS['UP'])
        self.assertEqual(RESEARCH_KEYS['DISP_LEGACY'],'0x1f9')
        self.assertIn(' 0x3 0 1 0 1',key_command('DISP'))
        session=EmulatorSession.__new__(EmulatorSession)
        session.status=Mock(side_effect=AssertionError('未通过验证不得派发'))
        for key in ('FN','DISP','PLAYBACK','C1','C2','C3','MODE_P','FRONT_DIAL_RIGHT','JOYSTICK_CENTER'):
            with self.subTest(key=key),self.assertRaises(ValueError):
                session.command({'action':'key','key':key})
        session.status.assert_not_called()


if __name__=='__main__':unittest.main()
