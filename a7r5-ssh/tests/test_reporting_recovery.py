"""只使用保存的证据和替身，不观察主机设备，不访问网络。"""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import lab
import device

BASE = dict(location_id=0x01100000, model='ILCE-7RM5', pid=0x0e0a,
            drivers=['IOUSBMassStorageDriver'], media=[(False,10),(True,20)])


class ReportingRegression(unittest.TestCase):
    def test_failed_execution_has_nonzero_cli_status(self):
        for success,expected in ((False,3),(True,0),(None,3)):
            result={} if success is None else dict(execution_succeeded=success)
            with self.subTest(success=success),patch.object(sys,'argv',[
                    'lab.py','execute-preflight','--operation','/unused','--device-io']), \
                    patch.object(lab,'execute_preflight',return_value=result), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(lab.main(),expected)

    def test_media_pending_then_restored_is_not_permanent_failure(self):
        # 引擎已完成 STOP；只替换其返回值，不导入或调用真实设备后端。
        def session(output,transport,_operation):
            output.mkdir()
            return dict(preflight_complete=True,preload_neutral_verified=True,
                        ordinary_identity_restored=False,automatic_service_exit_permitted=True,
                        service_stop_attempts=1,service_stop_result='error',service_stop_error='Pipe error')
        class Pending(ValueError): pass
        now=[0.0]
        def sleep(seconds): now[0]+=seconds
        snapshots=iter([BASE,Pending('普通驱动或媒体未恢复'),BASE,BASE])
        def snapshot(**kwargs):
            item=next(snapshots)
            if isinstance(item,Exception): raise item
            return copy.deepcopy(item)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(sys.modules,{'system_dump.session':SimpleNamespace(run_session=session)}), \
                patch.object(device,'host_snapshot',side_effect=snapshot), \
                patch.object(device.time,'monotonic',side_effect=lambda:now[0]), \
                patch.object(device.time,'sleep',side_effect=sleep):
            # 修复后只把明确的过渡状态作为可继续观察的条件。
            if hasattr(device,'RecoveryPending'):
                snapshots=iter([BASE,device.RecoveryPending('普通驱动或媒体未恢复',{}),BASE,BASE])
            result=device.run_preflight(Path(tmp),{})
            self.assertTrue(result['execution_succeeded'])
            self.assertFalse(result['ordinary_identity_restored'])
            self.assertTrue(result['host_recovery_verified'])
            self.assertTrue(result['screen_confirmation_pending'])
            self.assertFalse(result['acceptance_complete'])
            evidence=json.loads((Path(tmp)/'result/host-recovery.json').read_text())
            self.assertEqual(len(evidence['observations']),3)
            self.assertIn('普通驱动或媒体未恢复',evidence['observations'][0]['error'])

    def test_cli_process_exit_contract(self):
        import subprocess
        for result,status in ((False,3),(True,0)):
            code=('import sys; sys.path.insert(0,'+repr(str(lab.ROOT))+'); import lab; '
                  'lab.execute_preflight=lambda *a: {"execution_succeeded":'+repr(result)+'}; '
                  'sys.argv=["lab.py","execute-preflight","--operation","/unused","--device-io"]; '
                  'sys.exit(lab.main())')
            child=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True,timeout=5)
            self.assertEqual(child.returncode,status,child.stderr)
            self.assertEqual(json.loads(child.stdout)['execution_succeeded'],result)

    def test_reports_created_after_engine_are_returned_to_workspace_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'result';output.mkdir();owner=output.parent.stat()
            with patch.object(device.os,'geteuid',return_value=0),patch.object(device.os,'chown') as chown:
                device.save_result(output,'new.json',dict(example=True))
            chown.assert_called_once_with(output/'new.json',owner.st_uid,owner.st_gid,follow_symlinks=False)
            self.assertEqual(json.loads((output/'new.json').read_text()),dict(example=True))
            with self.assertRaises(FileExistsError): device.save_result(output,'new.json',dict(example=False))

    def test_withheld_or_missing_stop_never_observes_recovery(self):
        for safe,attempts in ((False,0),(False,1),(True,0),(True,2)):
            def session(output,*args,**kwargs):
                output.mkdir()
                return dict(preflight_complete=True,preload_neutral_verified=True,
                            automatic_service_exit_permitted=safe,service_stop_attempts=attempts)
            with self.subTest(safe=safe,attempts=attempts),tempfile.TemporaryDirectory() as tmp, \
                    patch.dict(sys.modules,{'system_dump.session':SimpleNamespace(run_session=session)}), \
                    patch.object(device,'host_snapshot',return_value=copy.deepcopy(BASE)) as snapshot:
                report=device.run_preflight(Path(tmp),{})
                self.assertFalse(report['execution_succeeded'])
                self.assertEqual(snapshot.call_count,1)


class RecoveryContract(unittest.TestCase):
    def observe(self,sequence,seconds=8):
        now=[0.0];items=iter(sequence);calls=[]
        def snapshot(**kwargs):
            calls.append(kwargs)
            item=next(items)
            if isinstance(item,Exception): raise item
            return copy.deepcopy(item)
        def sleep(seconds): now[0]+=seconds
        with patch.object(device.time,'monotonic',side_effect=lambda:now[0]), \
                patch.object(device.time,'sleep',side_effect=sleep), \
                patch('subprocess.run',side_effect=AssertionError('测试禁止主机查询')):
            result=device.observe_recovery(BASE,snapshot,seconds=seconds,interval=2)
        return result,calls

    def test_stability_resets_and_partial_enumeration_can_complete(self):
        partial=copy.deepcopy(BASE);partial['media']=[(True,20)]
        result,calls=self.observe([BASE,partial,BASE,BASE])
        self.assertTrue(result['recovered']);self.assertEqual(len(calls),4)
        self.assertEqual([r['status'] for r in result['observations']],['matching','pending','matching','matching'])
        self.assertEqual(result['camera_requests_sent'],0)

    def test_unknown_identity_media_and_query_failures_stop_without_retry(self):
        variants=[]
        for key,value in (('pid',0x1234),('location_id',0x01200000),('model','ILCE-7CM2'),
                          ('media',[(False,11),(True,20)]),('media',[(True,20),(True,20)]),
                          ('drivers',['unexpected-driver'])):
            altered=copy.deepcopy(BASE);altered[key]=value;variants.append(altered)
        variants.append(OSError('主机查询失败'))
        variants.append(device.RecoveryPending('驱动尚未恢复',dict(media=[(True,999)],drivers=[])))
        for item in variants:
            with self.subTest(item=item):
                result,calls=self.observe([item])
                self.assertFalse(result['recovered']);self.assertEqual(len(calls),1)
                self.assertEqual(result['observations'][0]['status'],'rejected')

    def test_pending_state_has_finite_deadline_and_no_false_success(self):
        result,calls=self.observe([device.RecoveryPending('已知过渡',{})]*4)
        self.assertFalse(result['recovered']);self.assertEqual(len(calls),4)
        self.assertEqual(result['reason'],'host_recovery_timeout')
        self.assertTrue(all(0 < c['timeout'] <= 5 for c in calls))
        result,_=self.observe([BASE,BASE],seconds=2)
        self.assertFalse(result['recovered'])

    def test_saved_immediate_failure_and_followup_are_kept_separate(self):
        root=lab.ROOT.parent/'a7r5-ssh-live-20261020-preflight-01'
        original=(root/'evidence/preflight-result-original.json').read_bytes()
        failure=(root/'evidence/host-recovery-immediate.json').read_bytes()
        followup=json.loads((root/'host-recovery-followup.json').read_text())
        before={key:followup[key] for key in ('location_id','pid','model','media','drivers')}
        # 一次后续观察不补造第二次观察；历史收据不能套用新版稳定性门槛。
        self.assertFalse(json.loads(original)['execution_succeeded'])
        self.assertIn('普通驱动或媒体未恢复',json.loads(failure)['error'])
        self.assertEqual(before['pid'],0x0e0a)
        self.assertTrue(followup['media_matches_before'])
        self.assertEqual((root/'evidence/preflight-result-original.json').read_bytes(),original)

    def test_host_tree_classification_and_readonly_command(self):
        def tree(pid=0x0e0a,location=0x01100000,model='ILCE-7RM5',children=None):
            return [dict(IOObjectClass='IOUSBHostDevice',idVendor=0x054c,idProduct=pid,
                         locationID=location,**{'USB Product Name':model},
                         IORegistryEntryChildren=children or [])]
        children=[dict(IOObjectClass='IOUSBMassStorageDriver'),
                  dict(IOObjectClass='IOMedia',Whole=True,Size=20,**{'BSD Name':'disk9'}),
                  dict(IOObjectClass='IOMedia',Whole=False,Size=10,**{'BSD Name':'disk9s1'})]
        self.assertEqual(device.parse_host_tree(tree(children=children)),BASE)
        for raw in ([],tree(pid=0x0336),tree(pid=0x096f),tree()):
            with self.subTest(raw=raw),self.assertRaises(device.RecoveryPending): device.parse_host_tree(raw)
        for raw in (tree(pid=0x1234),tree(location=0x01200000),tree(model='ILCE-7CM2'),tree()+tree()):
            with self.subTest(raw=raw),self.assertRaises(ValueError) as caught: device.parse_host_tree(raw)
            self.assertNotIsInstance(caught.exception,device.RecoveryPending)
        import plistlib
        with patch('subprocess.run',return_value=SimpleNamespace(stdout=plistlib.dumps(tree(children=children)))) as run:
            self.assertEqual(device.host_snapshot(timeout=3),BASE)
        run.assert_called_once_with(['/usr/sbin/ioreg','-a','-l','-r','-c','IOUSBHostDevice'],
                                    capture_output=True,check=True,timeout=3)


class StopContract(unittest.TestCase):
    def test_engine_records_one_stop_even_when_pipe_error(self):
        # 使用真实会话函数和假的 USB 接口；所有主机命令与设备后端均被替换。
        lab.engine()
        import system_dump.session as session
        import usb.core
        import usb.util
        import usb.backend.libusb1
        class Camera:
            idProduct=0x0e0a;idVendor=0x054c;bus=1;port_numbers=(1,);iProduct=1;stop_count=0
            def get_active_configuration(self):
                return {(0,0):[SimpleNamespace(bmAttributes=2,bEndpointAddress=0x81),
                               SimpleNamespace(bmAttributes=2,bEndpointAddress=0x02)]}
            def ctrl_transfer(self,request,*args,**kwargs):
                if args[:3]==session.STOP:
                    self.stop_count+=1;self.idProduct=0x0e0a
                    raise OSError('Pipe error')
        camera=Camera()
        class Auth:
            def __init__(self,driver): self.driver=driver
            def start(self): pass
            def authenticate(self): self.driver.device.idProduct=0x0336
        class Operation:
            safe_to_stop=True
            def __call__(self,driver,output,log,report): report['preflight_complete']=True
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(sys.modules,{'pmca.usb.sony':SimpleNamespace(SonySenserAuthDevice=Auth)}), \
                patch.object(usb.core,'find',side_effect=lambda **kwargs:[camera]), \
                patch.object(usb.backend.libusb1,'get_backend',return_value=object()), \
                patch.object(usb.util,'get_string',return_value='ILCE-7RM5'), \
                patch.object(usb.util,'release_interface'),patch.object(usb.util,'dispose_resources'), \
                patch.object(session,'unmount_camera'),patch.object(session,'claim_interface',return_value=False), \
                patch('subprocess.run',side_effect=AssertionError('禁止真实主机命令')), \
                contextlib.redirect_stdout(io.StringIO()):
            output=Path(tmp)/'result';report=session.run_session(output,'libusb',_operation=Operation())
            self.assertEqual(camera.stop_count,1)
            self.assertEqual(report['service_stop_attempts'],1)
            self.assertEqual(report['service_stop_result'],'error')
            self.assertIn('Pipe error',report['service_stop_error'])
            self.assertTrue(report['ordinary_identity_restored'])
            self.assertNotIn('failure',report)
            events=[json.loads(line)['event'] for line in (output/'events.jsonl').read_text().splitlines()]
            self.assertEqual(events.count('stop_senser_attempted'),1)
            self.assertEqual(events.count('stop_senser_exception'),1)


if __name__=='__main__': unittest.main(verbosity=2)
