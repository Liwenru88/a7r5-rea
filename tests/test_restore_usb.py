"""USB恢复脚本的离线回归，不连接相机、不加载USB后端。"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('usb_restore_script',ROOT/'scripts/restore_usb.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def report():return dict(stop_attempts=0,stop_result='not_attempted')


class Device:
    idVendor=0x054c;idProduct=0x0336;bus=1;port_numbers=[1]
    def __init__(self,error=False):self.calls=[];self.error=error
    def ctrl_transfer(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        if self.error:raise OSError(32,'Pipe error')
    def get_active_configuration(self):
        endpoints=[SimpleNamespace(bEndpointAddress=n,bmAttributes=2,wMaxPacketSize=512,bInterval=0) for n in (129,2,131,4)]
        class Interface(list):
            bInterfaceNumber=0;bAlternateSetting=0;bInterfaceClass=255;bInterfaceSubClass=0;bInterfaceProtocol=0
        return {(0,0):Interface(endpoints)}


class Timer:
    now=0
    def clock(self):return self.now
    def sleep(self,seconds):self.now+=seconds


def state(kind='ordinary',location=0x01100000,media=True):
    return dict(kind=kind,location_id=location,model='ILCE-7RM5' if kind=='ordinary' else None,
        drivers=['IOUSBMassStorageDriver'] if kind=='ordinary' else [],media=[[True,12345]] if media else [])


@pytest.mark.parametrize('error',[False,True])
def test_usb_restore_script_stop_is_exactly_once_even_on_pipe(error):
    device=Device(error);result=report();r.stop_once(device,result)
    assert device.calls==[((0x43,1,0xc800,0x2855,b''),{'timeout':5000})]
    with pytest.raises(PermissionError):r.stop_once(device,result)
    assert len(device.calls)==1 and result['stop_result']==('error' if error else 'returned')


@pytest.mark.parametrize('location,bus,ports',[(0x01100000,1,[1]),(0x02320000,2,[3,2])])
def test_usb_restore_script_auto_selects_current_port(location,bus,ports):
    device=Device();device.bus=bus;device.port_numbers=ports
    assert r.select_service([device],location) is device and not device.calls


@pytest.mark.parametrize('bad',['multiple','port','pid','interface'])
def test_usb_restore_script_rejects_mismatched_device_before_stop(bad):
    device=Device();devices=[device]
    if bad=='multiple':devices.append(Device())
    if bad=='port':device.port_numbers=[2]
    if bad=='pid':device.idProduct=0x096f
    if bad=='interface':device.get_active_configuration=lambda:{(0,0):[]}
    with pytest.raises((ValueError,AttributeError)):r.select_service(devices,0x01100000)
    assert not device.calls


@pytest.mark.parametrize('media',[False,True])
def test_usb_restore_script_ordinary_does_not_send_stop_or_bind_card_capacity(media):
    timer=Timer();result=report();observations=[]
    def take(*a,**k):observations.append(1);return state(media=media)
    def forbidden(*a):raise AssertionError('普通USB不应访问USB后端')
    r.recover(state(),take,forbidden,result,clock=timer.clock,sleep=timer.sleep)
    assert result['ordinary_usb_restored'] and len(observations)==2 and result['stop_attempts']==0
    assert result['host_recovery']['media_detected']==media
    assert not result['host_recovery']['historical_media_baseline_checked']


def test_usb_restore_script_pipe_error_kept_while_only_observing_afterwards():
    timer=Timer();device=Device(True);result=report();trace=[]
    def stop(initial,value):trace.append('stop');r.stop_once(device,value)
    def take(*a,**k):trace.append('host');return state()
    r.recover(state('service'),take,stop,result,clock=timer.clock,sleep=timer.sleep)
    assert trace==['stop','host','host'] and result['ordinary_usb_restored']
    assert 'Pipe error' in result['stop_error'] and len(device.calls)==1


def test_usb_restore_script_transition_timeout_has_no_stop_or_retry():
    timer=Timer();result=report()
    def forbidden(*a):raise AssertionError('096f不发送STOP')
    with pytest.raises(RuntimeError):r.recover(state('transition'),lambda *a,**k:state('transition'),forbidden,result,clock=timer.clock,sleep=timer.sleep)
    assert timer.now==45 and not result['ordinary_usb_restored'] and result['stop_attempts']==0


def test_usb_restore_script_port_change_stops_observation_immediately():
    timer=Timer();observations=[]
    def take(*a,**k):observations.append(1);return state(location=0x01200000)
    with pytest.raises(ValueError):r.recover(state(),take,lambda *a:None,report(),clock=timer.clock,sleep=timer.sleep)
    assert len(observations)==1 and timer.now==0


def test_usb_restore_script_held_lock_blocks_before_usb(monkeypatch):
    opened=[];closed=[]
    def opened_fd(path,flags,mode):opened.append((str(path),flags));return 99
    monkeypatch.setattr(r.os,'open',opened_fd)
    monkeypatch.setattr(r.os,'close',lambda fd:closed.append(fd))
    monkeypatch.setattr(r.os,'fstat',lambda fd:SimpleNamespace(st_mode=0o100600,st_nlink=1,st_uid=0))
    def busy(*a):raise BlockingIOError()
    monkeypatch.setattr(r.fcntl,'flock',busy)
    with pytest.raises(PermissionError):
        with r.device_locks():raise AssertionError('不应进入设备操作')
    assert len(opened)==1 and closed==[99] and opened[0][1]&r.os.O_NOFOLLOW


def test_usb_restore_script_cli_help_and_missing_sudo_never_observe(monkeypatch):
    monkeypatch.setattr(r.host,'snapshot',lambda *a,**k:pytest.fail('不应读取设备'))
    with pytest.raises(SystemExit) as help_exit:r.main(['--help'])
    assert help_exit.value.code==0
    monkeypatch.setattr(r.sys,'platform','darwin');monkeypatch.setattr(r.os,'geteuid',lambda:501)
    with pytest.raises(SystemExit) as missing_sudo:r.main(['--execute'])
    assert missing_sudo.value.code==2
