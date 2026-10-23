"""修复mmcb选卡后的固定一次性转存入口；prepare不观察设备，execute须另行批准。"""
from pathlib import Path
import argparse
import hashlib
import json
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEVICE = '/dev/mmcb2'
LOCATION = 0x01100000
SCHEMA = 'a7r5-mmcb-dump-approval-1'
RISK_FLAGS = ('camera_writes', 'debug_once', 'neutral_file_residue', 'card_dump_writes', 'failure_recovery_limits')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    from system_dump.restricted import save_json
    save_json(Path(path), value)


def validate_diagnostic(raw, run, receipt):
    from card_diag_once import parse_report
    value = parse_report(raw, {'run_id':run, 'card_uuid':receipt['ext2_uuid'],
                              'card_partition_bytes':receipt['partitions'][1]['bytes']})
    matches=[]
    for node in value['nodes']:
        calls={c['tag']:c for c in node['calls']}
        if (calls.get('read_sb',{}).get('superblock',{}).get('matches')
                and node['comparison']['all_four_sizes_available_and_equal']
                and node['comparison']['sysfs_dev_matches_proc']):
            matches.append('/dev/'+node['name'])
    if not value['complete'] or matches != [DEVICE]:
        raise ValueError('真实诊断未唯一确认指定mmcb2分区')
    return value


def prepare(output, views='plaintext'):
    from system_dump.bundle import prepare_bundle
    from system_dump.restricted import layout128
    output=Path(output).absolute()
    evidence=ROOT/'mac/system_dump/evidence/live-card-diag-20261018-01'
    receipt_path=ROOT/'mac/system_dump/evidence/card-format-20261018-01/card-ready.json'
    hashes=json.loads((evidence/'evidence-hashes.json').read_bytes())['files']
    for name in ('raw-session/run-card-diag/carddiag.bin','final-verification.json'):
        if sha(evidence/name)!=hashes[name]: raise ValueError('历史实机证据变化')
    final=json.loads((evidence/'final-verification.json').read_bytes())
    if not final['full_execution_checklist_complete'] or final['screen_report']!='normal':
        raise ValueError('上次诊断恢复核对不完整')
    receipt=json.loads(receipt_path.read_bytes())
    saved_receipt=ROOT/'mac/system_dump/evidence/card-diagnostic-implementation-20261018-01/candidate-v2/prepared-card-receipt.json'
    if sha(receipt_path)!=sha(saved_receipt): raise ValueError('卡收据与已执行诊断材料不一致')
    if not all(receipt[k] is True for k in ('card_prepared','full_ext2_readback_verified','mbr_verified')):
        raise ValueError('备用卡收据未通过')
    layout=layout128(receipt['capacity_bytes'])
    for actual,planned in zip(receipt['partitions'],layout['partitions'],strict=True):
        if (actual['bytes'],actual['start_lba'],actual['end_lba_inclusive']+1)!=(planned['bytes'],planned['start_lba'],planned['end_lba_exclusive']):
            raise ValueError('卡收据几何不符')
    raw=(evidence/'raw-session/run-card-diag/carddiag.bin').read_bytes()
    diagnostic=validate_diagnostic(raw, final['run_id'], receipt)
    value=prepare_bundle(output,receipt['capacity_bytes'],prepared_card=receipt,expected_card=DEVICE,views=views)
    (output/'prepared-card-receipt.json').write_bytes(receipt_path.read_bytes())
    (output/'diagnostic-input.bin').write_bytes(raw)
    value.update(profile='mmcb-fixed-neutral-views-2', expected_card_device=DEVICE, preload_policy='exact-neutral-512',
                 capacity_source='prepared_card_receipt_and_saved_live_diagnostic', card_geometry_verified=True,
                 diagnostic_run=diagnostic['run_id'], prepared_card_receipt_sha256=sha(receipt_path),
                 diagnostic_sha256=hashlib.sha256(raw).hexdigest())
    for source in (Path(__file__), ROOT/'mac/card_diag_once.py', ROOT/'mac/mmcb_dump_package.py'):
        value['sources'][str(source.relative_to(ROOT))]=sha(source)
    for name in ('prepared-card-receipt.json','diagnostic-input.bin'):
        value['artifacts'][name]=sha(output/name)
    value['pending']=['本次相机固定写入、一次DEBUG、指定卡转存和恢复受限风险的单独批准']
    save(output/'bundle.json',value)
    approval={'schema':SCHEMA,'bundle_sha256':sha(output/'bundle.json'),'run_id':value['run_id'],
              **{k:False for k in RISK_FLAGS},'unknown_preload_overwrite':False,'format_card':False,
              'expected_card_device':DEVICE,'dump_views':views,'card_verified_uuid':receipt['ext2_uuid'],
              'card_verified_partition_bytes':value['card_partition_bytes'],
              'card_verified_capacity_bytes':receipt['capacity_bytes']}
    save(output/'approval-template.json',approval)
    return value


def load(base):
    from system_dump.bundle import load_bundle, config
    base=Path(base);value,digest=load_bundle(base)
    from system_dump.core import validate_inventory
    expected = validate_inventory(value.get('expected_inventory'))
    if expected['views'] != value['dump_views']:
        raise ValueError('转存模式与封存盘点不符')
    if (value.get('profile')!='mmcb-fixed-neutral-views-2' or value.get('expected_card_device')!=DEVICE
            or value.get('preload_policy')!='exact-neutral-512'):
        raise ValueError('不是绑定mmcb2和精确中和基线的新材料')
    receipt=json.loads((base/'prepared-card-receipt.json').read_bytes())
    if (sha(base/'prepared-card-receipt.json')!=value['prepared_card_receipt_sha256']
            or sha(base/'diagnostic-input.bin')!=value['diagnostic_sha256']
            or receipt['ext2_uuid']!=value['card_uuid'] or receipt['card_marker']!=value['card_marker']
            or receipt['capacity_bytes']!=value['layout']['capacity_bytes']):
        raise ValueError('备用卡收据/诊断绑定不符')
    validate_diagnostic((base/'diagnostic-input.bin').read_bytes(),value['diagnostic_run'],receipt)
    header,prepare_script,dump_script=config(value['run_id'],value['card_uuid'],value['card_partition_bytes'],
                                            value['card_marker'],expected_card=DEVICE,views=value['dump_views'])
    if ((base/'config.h').read_text()!=header or (base/'prepare-task.sh').read_text()!=prepare_script
            or (base/'dump-task.sh').read_text()!=dump_script):
        raise ValueError('固定任务或卡路径不符')
    cleanup=next(json.loads(line.split(' ',2)[2]) for line in header.splitlines() if line.startswith('#define CLEANUP_SCRIPT '))
    if (base/'cleanup-task.sh').read_text()!=cleanup: raise ValueError('固定清理任务不符')
    prefix='/tmp/jiritsu/a7r5-'+value['run_id']
    fixed={'preload-arm.bin':(prefix+'.so\n').encode(),'preload-neutral.bin':b'\n'*512,
           'A7R5_CARD_ID':(value['card_marker']+'\n').encode(),
           'go-token.bin':f'A7R5_GO {value["run_id"]} {value["card_marker"]}\n'.encode(),
           'abort-token.bin':f'A7R5_ABORT {value["run_id"]} {value["card_marker"]}\n'.encode()}
    if any((base/name).read_bytes()!=data for name,data in fixed.items()): raise ValueError('固定协议材料不符')
    return value,digest


def approve(approval,value,digest):
    if (approval.get('schema')!=SCHEMA or approval.get('bundle_sha256')!=digest
            or approval.get('run_id')!=value['run_id'] or any(approval.get(k) is not True for k in RISK_FLAGS)
            or approval.get('unknown_preload_overwrite') is not False or approval.get('format_card') is not False
            or approval.get('expected_card_device')!=DEVICE
            or approval.get('dump_views')!=value['dump_views']
            or approval.get('card_verified_uuid')!=value['card_uuid']
            or approval.get('card_verified_partition_bytes')!=value['card_partition_bytes']
            or approval.get('card_verified_capacity_bytes')!=value['layout']['capacity_bytes']):
        raise PermissionError('缺少本次mmcb2固定转存批准；不允许未知预加载覆盖或格式化')


def strict_operation(value,payload):
    from system_dump.restricted import RestrictedChannel,DumpOperation,neutral
    class NeutralChannel(RestrictedChannel):
        baseline_checked=False
        def read(self,path,limit):
            data=super().read(path,limit)
            if path=='/etc/ld.so.preload' and not self.baseline_checked:
                if data!=neutral: raise PermissionError('只接受精确512换行基线，不覆盖未知/空文件/其他内容')
                self.baseline_checked=True
            return data
    return DumpOperation(value,payload,False,channel_factory=NeutralChannel)


def host_precheck(value,receipt):
    from system_dump.session import camera_media
    raw=subprocess.run(['/usr/sbin/ioreg','-a','-l','-r','-c','IOUSBHostDevice'],check=True,capture_output=True,timeout=15).stdout
    tree=plistlib.loads(raw)
    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node.get('IORegistryEntryChildren',[]))
    sony=[n for n in walk(tree) if n.get('IOObjectClass')=='IOUSBHostDevice' and n.get('idVendor')==0x054c]
    if len(sony)!=1 or sony[0].get('locationID')!=LOCATION or sony[0].get('idProduct')!=0x0e0a:
        raise ValueError('未唯一确认同端口普通Sony身份')
    media=camera_media(tree,LOCATION)
    expected=[(True,receipt['capacity_bytes']),(False,8589934592),(False,value['card_partition_bytes']),
              (True,67108864),(False,67108352)]
    if sorted((m['whole'],m['bytes']) for m in media)!=sorted(expected): raise ValueError('媒体几何不符')
    infos=[plistlib.loads(subprocess.run(['/usr/sbin/diskutil','info','-plist',m['device']],check=True,
                                        capture_output=True,timeout=15).stdout) for m in media]
    if len([i for i in infos if i.get('VolumeUUID')==receipt['exfat_volume_uuid']
            and i.get('FilesystemType')=='exfat' and i.get('PartitionMapPartitionOffset')==1048576])!=1:
        raise ValueError('指定卡exFAT UUID不符')


def execute(base,approval_path,output):
    from system_dump.images import regular_file
    from system_dump.session import run_session
    from system_dump.usb_adapter import LIBUSB
    base,output=Path(base),Path(output).absolute()
    value,digest=load(base)
    approve(json.loads(regular_file(approval_path).read_bytes()),value,digest)
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to('/dev'):
        raise ValueError('输出须为新的普通目录')
    runtime=json.loads((base/'external-runtime.json').read_bytes())
    if set(runtime)!={str(Path(sys.executable).resolve()),str(LIBUSB)}: raise ValueError('外部依赖清单不符')
    for name,item in runtime.items():
        if str(Path(name).resolve())!=item['resolved_path'] or sha(name)!=item['sha256']: raise ValueError('外部依赖变化')
    (base/'ATTEMPT_LOCK').mkdir(mode=0o700)
    host_precheck(value,json.loads((base/'prepared-card-receipt.json').read_bytes()))
    operation=strict_operation(value,(base/'a7r5_worker.arm64.so').read_bytes())
    class Bound:
        @property
        def safe_to_stop(self):return operation.safe_to_stop
        def __call__(self,driver,*args):
            ports=tuple(driver.device.port_numbers or ())
            location=(driver.device.bus<<24)|sum(p<<(20-4*i) for i,p in enumerate(ports))
            if not ports or location!=LOCATION: raise ValueError('部署前端口变化')
            return operation(driver,*args)
    return run_session(output,'libusb',_operation=Bound())


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action')
    p=sub.add_parser('prepare');p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('execute');p.add_argument('--bundle',type=Path,required=True);p.add_argument('--approval',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.action is None:parser.print_help();return 0
    result=prepare(args.output) if args.action=='prepare' else execute(args.bundle,args.approval,args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if args.action=='prepare' or result.get('card_unmounted_verified') and result.get('ordinary_identity_restored') and 'failure' not in result else 1


if __name__=='__main__':raise SystemExit(main())
