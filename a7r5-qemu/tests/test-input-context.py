"""帮助弹层关闭不一定产生 manager apply；不能据旧日志开放控制。"""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from input_context import InputContext


class ContextContract(unittest.TestCase):
    def test_menu_group_reentry_preserves_navigation_without_enabling_item_help(self):
        context=InputContext()
        context.observe('INITIAL','items',0x2d6)
        self.assertEqual(context.observe('LEFT','groups',0x2d5),'menu_group')
        self.assertEqual(context.observe('MENU','shoot',0),'shooting')
        self.assertEqual(context.observe('MENU','groups',0x2d5),'menu_group')
        self.assertEqual(context.observe('RIGHT','items',0x2d6),'menu')
        self.assertEqual(context.observe('LEFT','unknown',0x2d7),'unknown')

    def test_original_setup_must_finish_before_function_context(self):
        context=InputContext()
        context.observe('INITIAL','menu',0x2d6,0)
        self.assertEqual(context.observe('MENU','shoot',0),'shooting')
        context.observe('MENU','menu',0x2d6)
        self.assertEqual(context.observe('INITIAL_SETUP','notice',0x1e3,0),'initial_setup')
        self.assertEqual(context.observe('ENTER','app-guide',0x1e0),'setup_on_camera')
        self.assertEqual(context.observe('C4','camera-setup',0x1c8),'initial_setup')
        self.assertEqual(context.observe('ENTER','unfinished',0x355,1),'initial_setup')
        self.assertEqual(context.observe('ENTER','finished',0x355,2),'setup_complete')
        self.assertEqual(context.observe('MENU','menu',0x2d6),'menu')
        self.assertEqual(context.observe('MENU','shoot',0),'shooting_ready')
        self.assertEqual(context.observe('DISP','viewfinder',2),'shooting_ready')

    def test_function_popup_and_empty_playback_roundtrips(self):
        context=InputContext()
        context.observe('MENU','shoot',0,2)
        self.assertEqual(context.observe('FN','fn',0xc2),'fn')
        self.assertEqual(context.observe('RIGHT','fn-next',0xc2),'fn')
        self.assertEqual(context.observe('ENTER','auto-mode-notice',0x34f),'fn_notice')
        self.assertEqual(context.observe('ENTER','fn-next',0x34f),'fn')
        self.assertEqual(context.observe('LEFT','fn-left',0x34f),'fn')
        self.assertEqual(context.observe('FN','shoot',0),'shooting_ready')
        self.assertEqual(context.observe('PLAYBACK','no-card',0x45f),'playback_empty')
        self.assertEqual(context.observe('PLAYBACK','shoot',0),'shooting_ready')

    def test_option_help_returns_to_option_and_commit_returns_to_menu(self):
        context = InputContext()
        context.observe('INITIAL', 'menu-frame', 0x2d6)
        self.assertEqual(context.observe('ENTER', 'option-off', 0x2ed), 'menu_option')
        self.assertEqual(context.observe('C4', 'option-help', 0x259), 'guide')
        self.assertEqual(context.observe('ENTER', 'option-off', 0x259), 'menu_option')
        self.assertEqual(context.observe('UP', 'option-on', 0x259), 'menu_option')
        self.assertEqual(context.observe('ENTER', 'menu-on', 0x259), 'menu')

    def test_missing_page_log_does_not_prove_menu_context(self):
        context = InputContext()
        context.observe('INITIAL', 'menu', 0x2d6)
        self.assertEqual(context.observe('RIGHT', 'new-frame', None), 'unknown')
        self.assertEqual(context.observe('ENTER', 'unanchored-option', 0x2ed), 'unknown')
        context = InputContext()
        context.observe('INITIAL', 'menu', 0x2d6)
        context.observe('ENTER', 'option', 0x2ed)
        self.assertEqual(context.observe('ENTER', 'missing-page', None), 'unknown')

    def test_roundtrip_uses_real_frame_when_open_log_is_stale(self):
        context = InputContext()
        self.assertEqual(context.observe('INITIAL', 'menu-frame', 0x2d6), 'menu')
        self.assertEqual(context.observe('C4', 'guide-frame', 0x259), 'guide')
        self.assertEqual(context.observe('ENTER', 'menu-frame', 0x259), 'menu')
        self.assertEqual(context.observe('RIGHT', 'next-menu-frame', 0x259), 'menu')

    def test_unexpected_guide_frame_and_shooting_do_not_allow_c4(self):
        context = InputContext()
        context.observe('INITIAL', 'menu', 0x2d6)
        context.observe('C4', 'guide', 0x259)
        self.assertEqual(context.observe('ENTER', 'unexpected', 0x259), 'unknown')
        self.assertEqual(context.observe('MENU', 'shooting', 0), 'shooting')
        self.assertEqual(context.observe('MENU', 'menu', 0x2d6), 'menu')


if __name__ == '__main__':
    unittest.main()
