"""恢复观察只接收主机元数据；不导入 USB 后端，不发送设备请求。"""
from collections import Counter
import time


class RecoveryPending(ValueError):
    def __init__(self, message, snapshot):
        super().__init__(message)
        self.snapshot = snapshot


def parse_host_tree(tree):
    found = []
    def walk(node):
        if node.get('IOObjectClass') == 'IOUSBHostDevice' and node.get('idVendor') == 0x054c:
            found.append(node)
        for child in node.get('IORegistryEntryChildren', []):
            walk(child)
    for node in tree:
        walk(node)
    if not found:
        raise RecoveryPending('主机尚未列出Sony设备', dict(present=False))
    if len(found) != 1:
        raise ValueError('不能唯一定位Sony设备')
    node = found[0]
    snapshot = dict(location_id=node.get('locationID'), model=node.get('USB Product Name'),
                    pid=node.get('idProduct'), media=[], drivers=[])
    if (snapshot['location_id'], snapshot['model']) != (0x01100000, 'ILCE-7RM5'):
        raise ValueError('型号或物理端口不符')
    if snapshot['pid'] not in (0x0e0a, 0x0336, 0x096f):
        raise ValueError('未知USB身份；不继续观察')
    if snapshot['pid'] != 0x0e0a:
        raise RecoveryPending('仍为已知服务或过渡身份', snapshot)
    def collect(item):
        kind = item.get('IOObjectClass', '')
        if 'MassStorage' in kind:
            snapshot['drivers'].append(kind)
        if 'BSD Name' in item:
            size = item.get('Size')
            if type(size) is not int or size <= 0:
                raise ValueError('媒体容量元数据异常')
            snapshot['media'].append((bool(item.get('Whole')), size))
        for child in item.get('IORegistryEntryChildren', []):
            collect(child)
    collect(node)
    snapshot['media'].sort()
    snapshot['drivers'] = sorted(set(snapshot['drivers']))
    if not snapshot['drivers'] or not any(whole for whole, size in snapshot['media']):
        raise RecoveryPending('普通驱动或媒体未恢复', snapshot)
    return snapshot


def observe_recovery(before, snapshot, *, seconds=45, interval=2):
    """连续两次完整匹配才通过；只等待已知过渡，不重试任何相机操作。"""
    if not 0 < seconds <= 45 or not 0 < interval <= seconds:
        raise ValueError('恢复观察必须有界')
    expected_media = Counter(tuple(entry) for entry in before['media'])
    expected_drivers = set(before['drivers'])
    if not expected_media or not expected_drivers:
        raise ValueError('缺少会话前媒体或驱动基线')
    start = time.monotonic()
    result = dict(before=before, after=None, observations=[], recovered=False,
                  media_matches=False, drivers_match=False, stable_matches_required=2,
                  deadline_seconds=seconds, source='host_ioreg_only', camera_requests_sent=0)
    stable = 0
    # 查询也使用剩余预算；额外次数上限防止测试时钟或异常时钟导致无限循环。
    for _ in range(64):
        elapsed = time.monotonic() - start
        if elapsed >= seconds:
            break
        record = dict(elapsed_seconds=round(elapsed, 3))
        result.update(after=None,media_matches=False,drivers_match=False)
        try:
            after = snapshot(timeout=min(5, seconds-elapsed))
        except RecoveryPending as exc:
            stable = 0
            record.update(status='pending', error=type(exc).__name__+': '+str(exc), snapshot=exc.snapshot)
            result['after']=exc.snapshot
            changed_identity=any(key in exc.snapshot and exc.snapshot[key]!=before[key]
                                 for key in ('location_id','model'))
            extra_media=Counter(tuple(entry) for entry in exc.snapshot.get('media',[]))-expected_media
            extra_drivers=set(exc.snapshot.get('drivers',[]))-expected_drivers
            if changed_identity or extra_media or extra_drivers:
                record.update(status='rejected',error='过渡子树含有不匹配的身份、媒体或驱动')
                result['observations'].append(record)
                result['reason']='identity_or_media_changed'
                return result
        except Exception as exc:
            record.update(status='rejected', error=type(exc).__name__+': '+str(exc))
            result['observations'].append(record)
            result['reason'] = 'host_metadata_rejected'
            return result
        else:
            record['snapshot'] = after
            result['after'] = after
            if any(after.get(key) != before.get(key) for key in ('location_id', 'model', 'pid')):
                record.update(status='rejected', error='相机会话身份变化')
            else:
                media = Counter(tuple(entry) for entry in after['media'])
                drivers = set(after['drivers'])
                result['media_matches'] = media == expected_media
                result['drivers_match'] = drivers == expected_drivers
                if media - expected_media or drivers - expected_drivers:
                    record.update(status='rejected', error='出现会话前不存在的媒体或驱动')
                elif result['media_matches'] and result['drivers_match']:
                    stable += 1
                    record.update(status='matching', consecutive_matches=stable)
                else:
                    stable = 0
                    record.update(status='pending', error='主机媒体或驱动子树尚未完整')
            if record['status'] == 'rejected':
                result['observations'].append(record)
                result['reason'] = 'identity_or_media_changed'
                return result
        result['observations'].append(record)
        if stable >= 2 and time.monotonic() - start < seconds:
            result.update(recovered=True, reason='stable_host_recovery')
            return result
        remaining = seconds - (time.monotonic()-start)
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    result['reason'] = 'host_recovery_timeout'
    return result
