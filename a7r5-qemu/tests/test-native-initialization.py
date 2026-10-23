"""验证首次初始化只确认已知页面，未知页面停止，不重复初始化。"""
from pathlib import Path
import json,sys,unittest
from unittest.mock import patch,Mock
LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/'tools'))
from native_vm import NativeVM
from vm_session import VM


class InitializationContract(unittest.TestCase):
    def test_live_menu_wait_accepts_only_the_two_proven_pages(self):
        vm=self.make_vm();vm.last_native_screen=Mock(return_value=0x2d5)
        vm.console.write_bytes(b'')
        with patch('native_vm.time.monotonic',side_effect=[0,0]),patch('native_vm.time.sleep'):
            vm.wait_native_screen((0x2d5,0x2d6))
        vm.last_native_screen=Mock(return_value=0x2d7)
        vm.process=Mock();vm.process.poll.return_value=None
        with patch('native_vm.time.monotonic',side_effect=[0,0,16]),patch('native_vm.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'页面不符'):
                vm.wait_native_screen((0x2d5,0x2d6))

    def make_vm(self):
        vm=NativeVM('initialization-contract',capid=True,boot_services=True)
        vm.last_native_screen=Mock(return_value=0x2d6)
        return vm

    def test_known_guide_is_acknowledged_once_then_ready(self):
        vm=self.make_vm();vm.wait_native_screen=Mock()
        with patch.object(VM,'command',return_value=b'ok') as command:
            vm.prime_native_menu()
            self.assertEqual(command.call_count,5)
            self.assertIn('0x1ac',command.call_args_list[3].args[0])
            self.assertEqual([c.args[0] for c in vm.wait_native_screen.call_args_list],[0x2d6,0x355,0x2d6,0x1e9,0,0x2d6])
            result=json.loads((vm.out/'native-initialization.json').read_text())
            self.assertEqual(result['status'],'ready')
            self.assertTrue(result['touch_guide_acknowledged_by_original_enter'])
            with self.assertRaises(RuntimeError):vm.prime_native_menu()
            self.assertEqual(command.call_count,5)

    def test_snapshot_resumes_then_confirms_idle_pause(self):
        for command in ('/simulation/headless-osd-export', '/simulation/headless-osd-export --after 2'):
            vm=self.make_vm();vm.native_reentry=True;vm.native_paused=True
            vm.set_native_paused=Mock()
            with patch.object(VM,'command',return_value=b'frame'):
                self.assertEqual(vm.command(command),b'frame')
            self.assertEqual([c.args[0] for c in vm.set_native_paused.call_args_list],[False,True])

    def test_failed_command_is_not_reported_as_idle_success(self):
        vm=self.make_vm();vm.native_reentry=True;vm.native_paused=True
        vm.set_native_paused=Mock()
        with patch.object(VM,'command',side_effect=RuntimeError('transfer failed')):
            with self.assertRaisesRegex(RuntimeError,'transfer failed'):
                vm.command('/simulation/headless-osd-export')
        self.assertEqual([c.args[0] for c in vm.set_native_paused.call_args_list],[False])

    def test_wrong_modal_stops_before_enter(self):
        vm=self.make_vm();vm.wait_native_screen=Mock(side_effect=[None,None,None,RuntimeError('wrong modal')])
        with patch.object(VM,'command',return_value=b'ok') as command:
            with self.assertRaisesRegex(RuntimeError,'wrong modal'):vm.prime_native_menu()
            self.assertEqual(command.call_count,3)
            self.assertTrue(all('0x1ac' not in c.args[0] for c in command.call_args_list))
            result=json.loads((vm.out/'native-initialization.json').read_text())
            self.assertEqual(result['status'],'in-progress')
            self.assertFalse(getattr(vm,'native_primed',False))


if __name__=='__main__':unittest.main()
