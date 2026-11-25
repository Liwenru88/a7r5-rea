"""动态 USB 端口识别、模式检测（0e0a/0336/096f）、0336 自动恢复与普通模式观察。"""
from collections import Counter
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]
VENDOR_SITE = PROJECT / 'a7r5-desktop/prepared/engine/site'
FALLBACK_SITE = PROJECT / 'a7r5-exec/vendor/engine/libs'
FALLBACK_PMCA = PROJECT / 'a7r5-exec/vendor/engine/sources/workspaces/j/work/sony-pmca-re'
LIBUSB_CANDIDATES = (
    PROJECT / 'a7r5-desktop/prepared/engine/lib/libusb-1.0.dylib',
    Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib'),
    Path('/usr/local/opt/libusb/lib/libusb-1.0.dylib'),
)

VID = 0x054c
PID_ORDINARY = 0x0e0a
PID_SERVICE = 0x0336
PID_TRANSITION = 0x096f
MODEL = 'ILCE-7RM5'
STOP_REQUEST = (0x43, 1, 0xc800, 0x2855, b'')

SERVICE_INTERFACE = {
    'number': 0,
    'alternate': 0,
    'interface_class': 255,
    'subclass': 0,
    'protocol': 0,
    'endpoints': [
        {'address': n, 'attributes': 2, 'max_packet': 512, 'interval': 0}
        for n in (129, 2, 131, 4)
    ],
}


def ensure_usb_paths():
    """注入项目内 vendored PyUSB/Cryptodome 与 pmca_source 路径（优先使用 .venv 原生扩展，缺失时回退库内源码）。"""
    if VENDOR_SITE.is_dir() and str(VENDOR_SITE) not in sys.path:
        sys.path.insert(0, str(VENDOR_SITE))
    for path in (
        PROJECT / 'a7r5-desktop/prepared/engine/vendor/pmca_source',
        FALLBACK_PMCA,
        FALLBACK_SITE,
    ):
        text = str(path)
        if path.is_dir() and text not in sys.path:
            sys.path.append(text)


def find_libusb():
    """定位本机可用的 libusb-1.0.dylib。"""
    configured = os.environ.get('A7R5_LIBUSB')
    candidates = (Path(configured),) if configured else LIBUSB_CANDIDATES
    library = next((p for p in candidates if p.is_file()), None)
    if library is None:
        raise FileNotFoundError('未找到 libusb-1.0.dylib；可设置 A7R5_LIBUSB 环境变量指定路径')
    return library


def physical_port(location):
    """把 macOS locationID 转换为 libusb 的 (bus, ports) 元组，支持任意物理端口。"""
    if type(location) is not int or not 0 < location <= 0xffffffff:
        raise ValueError('USB 位置标识无效')
    ports = []
    ended = False
    for shift in (20, 16, 12, 8, 4):
        value = (location >> shift) & 15
        if value == 0:
            ended = True
        elif ended:
            raise ValueError('USB 端口拓扑不连续')
        else:
            ports.append(value)
    if not ports or location & 15:
        raise ValueError('无法识别 USB 端口拓扑')
    return location >> 24, ports


def interface_fingerprint(interface):
    """提取 USB 接口描述符指纹。"""
    return {
        'number': int(interface.bInterfaceNumber),
        'alternate': int(interface.bAlternateSetting),
        'interface_class': int(interface.bInterfaceClass),
        'subclass': int(interface.bInterfaceSubClass),
        'protocol': int(interface.bInterfaceProtocol),
        'endpoints': [
            {
                'address': int(e.bEndpointAddress),
                'attributes': int(e.bmAttributes),
                'max_packet': int(e.wMaxPacketSize),
                'interval': int(e.bInterval),
            }
            for e in interface
        ],
    }


def usb_devices(tree):
    """遍历主机注册表中的 USB 设备节点。"""
    for node in tree:
        if node.get('IOObjectClass') == 'IOUSBHostDevice':
            yield node
        yield from usb_devices(node.get('IORegistryEntryChildren', []))


def parse_ioreg(tree, location=None):
    """解析 ioreg IOUSBHostDevice 树，识别唯一的 Sony 相机及其模式与存储媒体。"""
    found = [node for node in usb_devices(tree) if node.get('idVendor') == VID]
    if not found:
        return {'kind': 'absent', 'present': False}
    if len(found) != 1:
        raise ValueError('检测到多台 Sony 设备，请只连接一台 A7R5 相机')

    node = found[0]
    observed = node.get('locationID')
    pid = node.get('idProduct')
    bus, ports = physical_port(observed)
    if pid not in (PID_ORDINARY, PID_SERVICE, PID_TRANSITION):
        raise ValueError(f'当前 USB 模式未适配 (pid=0x{pid:04x})，请在相机上选择 MSC')
    if location is not None and observed != location:
        raise ValueError('本次检查期间 USB 物理端口发生变化，请重新执行')

    kind = {PID_ORDINARY: 'ordinary', PID_SERVICE: 'service', PID_TRANSITION: 'transition'}[pid]
    result = {
        'kind': kind,
        'present': True,
        'location_id': observed,
        'bus': bus,
        'ports': ports,
        'pid': pid,
        'media': [],
        'drivers': [],
        'observed_product': node.get('USB Product Name'),
    }
    if pid != PID_ORDINARY:
        return result

    if node.get('USB Product Name') != MODEL:
        raise ValueError(f'仅支持 {MODEL}，当前识别到：{node.get("USB Product Name")}')
    result['model'] = MODEL

    def collect(item):
        cls = item.get('IOObjectClass', '')
        if 'MassStorage' in cls:
            result['drivers'].append(cls)
        if 'BSD Name' in item:
            size = item.get('Size')
            if type(size) is not int or size <= 0:
                raise ValueError('存储媒体容量元数据无效')
            result['media'].append([bool(item.get('Whole')), size])
        for child in item.get('IORegistryEntryChildren', []):
            collect(child)

    collect(node)
    result['media'].sort()
    result['drivers'] = sorted(set(result['drivers']))
    return result


def read_ioreg(timeout=5):
    """读取 macOS USB 注册表快照。"""
    return subprocess.run(
        ['/usr/sbin/ioreg', '-a', '-l', '-r', '-c', 'IOUSBHostDevice'],
        capture_output=True,
        check=True,
        timeout=timeout,
    ).stdout


def snapshot(out_dir=None, label=None, timeout=5, location=None):
    """抓取一次 macOS ioreg USB 快照并解析状态。"""
    raw = read_ioreg(timeout)
    if out_dir is not None and label is not None:
        (Path(out_dir) / f'{label}.plist').write_bytes(raw)
    if not raw.strip():
        return {'kind': 'absent', 'present': False}
    return parse_ioreg(plistlib.loads(raw), location)


def send_stop_once(location_id, report):
    """向指定物理端口上的 054c:0336 服务设备发送单次 STOP 控制请求。"""
    if report.get('stop_attempts', 0) != 0:
        raise PermissionError('STOP 已发送过，禁止重复发送')
    ensure_usb_paths()
    import usb.core
    import usb.util
    import usb.backend.libusb1

    libusb_path = find_libusb()
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: str(libusb_path))
    if backend is None:
        raise RuntimeError('libusb 后端加载失败')
    bus, ports = physical_port(location_id)
    devices = list(usb.core.find(find_all=True, idVendor=VID, backend=backend))
    try:
        if len(devices) != 1:
            raise ValueError('请只连接一台 Sony 相机，不发送 STOP')
        dev = devices[0]
        if (int(dev.idVendor), int(dev.idProduct), dev.bus, list(dev.port_numbers or ())) != (
            VID,
            PID_SERVICE,
            bus,
            ports,
        ):
            raise ValueError('设备身份或物理端口变化，拒绝发送 STOP')
        if interface_fingerprint(dev.get_active_configuration()[(0, 0)]) != SERVICE_INTERFACE:
            raise ValueError('不是已适配的 0336 服务接口，拒绝发送 STOP')
        report['stop_attempts'] = 1
        try:
            dev.ctrl_transfer(*STOP_REQUEST, timeout=5000)
            report['stop_result'] = 'returned'
        except Exception as exc:
            # 相机可能在返回前立即重启 USB，保留错误并交由主机观察确认。
            report['stop_result'] = 'error'
            report['stop_error'] = f'{type(exc).__name__}: {exc}'
    finally:
        for dev in devices:
            try:
                usb.util.dispose_resources(dev)
            except Exception as exc:
                report.setdefault('resource_release_errors', []).append(str(exc))


def observe_ordinary(
    location_id,
    take=None,
    *,
    baseline=None,
    seconds=45,
    interval=2,
    clock=time.monotonic,
    sleep=time.sleep,
):
    """观察同一物理端口是否稳定恢复为普通 MSC 模式（连续两次快照匹配）。"""
    if not 0 < seconds <= 60 or not 0 < interval <= seconds:
        raise ValueError('观察时间参数无效')
    take = take or (lambda label, timeout=5: snapshot(timeout=timeout, location=None))
    want_media = Counter(tuple(r) for r in baseline['media']) if baseline and baseline.get('media') else None
    want_drivers = set(baseline['drivers']) if baseline and baseline.get('drivers') else None
    start = clock()
    observations = []
    previous_sig = None
    stable = 0

    for idx in range(40):
        left = seconds - (clock() - start)
        if left <= 0:
            break
        cur = take(f'host-{idx:02d}', timeout=min(5, left))
        observations.append(cur)
        if cur.get('location_id') not in (None, location_id):
            raise ValueError('观察期间 USB 物理端口发生变化')
        if cur['kind'] not in ('ordinary', 'service', 'transition', 'absent'):
            raise ValueError(f'未知 USB 状态：{cur["kind"]}')

        if cur['kind'] == 'ordinary' and cur.get('model') == MODEL and cur.get('drivers'):
            now_media = Counter(tuple(r) for r in cur.get('media', []))
            now_drivers = set(cur.get('drivers', []))
            if want_media is not None and want_drivers is not None:
                if now_media - want_media or now_drivers - want_drivers:
                    raise ValueError('恢复后出现基线以外的媒体或驱动')
                matched = now_media == want_media and now_drivers == want_drivers
                stable = stable + 1 if matched else 0
            else:
                sig = (cur.get('model'), tuple(cur.get('drivers', [])), tuple(tuple(x) for x in cur.get('media', [])))
                stable = (stable + 1) if sig == previous_sig else 1
                previous_sig = sig
            if stable >= 2:
                return {
                    'recovered': True,
                    'observations': observations,
                    'final': cur,
                    'media_detected': bool(cur.get('media')),
                }
        else:
            stable = 0
            previous_sig = None

        left = seconds - (clock() - start)
        if left <= 0:
            break
        sleep(min(interval, left))

    return {
        'recovered': False,
        'observations': observations,
        'reason': f'{seconds} 秒内未确认稳定的普通 MSC 模式',
    }


def ensure_ordinary_mode(
    out_dir=None,
    *,
    take=None,
    stop_fn=send_stop_once,
    clock=time.monotonic,
    sleep=time.sleep,
    log_fn=None,
):
    """自动识别当前相机模式：若为 096f 则等待稳定；若为 0336 则自动 STOP 恢复为 0e0a 后返回基线。"""
    take = take or (lambda label, timeout=5: snapshot(out_dir, label, timeout=timeout))
    log = log_fn or (lambda *args, **kwargs: None)
    initial = take('precheck-0')
    if initial['kind'] == 'absent':
        raise RuntimeError('未检测到 Sony 相机，请连接 USB 并在相机上选择 MSC 模式')

    recovery_report = {'initial': initial, 'stop_attempts': 0, 'stop_result': 'not_needed'}
    current = initial

    if current['kind'] == 'transition':
        log('等待 USB 过渡态 (096f) 稳定...')
        deadline = clock() + 15
        while clock() < deadline and current['kind'] == 'transition':
            sleep(0.5)
            current = take('precheck-transition')
        if current['kind'] in ('absent', 'transition'):
            raise RuntimeError('相机停留在 USB 过渡态或断开连接，请检查相机屏幕提示')

    if current['kind'] == 'service':
        log(f'检测到相机当前处于服务通道模式 (054c:0336, location=0x{current["location_id"]:08x})，自动发送 STOP 恢复普通 MSC...')
        stop_fn(current['location_id'], recovery_report)
        proof = observe_ordinary(
            current['location_id'],
            take=take,
            seconds=45,
            interval=1.5,
            clock=clock,
            sleep=sleep,
        )
        recovery_report['host_recovery'] = proof
        if not proof['recovered']:
            raise RuntimeError('已发送 STOP，但相机未恢复到普通 MSC 模式：' + proof.get('reason', '未知原因'))
        current = proof['final']
        log('已自动从 0336 恢复为普通 MSC 模式 (054c:0e0a)')

    if current['kind'] != 'ordinary' or current.get('model') != MODEL or not current.get('drivers'):
        raise RuntimeError('未能确认 A7R5 普通 MSC 连接，请在相机上选择 MSC 模式')

    return current, recovery_report
