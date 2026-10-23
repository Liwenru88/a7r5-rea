"""串口或固件异常后不得继续追加客体请求；宿主仍须关闭和保存失败收据。"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/'tools'))
from menu_live import FirmwareFault, FirmwareMonitor
from media_candidate import MediaVM
spec=importlib.util.spec_from_file_location('media_probe_cleanup',LAB/'tools/probe_app.py')
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class FailedSession(unittest.TestCase):
    def test_explicit_model_rejection_stops_before_additional_guest_requests(self):
        for record in (b'MEDIA_AUX_UNSUPPORTED command=0x4073 body8=1\n',
                       b'MEDIA_RM_UNSUPPORTED op=99\n',b'MEDIA_DATAFLOW_FATAL transport=-1021\n'):
            with self.subTest(record=record),tempfile.TemporaryDirectory() as folder:
                console=Path(folder)/'console.log';console.write_bytes(b'normal\n'+record[:12])
                monitor=FirmwareMonitor(console);monitor.check()
                with console.open('ab') as log:log.write(record[12:])
                with self.assertRaises(FirmwareFault):monitor.check()
                with self.assertRaises(FirmwareFault):monitor.check()
        with tempfile.TemporaryDirectory() as folder:
            console=Path(folder)/'console.log'
            console.write_bytes(b'[ 42.1] [K] No snd_msg registered. Skip snd to 0x86f\n')
            FirmwareMonitor(console).check()

    def test_unknown_playback_frame_does_not_receive_return_keys(self):
        from media_playback_check import run
        with tempfile.TemporaryDirectory(dir=LAB/'build') as folder:
            vm=Mock(out=Path(folder));vm.last_native_screen.return_value=0x45f
            result=run(vm,{'steps':[{'frame':{'pixel_sha256':'unverified'}}]})
            vm.command.assert_not_called()
            self.assertEqual(result['status'],'requires-inspection')
            self.assertFalse(result['photo_playback_verified'])

    def test_unfinished_research_key_stops_before_next_key(self):
        with tempfile.TemporaryDirectory(dir=LAB/'build') as folder:
            vm=MediaVM.__new__(MediaVM);vm.out=Path(folder)
            vm.wait_native_screen=Mock();vm.last_native_screen=Mock(return_value=0x2d6)
            with patch('native_vm.NativeVM.command',side_effect=[b'MEDIA_PRIME_STARTED',b'MEDIA_PRIME_PENDING']) as command:
                with self.assertRaisesRegex(RuntimeError,'停止后续按键'):vm.prime_native_menu()
                self.assertEqual(command.call_count,2)
            receipt=json.loads((vm.out/'native-initialization.json').read_text())
            self.assertEqual(receipt['status'],'stopped')
            self.assertEqual([s['key'] for s in receipt['steps']],['MENU'])
            self.assertFalse(getattr(vm,'native_primed',False))

    def test_no_more_guest_commands_after_fault_or_serial_timeout(self):
        argv=['probe-app.py','--without-bluetooth','--software-gpe','--capid','--boot-services',
              '--gui-trace','--apply-menu','--candidate-inputs','initial-playback',
              '--media-candidate',str(LAB/'build/research-only'),'--virtual-media-rm']
        for error in (TimeoutError('unfinished serial command'),FirmwareFault('firmware exception'),ValueError('frame decode failed')):
            with self.subTest(error=type(error).__name__),tempfile.TemporaryDirectory(dir=LAB/'build') as folder:
                root=Path(folder);console=root/'console.log'
                preserved=b'MEDIA_IMAGING_REQUEST preserved\n'+(b'MEDIA_AUX_UNSUPPORTED command=0x4073 body8=1\n' if isinstance(error,ValueError) else b'')
                console.write_bytes(preserved)
                vm=Mock(out=root,console=console,candidate=LAB/'build/research-only')
                vm.command.side_effect=error
                vm.process.poll.return_value=None
                vm.close.return_value={'method':'mock-close','exit_code':0}
                with patch.object(sys,'argv',argv),patch('media_candidate.MediaVM',return_value=vm):
                    with self.assertRaises(FirmwareFault if isinstance(error,ValueError) else type(error)):probe.main()
                self.assertEqual(vm.command.call_count,1)
                vm.close.assert_called_once()
                result=json.loads((root/'result.json').read_text())
                self.assertEqual(result['status'],'failed')
                self.assertFalse(result['media_application_verified'])
                self.assertEqual((root/'media-imaging.log').read_bytes(),preserved.rstrip(b'\n'))


if __name__=='__main__':unittest.main()
