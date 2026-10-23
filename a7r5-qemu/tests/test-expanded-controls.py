"""固定步进、上下文和未实现控制不能被界面配置绕过。"""
import json
import hashlib
import zlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from input_registry import InputRegistry
from input_context import InputContext
from menu_live import KEYS,SINGLE_STATUS,TAP_STATUS,key_command
from control_actions import request_for_action
from mode_state import wait_mode_frame,displayed_mode,shooting_signature


class ExpandedControls(unittest.TestCase):
    def setUp(self):
        self.registry = InputRegistry.load()

    def test_each_dial_accepts_exactly_one_signed_step(self):
        for control in ('FRONT_DIAL','REAR_DIAL_L','REAR_DIAL_R','CONTROL_WHEEL'):
            for value, suffix in ((-1,'LEFT'),(1,'RIGHT')):
                request = dict(action='input',control=control,event='rotate',value=value)
                with self.subTest(control=control,value=value):
                    self.assertEqual(self.registry.resolve(request,'menu'), control+'_'+suffix)
            for value in (0,2,-2,True,1.0,'1',None):
                with self.subTest(control=control,invalid=value), self.assertRaises(ValueError):
                    self.registry.resolve(dict(action='input',control=control,event='rotate',value=value),'menu')
            with self.assertRaises(ValueError):
                self.registry.resolve(dict(action='input',control=control,event='rotate',value=1),'shooting_ready')

    def test_custom_keys_do_not_become_active_in_unverified_contexts(self):
        for control in ('C1','C2','C3'):
            request = dict(action='input',control=control,event='tap',value=None)
            self.assertEqual(self.registry.resolve(request,'shooting_ready'),control)
            for context in ('menu','unknown','shooting','custom_notice','custom_setting'):
                with self.subTest(control=control,context=context), self.assertRaises(ValueError):
                    self.registry.resolve(request,context)
        for control in ('SHUTTER_FULL','SHUTTER_HALF','MOVIE','AF_ON','TOUCH'):
            self.assertFalse(self.registry.available(control,'shooting_ready'))

    def test_dials_use_distinct_proven_codes_and_not_press_release(self):
        for control,code,step in (('FRONT_DIAL','0x1000001c',30),('REAR_DIAL_L','0x10000013',1024),
                                  ('REAR_DIAL_R','0x10000016',30),('CONTROL_WHEEL','0x1000001d',24)):
            for value,suffix in ((-1,'LEFT'),(1,'RIGHT')):
                action=control+'_'+suffix
                self.assertEqual(KEYS[action],code)
                self.assertEqual(int(SINGLE_STATUS[action],0),(step*value)&0xffffffff)
                self.assertEqual(key_command(action).count('/simulation/inject-key'),1)
                self.assertEqual(request_for_action(action),dict(action='input',control=control,event='rotate',value=value))

    def test_page_focus_and_custom_popups_require_verified_returns(self):
        context=InputContext();context.observe('INITIAL','menu',0x2d6)
        self.assertEqual(context.observe('REAR_DIAL_L_RIGHT','page',0x2d6),'menu_page')
        self.assertFalse(self.registry.available('C4','menu_page'))
        self.assertEqual(context.observe('CONTROL_WHEEL_RIGHT','item',0x2d6),'menu')
        context.observe('MENU','shooting',0,2,'stable')
        self.assertEqual(context.observe('C1','notice',0x34f,stable_pixel='notice'),'custom_notice')
        self.assertEqual(context.observe('ENTER','blink-changed',0x34f,stable_pixel='stable'),'shooting_ready')
        self.assertEqual(context.observe('C3','focus',0xd4,stable_pixel='focus'),'custom_setting')
        context.observe('DOWN','mf',0xd4,stable_pixel='mf')
        self.assertEqual(context.observe('ENTER','lens-error',0x332),'custom_setting_notice')
        self.assertEqual(context.observe('ENTER','mf',0x332),'custom_setting')
        self.assertEqual(context.observe('MENU','shooting',0,stable_pixel='stable'),'shooting_ready')
        context.observe('C2','notice',0x34f,stable_pixel='notice')
        self.assertEqual(context.observe('ENTER','wrong',0x34f,stable_pixel='wrong'),'unknown')

    def test_mode_selection_has_fixed_values_and_waits_for_target_frame(self):
        calls=[]
        def sample(attempt,after):
            calls.append((attempt,after))
            return b'png',dict(sequence=after+1,shooting_mode='P' if attempt else 'AUTO')
        png,info,attempt=wait_mode_frame(sample,'P',10)
        self.assertEqual((info['shooting_mode'],attempt,calls),('P',1,[(0,10),(1,11)]))
        with self.assertRaises(TimeoutError):
            wait_mode_frame(lambda *_:(b'old',dict(sequence=1,shooting_mode='AUTO')),'P',0,timeout=0)
        self.assertIsNone(displayed_mode(bytes(640*480*2)))
        with self.assertRaises(ValueError):displayed_mode(b'wrong')
        for mode,status in (('AUTO',2),('P',3),('S',4),('A',5),('M',6)):
            request=dict(action='input',control='MODE_DIAL',event='select',value=mode)
            self.assertEqual(self.registry.resolve(request,'shooting_ready'),'MODE_'+mode)
            self.assertEqual(int(SINGLE_STATUS['MODE_'+mode],0),status)
        for value in (1,True,'MR1','anything',None):
            with self.assertRaises(ValueError):
                self.registry.resolve(dict(action='input',control='MODE_DIAL',event='select',value=value),'shooting_ready')

    def test_joystick_is_an_independent_five_way_event_not_navigation_alias(self):
        for direction,status in (('UP',1),('DOWN',2),('LEFT',4),('RIGHT',8),('CENTER',16)):
            action='JOYSTICK_'+direction
            request=dict(action='input',control='JOYSTICK',event='pad',value=direction)
            self.assertEqual(self.registry.resolve(request,'menu'),action)
            self.assertEqual(KEYS[action],'0x70f7')
            self.assertEqual(int(TAP_STATUS[action],0),status)
            self.assertEqual(key_command(action).count('/simulation/inject-key'),2)
            self.assertFalse(self.registry.available('JOYSTICK','shooting_ready'))
        for direction in (True,'UP_LEFT','anything',1,None):
            with self.assertRaises(ValueError):
                self.registry.resolve(dict(action='input',control='JOYSTICK',event='pad',value=direction),'menu')

    def test_touch_toggle_notice_does_not_break_verified_popup_return(self):
        pixels=bytearray(640*480*2);reference=shooting_signature(pixels)
        pixels[(390*640+170)*2]=1
        self.assertEqual(shooting_signature(pixels),reference)
        pixels[(390*640+50)*2]=1
        self.assertNotEqual(shooting_signature(pixels),reference)
        context=InputContext();context.observe('MENU','shoot',0,2,reference)
        self.assertEqual(context.observe('C4','touch-off',0,stable_pixel=reference),'shooting_ready')
        context.observe('C1','notice',0x34f,stable_pixel='notice')
        self.assertEqual(context.observe('ENTER','shoot',0x34f,stable_pixel=reference),'shooting_ready')
        self.assertTrue(self.registry.available('C4','shooting_ready'))

    def test_real_touch_toast_alpha_plane_returns_to_the_same_shooting_page(self):
        folder=ROOT/'tests/fixtures'
        meta=json.loads((folder/'touch-toast-pixels.json').read_text())
        raw=zlib.decompress((folder/'touch-toast-pixels.zlib').read_bytes());size=meta['frame_bytes']
        self.assertEqual(len(raw),size*4)
        frames=[raw[i*size:(i+1)*size] for i in range(4)]
        self.assertEqual([hashlib.sha256(x).hexdigest() for x in frames],meta['pixel_sha256'])
        for i in (0,2):
            self.assertEqual(shooting_signature(frames[i]),shooting_signature(frames[i+1]))


if __name__=='__main__':
    unittest.main()
