"""本次会话的主机元数据解析；只有获批实机入口才调用 snapshot。"""
from collections import Counter
import plistlib
import subprocess
import time

def physical_port(location):
    """把本次Mac位置转换为libusb总线及端口链，不绑定历史插口。"""
    if type(location) is not int or not 0 < location <= 0xffffffff:
        raise ValueError('USB位置未知')
    ports = []
    ended = False
    for shift in (20, 16, 12, 8, 4):
        value = (location >> shift) & 15
        if value == 0:
            ended = True
        elif ended:
            raise ValueError('USB端口拓扑不连续')
        else:
            ports.append(value)
    if not ports or location & 15:
        raise ValueError('无法识别USB端口拓扑')
    return location >> 24, ports


def parse(tree):
    found = []
    def walk(node):
        if node.get('IOObjectClass') == 'IOUSBHostDevice' and node.get('idVendor') == 0x054c:
            found.append(node)
        for child in node.get('IORegistryEntryChildren', []):
            walk(child)
    for node in tree:
        walk(node)
    if not found:
        return {'kind': 'absent', 'present': False}
    if len(found) != 1:
        raise ValueError('不能唯一定位Sony设备')
    node = found[0]
    pid = node.get('idProduct')
    location = node.get('locationID')
    physical_port(location)
    if pid not in (0x0336, 0x096f, 0x0e0a):
        raise ValueError('未知USB身份，请在相机上选择MSC')
    result = dict(kind={0x0336: 'service', 0x096f: 'transition', 0x0e0a: 'ordinary'}[pid],
                  location_id=location, pid=pid, observed_product=node.get('USB Product Name'),
                  media=[], drivers=[])
    if pid != 0x0e0a:
        # 服务态名称只记录；仍需版本和本次nonce终态交叉绑定，不能据此直接STOP。
        return result
    if node.get('USB Product Name') != 'ILCE-7RM5':
        raise ValueError('普通身份型号不符')
    result['model'] = 'ILCE-7RM5'
    def collect(item):
        kind = item.get('IOObjectClass', '')
        if 'MassStorage' in kind:
            result['drivers'].append(kind)
        if 'BSD Name' in item:
            size = item.get('Size')
            if type(size) is not int or size <= 0:
                raise ValueError('媒体容量元数据异常')
            result['media'].append([bool(item.get('Whole')), size])
        for child in item.get('IORegistryEntryChildren', []):
            collect(child)
    collect(node)
    result['media'].sort()
    result['drivers'] = sorted(set(result['drivers']))
    return result


def snapshot(out, label, timeout=5):
    raw = subprocess.run(['/usr/sbin/ioreg', '-a', '-l', '-r', '-c', 'IOUSBHostDevice'],
                         capture_output=True, check=True, timeout=timeout).stdout
    # 先保存原始树；即使解析拒绝也留下真实产品名、PID和位置。
    (out / (label + '.plist')).write_bytes(raw)
    return parse(plistlib.loads(raw))


def observe(baseline, take, seconds=45, interval=2):
    if not 0 < seconds <= 45 or not 0 < interval <= seconds:
        raise ValueError('观察必须有界')
    media = Counter(tuple(row) for row in baseline['media'])
    drivers = set(baseline['drivers'])
    if not media or not drivers:
        raise ValueError('缺少本次完整基线')
    physical_port(baseline['location_id'])
    start = time.monotonic()
    proof = dict(recovered=False, observations=[], source='host_ioreg_only', camera_protocol_requests=0)
    stable = 0
    for number in range(32):
        left = seconds - (time.monotonic() - start)
        if left <= 0:
            break
        row = dict(number=number)
        try:
            value = take(f'host-{number:02}', timeout=min(5, left))
            row['snapshot'] = value
            if value.get('location_id') not in (None, baseline['location_id']):
                raise ValueError('本次会话USB端口变化')
            if value['kind'] == 'ordinary':
                now_media = Counter(tuple(item) for item in value['media'])
                now_drivers = set(value['drivers'])
                if now_media - media or now_drivers - drivers:
                    raise ValueError('出现基线以外的媒体或驱动')
                matched = now_media == media and now_drivers == drivers
                stable = stable + 1 if matched else 0
                row.update(status='matching' if matched else 'pending', consecutive=stable)
            else:
                stable = 0
                row['status'] = 'pending'
        except Exception as exc:
            row.update(status='rejected', error=type(exc).__name__ + ': ' + str(exc))
            proof['observations'].append(row)
            proof['reason'] = 'metadata_rejected'
            return proof
        proof['observations'].append(row)
        if stable >= 2 and time.monotonic() - start < seconds:
            proof.update(recovered=True, reason='two_stable_ordinary_matches')
            return proof
        left = seconds - (time.monotonic() - start)
        if left <= 0:
            break
        time.sleep(min(interval, left))
    proof['reason'] = 'host_observation_timeout'
    return proof
