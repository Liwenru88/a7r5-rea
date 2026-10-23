"""使用真实认证会话调度器，失败时不发STOP；成功只发一次。"""
from pathlib import Path
import hashlib
import sys
from types import SimpleNamespace,ModuleType
import pytest
from test_exec import Camera,operation,PROFILE,ROOT
sys.path[:0]=[str(ROOT/'vendor/engine/mac'),str(ROOT/'vendor/engine/libs')]
from system_dump import session
import usb.core,usb.util,usb.backend.libusb1


@pytest.mark.parametrize('engine',['libjit','kit'])
@pytest.mark.parametrize('fault',[None,'unknown-preload'])
def test_real_session_stop_depends_on_full_method_gate(tmp_path,monkeypatch,engine,fault):
    op=operation(tmp_path/'run',engine);op.config['version_sha256']=hashlib.sha256(b'fixed-version').hexdigest()
    out=tmp_path/'session';op.output=out
    camera=Camera(op,engine,fault);controls=[];stage=[0]
    class Interface(list):pass
    class Device:
        idVendor=0x054c;bus=0;port_numbers=[1];iProduct=1
        def __init__(self,pid):self.idProduct=pid
        def get_active_configuration(self):
            row=PROFILE['interfaces']['interface-1.json' if self.idProduct==0x0e0a else 'interface-2.json']
            interface=Interface([SimpleNamespace(bEndpointAddress=e['address'],bmAttributes=e['attributes'],
                                                 wMaxPacketSize=e['max_packet'],bInterval=e['interval']) for e in row['endpoints']])
            for attr,key in [('bInterfaceNumber','number'),('bAlternateSetting','alternate'),('bInterfaceClass','interface_class'),('bInterfaceSubClass','subclass'),('bInterfaceProtocol','protocol')]:setattr(interface,attr,row[key])
            return {(0,0):interface}
        def write(self,ep,data,timeout):assert ep==2;return camera.write(data)
        def read(self,ep,n,timeout):assert ep==129;return camera.read(n)
        def ctrl_transfer(self,*args,**kwargs):controls.append(args)
    normal=Device(0x0e0a);service=Device(0x0336)
    class Auth:
        def __init__(self,driver):self.driver=driver
        def start(self):self.driver.vendorRequestOut(*session.START)
        def authenticate(self):stage[0]+=1
    sony=ModuleType('pmca.usb.sony');sony.SonySenserAuthDevice=Auth
    monkeypatch.setitem(sys.modules,'pmca.usb.sony',sony)
    monkeypatch.setattr(usb.core,'find',lambda **k:[normal if stage[0]==0 else service])
    monkeypatch.setattr(usb.backend.libusb1,'get_backend',lambda **k:object())
    monkeypatch.setattr(usb.util,'get_string',lambda *a:'ILCE-7RM5')
    monkeypatch.setattr(usb.util,'dispose_resources',lambda *a:None)
    monkeypatch.setattr(usb.util,'release_interface',lambda *a:None)
    monkeypatch.setattr(session,'claim_interface',lambda *a:False)
    monkeypatch.setattr(session,'unmount_camera',lambda *a:None)
    report=session.run_session(out,'libusb',_operation=op)
    stops=[row for row in controls if row[1:4]==session.STOP]
    assert len(stops)==report['service_stop_attempts']==int(fault is None)
    assert len(controls)==2+int(fault is None)
    assert camera.triggers==int(fault is None) and op.safe_to_stop is (fault is None)
