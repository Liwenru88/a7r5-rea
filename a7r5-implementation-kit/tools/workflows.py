"""复用成功版本构建转存操作，并将新会话证据绑定到精简取回任务。"""
import hashlib
import json
from pathlib import Path

from .common import BASE, fresh, load, regular, save, seal, sha
from .profiles import VIEWS, inventory as profile_inventory, project


def prepare_dump(destination, profile='standard'):
    from mmcb_dump_once import prepare
    from system_dump.restricted import save_json
    expected = profile_inventory(profile)
    directory = fresh(destination)
    bundle = prepare(directory / 'bundle', views=VIEWS[profile])
    bundle['dump_profile'] = profile
    bundle['expected_inventory'] = expected
    save_json(directory / 'bundle/bundle.json', bundle)
    template = json.loads((directory / 'bundle/approval-template.json').read_bytes())
    template['bundle_sha256'] = sha(directory / 'bundle/bundle.json')
    save_json(directory / 'bundle/approval-template.json', template)
    save(directory / 'bundle/external-runtime.json', {
        name: {'resolved_path': str(Path(name).resolve()), 'sha256': sha(Path(name).resolve())}
        for name in (str(Path(__import__('sys').executable).resolve()), '/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib')})
    return seal(directory, {'kind': 'dump', 'run_id': bundle['run_id'], 'dump_profile': profile,
        'image_count': len(expected['partitions']), 'image_bytes': expected['total_bytes'],
        'risk_statement': f'写相机固定载荷及预加载，认证/START和一次DEBUG；本次{profile}模式{len(expected["partitions"])}项，盘点通过自动GO，仅写已绑定mmcb2；不格式化，不覆盖未知预加载；中和不等于还原，异常可能需另行恢复。'})


def run_dump(directory, operation):
    from mmcb_dump_once import execute, load as load_bundle, RISK_FLAGS, SCHEMA, DEVICE
    bundle, digest = load_bundle(directory / 'bundle')
    if (bundle['run_id'] != operation['run_id'] or bundle['dump_profile'] != operation['dump_profile']
            or project(bundle['expected_inventory']) != project(profile_inventory(operation['dump_profile']))):
        raise ValueError('转存会话不符')
    approval = {'schema': SCHEMA, 'bundle_sha256': digest, 'run_id': bundle['run_id'],
        **{key: True for key in RISK_FLAGS}, 'unknown_preload_overwrite': False, 'format_card': False,
        'expected_card_device': DEVICE, 'card_verified_uuid': bundle['card_uuid'],
        'dump_views': bundle['dump_views'],
        'card_verified_partition_bytes': bundle['card_partition_bytes'],
        'card_verified_capacity_bytes': bundle['layout']['capacity_bytes']}
    # 仅在外层逐次批准及尝试锁通过后生成引擎专用批准。
    save(directory / 'engine-approval.json', approval)
    report = execute(directory / 'bundle', directory / 'engine-approval.json', directory / 'result')
    report['execution_succeeded'] = bool(report.get('worker_done_receipt')
        and report.get('card_unmounted_verified') and report.get('preload_neutral_verified')
        and report.get('ordinary_identity_restored') and not report.get('failure'))
    save(directory / 'result/kit-result.json', report)
    return report


def binding_from_dump(directory):
    operation = load(directory)
    if operation['kind'] != 'dump':
        raise ValueError('须使用本包新转存操作，不能把历史旧会话当作新任务')
    output = Path(operation['output'])
    report = json.loads(regular(output / 'summary.json').read_bytes())
    if not all(report.get(k) is True for k in
               ('worker_done_receipt', 'card_unmounted_verified', 'preload_neutral_verified')):
        raise ValueError('没有本次DONE、卸载及中和证据；不得自动取卡')
    confirmation = json.loads(regular(output / 'host-confirmation.json').read_bytes())
    if (confirmation.get('run_id') != operation['run_id'] or confirmation.get('normal_usb_and_media') is not True
            or confirmation.get('screen_report') != 'normal'):
        raise ValueError('缺少本次普通USB、媒体及人工屏幕确认')
    from system_dump.core import validate_inventory
    from system_dump.tasks import inventory2
    expected = validate_inventory(json.loads(regular(output / 'inventory-expected.json').read_bytes()))
    # 盘点从独立主机会话取得，不从待读取SD卡中的inventory决定允许文件集合。
    parts = inventory2(regular(output / 'parts.txt').read_text(), views=VIEWS[operation['dump_profile']])
    if project(expected) != project(parts) or project(expected) != project(profile_inventory(operation['dump_profile'])):
        raise ValueError('新会话盘点与封存模式范围不符，须审查后另行适配')
    source_lines = ''.join(f"{p['device']} {p['major']} {p['minor']} {p['bytes']}\n" for p in expected['partitions'])
    if regular(output / 'sources.txt').read_text() != source_lines:
        raise ValueError('设备实际选源清单与本次模式不符')
    names = ('parts', 'mounts', 'devices', 'topology', 'sources')
    receipt = json.loads((BASE / 'profiles/prepared-card.json').read_bytes())
    return {'run_id': operation['run_id'], 'inventory': expected, 'dump_profile': operation['dump_profile'],
        'expected_complete': f"A7R5-DUMP-1 {operation['run_id']} {len(expected['partitions'])} {expected['total_bytes']}\n",
        'capacity_bytes': receipt['capacity_bytes'], 'sector_bytes': 512,
        'partition_bytes': receipt['partitions'][1]['bytes'],
        'partition_offset': receipt['partitions'][1]['start_lba'] * 512,
        'card_uuid': receipt['ext2_uuid'], 'card_marker': receipt['card_marker'] + '\n',
        'card_identity': receipt['card_identity'], 'mbr_entries': receipt['partitions'],
        'exfat_uuid': receipt['exfat_volume_uuid'],
        'metadata_sha256': {name: sha(output / (name + '.txt')) for name in names}}


def prepare_collect(dump_directory, destination, safety):
    if safety != 'CAMERA-OFF-CARD-LOCKED-MEDIA-EJECTED':
        raise PermissionError('须先完成相机退出、媒体正常弹出、断USB、正常关机、取卡置LOCK；不能由本入口代办')
    expected = binding_from_dump(dump_directory)
    directory = fresh(destination)
    save(directory / 'binding.json', expected)
    return seal(directory, {'kind': 'collect', 'run_id': expected['run_id'],
        'dump_profile': expected['dump_profile'], 'image_count': len(expected['inventory']['partitions']),
        'image_bytes': expected['inventory']['total_bytes'],
        'reader_tree_path': __import__('capture_current_dump').READER,
        'risk_statement': f'只读核对指定卡身份、系统写保护、布局和超级块，仅提取本次{expected["dump_profile"]}模式{len(expected["inventory"]["partitions"])}项及元数据；正常卸载与弹出；不复制整卡分区、不修复、不格式化。系统只读状态不等于已证明硬件写阻断。'})


def confirm_recovery(directory, screen_normal):
    from .root import normal, snapshot
    operation = load(directory)
    if operation['kind'] not in ('dump', 'root') or not screen_normal:
        raise ValueError('须先人工看到正常屏幕；本命令只观察主机元数据一次')
    output = Path(operation['output'])
    report = json.loads(regular(output / 'summary.json').read_bytes())
    needed = ('worker_done_receipt', 'card_unmounted_verified', 'preload_neutral_verified') if operation['kind'] == 'dump' else ('root_task_done', 'preload_neutral_verified')
    if not all(report.get(k) is True for k in needed):
        raise ValueError('没有本次任务完成及中和门槛；不能用主机观察替代')
    after = normal(snapshot())
    if operation['kind'] == 'dump':
        receipt = json.loads((BASE / 'profiles/prepared-card.json').read_bytes())
        expected = sorted([(True, receipt['capacity_bytes']), (False, receipt['partitions'][0]['bytes']),
                           (False, receipt['partitions'][1]['bytes']), (True, 67108864), (False, 67108352)])
        if sorted((m['whole'], m['bytes']) for m in after['media']) != expected:
            raise ValueError('指定卡及PMHOME媒体集合未恢复')
    else:
        prior = json.loads(regular(output / 'host-recovery.json').read_bytes())
        if prior.get('media_matches') is not True:
            raise ValueError('root会话的前后媒体核对未通过，须单独排查')
    value = {'run_id': operation['run_id'], 'normal_usb_and_media': True, 'screen_report': 'normal',
             'host_metadata_only': True, 'camera_protocol_requests_sent': False, 'observed': after}
    save(output / 'host-confirmation.json', value)
    return value
