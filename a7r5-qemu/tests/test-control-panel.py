"""Qt 控件的能力门槛；假界面测试不作为原厂功能验收。"""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from PySide6.QtWidgets import QApplication
from client.control_panel import ControlPanel


class PanelContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_known_controls_follow_context_and_unknown_controls_stay_disabled(self):
        panel=ControlPanel()
        panel.set_available(True,'menu')
        self.assertTrue(panel.action_buttons['FRONT_DIAL_RIGHT'].isEnabled())
        self.assertFalse(panel.buttons['C1'].isEnabled())
        self.assertFalse(panel.mode_button.isEnabled())
        panel.set_available(True,'shooting_ready','P')
        self.assertTrue(panel.buttons['C1'].isEnabled())
        self.assertTrue(panel.mode_button.isEnabled())
        self.assertTrue(panel.physical_buttons['C4'].isEnabled())
        self.assertIn('触摸操作',panel.physical_buttons['C4'].text())
        self.assertFalse(panel.physical_buttons['TOUCH'].isEnabled())
        self.assertFalse(panel.action_buttons['FRONT_DIAL_RIGHT'].isEnabled())
        self.assertFalse(panel.physical_buttons['MOVIE'].isEnabled())
        self.assertFalse(panel.physical_buttons['SHUTTER_FULL'].isEnabled())
        panel.set_available(True,'shooting_ready',None)
        self.assertFalse(panel.mode_button.isEnabled())
        panel.set_available(False,'shooting_ready','P')
        self.assertFalse(any(b.isEnabled() for b in panel.action_buttons.values()))
        self.assertFalse(panel.mode_button.isEnabled())
        panel.close()


if __name__=='__main__':unittest.main()
