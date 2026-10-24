#!/usr/bin/env python3
"""Mac端退出A7R5服务模式：自动识别当前端口，最多一次STOP。"""
import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('a7r5_recovery_host',ROOT/'a7r5-exec/runtime/host_state.py')
host=importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
STOP=(0x43,1,0xc800,0x2855,b'')
SERVICE_INTERFACE=dict(number=0,alternate=0,interface_class=255,subclass=0,protocol=0,
    endpoints=[dict(address=n,attributes=2,max_packet=512,interval=0) for n in (129,2,131,4)])


def stop_once(device,report):
    if report['stop_attempts']!=0:raise PermissionError('STOP已发送，禁止重试')
    report['stop_attempts']=1
    try:
        device.ctrl_transfer(*STOP,timeout=5000)
        report['stop_result']='returned'
    except Exception as exc:
        # 设备可能在响应前重新枚举；保留错误，随后仅观察主机，不补发请求。
        report.update(stop_result='error',stop_error=type(exc).__name__+': '+str(exc))


def interface_fingerprint(interface):
    return dict(number=int(interface.bInterfaceNumber),alternate=int(interface.bAlternateSetting),
        interface_class=int(interface.bInterfaceClass),subclass=int(interface.bInterfaceSubClass),
        protocol=int(interface.bInterfaceProtocol),endpoints=[dict(address=int(e.bEndpointAddress),
        attributes=int(e.bmAttributes),max_packet=int(e.wMaxPacketSize),interval=int(e.bInterval)) for e in interface])


def select_service(devices,location):
    bus,ports=host.physical_port(location)
    if len(devices)!=1:raise ValueError('请只连接一台Sony相机，不发送STOP')
    device=devices[0]
    if (int(device.idVendor),int(device.idProduct),device.bus,list(device.port_numbers or ()))!=(0x054c,0x0336,bus,ports):
        raise ValueError('设备身份或本次端口变化，不发送STOP')
    if interface_fingerprint(device.get_active_configuration()[(0,0)])!=SERVICE_INTERFACE:
        raise ValueError('不是已适配的服务接口，不发送STOP')
    return device


def send_stop(initial,report):
    # 仅在明确执行且当前为0336时加载USB后端；不接管接口、不分离驱动。
    vendor=ROOT/'a7r5-exec/vendor/engine/libs'
    if vendor.is_dir():sys.path.insert(0,str(vendor))
    import usb.core
    import usb.util
    import usb.backend.libusb1
    configured=os.environ.get('A7R5_LIBUSB')
    candidates=[Path(configured)] if configured else [Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib'),Path('/usr/local/opt/libusb/lib/libusb-1.0.dylib')]
    library=next((p for p in candidates if p.is_file()),None)
    if library is None:raise FileNotFoundError('未找到libusb；可设置A7R5_LIBUSB指向本机dylib')
    backend=usb.backend.libusb1.get_backend(find_library=lambda _:str(library))
    if backend is None:raise RuntimeError('libusb后端不可用')
    devices=list(usb.core.find(find_all=True,idVendor=0x054c,backend=backend))
    try:
        device=select_service(devices,initial['location_id'])
        stop_once(device,report)
    finally:
        for device in devices:
            try:usb.util.dispose_resources(device)
            except Exception as exc:report.setdefault('resource_release_errors',[]).append(str(exc))


def observe(location,take,*,seconds=45,clock=time.monotonic,sleep=time.sleep):
    start=clock();observations=[];previous=None
    while clock()-start<seconds:
        left=seconds-(clock()-start)
        current=take('host-'+str(len(observations)),timeout=min(5,left))
        observations.append(current)
        if current.get('location_id') not in (None,location):raise ValueError('观察期间端口变化，立即停止')
        if current['kind'] not in ('ordinary','service','transition','absent'):raise ValueError('未知USB状态')
        ready=(current['kind']=='ordinary' and current.get('model')=='ILCE-7RM5' and bool(current.get('drivers')))
        signature=(current.get('model'),tuple(current.get('drivers',[])),tuple(tuple(x) for x in current.get('media',[]))) if ready else None
        if signature is not None and signature==previous:
            return dict(recovered=True,observations=observations,verification='two_stable_MSC_matches',
                media_detected=bool(current.get('media')),historical_media_baseline_checked=False)
        previous=signature
        sleep(min(2,max(0,seconds-(clock()-start))))
    return dict(recovered=False,observations=observations,reason='45秒内未确认稳定普通USB')


def recover(initial,take,stop,report,*,clock=time.monotonic,sleep=time.sleep):
    if initial['kind'] not in ('ordinary','service','transition'):raise ValueError('未连接支持的相机，不发送请求')
    location=initial['location_id']
    if initial['kind']=='service':stop(initial,report)
    # 0e0a与096f只观察；STOP成功或报错后均不再发送相机协议请求。
    proof=observe(location,take,clock=clock,sleep=sleep)
    report.update(host_recovery=proof,ordinary_usb_restored=proof['recovered'])
    if not proof['recovered']:raise RuntimeError(proof['reason'])


@contextmanager
def device_locks():
    with ExitStack() as stack:
        for path,owners in [(Path('/private/tmp/local.a7r5.studio.device.lock'),{0}),
                            (ROOT/'a7r5-exec/ACTIVE_SESSION.lock',{0,ROOT.stat().st_uid})]:
            fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
            stack.callback(os.close,fd)
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid not in owners:
                raise PermissionError('设备互斥锁身份异常：'+str(path))
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise PermissionError('已有设备任务运行，请等待结束后恢复') from None
        yield


def main(argv=None):
    parser=argparse.ArgumentParser(description='恢复A7R5普通USB。执行会退出服务模式，可能中断进行中的任务；请先结束传输。')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--execute',action='store_true',help='允许当前0336设备接收一次STOP；不认证、不上传、不触发libJit')
    group.add_argument('--check',action='store_true',help='只观察主机USB状态，不发送STOP（默认）')
    args=parser.parse_args(argv)
    if sys.platform!='darwin':parser.error('仅支持macOS')
    if args.execute and os.geteuid()!=0:parser.error('执行恢复需要sudo；也可双击restore-usb.command')
    base=ROOT/'.local'
    if base.is_symlink():raise ValueError('日志父目录不能是符号链接')
    base.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=base/('usb-recovery-'+stamp+'-'+uuid.uuid4().hex[:8]);out.mkdir(mode=0o700)
    report=dict(mode='execute' if args.execute else 'check',stop_attempts=0,stop_result='not_attempted',
        ordinary_usb_restored=False,automatic_retry=False,authentication_requests=0,
        file_operations=0,payload_triggers=0,logs=str(out))
    def take(label,timeout=5):return host.snapshot(out,label,timeout)
    try:
        if args.execute:
            with device_locks():
                initial=take('initial');report['initial']=initial
                recover(initial,take,send_stop,report)
        else:report['initial']=take('initial')
    except Exception as exc:report['failure']=type(exc).__name__+': '+str(exc)
    finally:
        with (out/'result.json').open('x') as handle:json.dump(report,handle,ensure_ascii=False,indent=2)
        if os.geteuid()==0:
            owner=ROOT.stat()
            for path in [out,*out.iterdir()]:os.chown(path,owner.st_uid,owner.st_gid,follow_symlinks=False)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if 'failure' in report:return 3
    if not args.execute:return 0
    print('普通USB已稳定恢复。'+(' STOP返回错误，详情已保留；未重试。' if report['stop_result']=='error' else ''))
    if not report['host_recovery'].get('media_detected'):print('当前未检测到存储媒体；本结果只确认USB身份和驱动恢复。')
    return 0

if __name__=='__main__':raise SystemExit(main())
