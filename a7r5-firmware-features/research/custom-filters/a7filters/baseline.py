"""严格绑定现有修改包的只读入口，不重套原厂补丁、不读私钥。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile

HOME = Path(__file__).resolve().parents[1]
PROJECT = HOME.parents[1]
DAT_IDENTITY = {
    'bytes': 754525608,
    'sha256': '3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2',
}


def regular_path(value):
    path = Path(value).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('拒绝符号链接路径')
    path = Path(os.path.normpath(path))
    if any(path == p or path.is_relative_to(p) for p in map(Path, ('/dev', '/Volumes', '/proc', '/sys'))):
        raise ValueError('拒绝设备、系统或真实介质路径')
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('只允许普通文件')
    return path


def file_sha(path):
    with regular_path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_file(path, expected):
    path = regular_path(path)
    if path.stat().st_size != expected['bytes']:
        raise ValueError('输入文件长度与基线不符')
    digest = file_sha(path)
    if digest != expected['sha256']:
        raise ValueError('输入文件摘要与基线不符')
    return {'path': str(path), 'bytes': expected['bytes'], 'sha256': digest}


def check_component(name, raw, expected):
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != expected['bytes'] or digest != expected['sha256']:
        raise ValueError(f'{name} 组件长度或摘要不符')
    return {'bytes': len(raw), 'sha256': digest}


def output_path(value):
    path = Path(value).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('拒绝输出符号链接')
    path = Path(os.path.normpath(path))
    if any(path == p or path.is_relative_to(p) for p in map(Path, ('/dev', '/Volumes', '/proc', '/sys'))):
        raise ValueError('拒绝输出到设备或真实介质')
    if path.exists() or not path.parent.is_dir():
        raise ValueError('输出已存在或父目录缺失')
    return path


def write_report(path, report):
    with output_path(path).open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def load_lock():
    lock = json.loads((HOME/'baseline.json').read_text())
    if lock.get('schema') != 'a7r5-fixed-filter-baseline/1' or lock['dat'] != DAT_IDENTITY:
        raise ValueError('基线清单身份变化，禁止放宽前像门槛')
    return lock


def audit(path, *, investigate=False, investigate_ui=False, ui_adapter=None, ap_ui_module=None,
          cp_parameter_adapter=None, cp_atomic_adapter=None, ap_handshake_module=None, cp_handshake_module=None,
          ap_runtime_module=None, cp_runtime_module=None, grid_adapter=None, joint_adapter=None):
    """明文仅存匿名临时文件；组件只读入内存，不解包到设备或工作目录。"""
    if ui_adapter is not None and not investigate_ui:
        raise ValueError('目标适配器验证必须同时启用界面研究')
    if cp_parameter_adapter is not None and not (investigate or investigate_ui):
        raise ValueError('CP参数适配器验证必须同时启用接入研究')
    if cp_atomic_adapter is not None and not (investigate or investigate_ui):
        raise ValueError('CP原子适配器验证必须同时启用接入研究')
    grid_raw=None
    if grid_adapter is not None:
        if not (investigate or investigate_ui):raise ValueError('网格转换适配器验证必须同时启用接入研究')
        grid_path=regular_path(grid_adapter)
        if grid_path.stat().st_size>0x20000:raise ValueError('网格模块超过离线文件预算')
        grid_raw=grid_path.read_bytes()
    joint_raw=None
    if joint_adapter is not None:
        if not (investigate or investigate_ui):raise ValueError('联合转换适配器验证必须同时启用接入研究')
        joint_path=regular_path(joint_adapter)
        if joint_path.stat().st_size>0x20000:raise ValueError('联合模块超过离线文件预算')
        joint_raw=joint_path.read_bytes()
    if (ap_handshake_module is None)!=(cp_handshake_module is None):
        raise ValueError('AP/CP握手模块必须成对提供')
    if (ap_runtime_module is None)!=(cp_runtime_module is None):
        raise ValueError('AP/CP运行时模块必须成对提供')
    runtime_raw=None
    if ap_runtime_module is not None:
        if not investigate_ui:raise ValueError('运行时模块必须同时启用界面研究以核对同包时间符号')
        runtime_raw=[]
        for module in (ap_runtime_module,cp_runtime_module):
            candidate=regular_path(module)
            if candidate.stat().st_size>0x20000:raise ValueError('运行时模块超过离线文件预算')
            runtime_raw.append(candidate.read_bytes())
    handshake_raw=None
    if ap_handshake_module is not None:
        if not (investigate or investigate_ui):raise ValueError('握手模块必须同时启用接入研究')
        handshake_raw=[]
        for module in (ap_handshake_module,cp_handshake_module):
            candidate=regular_path(module)
            if candidate.stat().st_size>0x20000:raise ValueError('握手模块超过离线文件预算')
            handshake_raw.append(candidate.read_bytes())
    atomic_raw = None
    if cp_atomic_adapter is not None:
        atomic_path = regular_path(cp_atomic_adapter)
        if atomic_path.stat().st_size > 0x20000:
            raise ValueError('CP原子适配器超过离线文件预算')
        atomic_raw = atomic_path.read_bytes()
    cp_adapter_raw = None
    if cp_parameter_adapter is not None:
        cp_adapter_path = regular_path(cp_parameter_adapter)
        if cp_adapter_path.stat().st_size > 0x20000:
            raise ValueError('CP参数适配器超过离线文件预算')
        cp_adapter_raw = cp_adapter_path.read_bytes()
    adapter_raw = None
    module_raw = None
    if ap_ui_module is not None:
        if not investigate_ui:raise ValueError('AP挂钩验证必须同时启用界面研究')
        module_path=regular_path(ap_ui_module)
        if module_path.stat().st_size>1024*1024:raise ValueError('AP挂钩模块超过离线预算')
        module_raw=module_path.read_bytes()
    if ui_adapter is not None:
        adapter_path = regular_path(ui_adapter)
        if adapter_path.stat().st_size > 1024*1024:
            raise ValueError('目标适配器超过离线文件预算')
        adapter_raw = adapter_path.read_bytes()
    investigate = investigate or investigate_ui
    lock = load_lock()
    source = check_file(path, DAT_IDENTITY)
    sys.path.insert(0, str(PROJECT/'a7r5-dat-tool'))
    from a7r5dat import codec
    from a7r5dat.ext2_patch import reader
    from a7r5dat.fat import FatImage
    from a7r5dat.tool import read_archive, checksum_updates

    public = PROJECT/'a7r5-dat-tool/keys/research-public.pem'
    if file_sha(public) != lock['public_key_sha256']:
        raise ValueError('研究公钥身份不符')
    layout, _, _ = codec.verify_signature(source['path'], public.read_bytes())
    expected = {r['path']: r for r in lock['target_files']}
    checked = {}
    binaries = {}
    name_resources = {}
    with tempfile.TemporaryFile() as clear:
        frames = codec.decrypt_to(source['path'], clear)
        if frames['plaintext_bytes'] != lock['plaintext_bytes']:
            raise ValueError('明文长度不符')
        _, updater, info, entries, _ = read_archive(clear, frames['plaintext_bytes'])
        if (info['major'], info['minor'], len(entries)) != (4, 6, lock['tar_entries']):
            raise ValueError('版本或归档条目不符')
        if hashlib.sha256(updater).hexdigest() != lock['updater_sha256']:
            raise ValueError('继承的更新器主体变化')
        originals = {r['name']: r for r in entries if r['type'] == '0'}
        current = {k: dict(bytes=v['size'], crc32=v['crc32']) for k, v in originals.items()}
        with tarfile.open(fileobj=codec.Part(clear, info['tar_offset'], info['tar_bytes']), mode='r:') as archive:
            ap_image = archive.extractfile('0700_part_image/dev/nflasha15').read()
            fs = reader(ap_image)
            for name, target in expected.items():
                if not name.startswith('components/usr/'):
                    continue
                inner = name.removeprefix('components/usr')
                raw = fs.read_inode(fs.walk(inner))
                checked[name] = check_component(name, raw, target)
                if inner == '/lib/appFw.so':
                    binaries['ap'] = raw
                if investigate_ui and inner.endswith('.uxc'):
                    name_resources[name] = raw
            if investigate:
                from .access_evidence import BACKUP_SHA, MANAGER_SHA
                from .ap_cp_messages import IPC_PATH,IPC_BYTES,IPC_SHA
                for library,key,size,digest in (('libbackup.so','backup',14232,BACKUP_SHA),
                                                ('libBackupManager.so','manager',10272,MANAGER_SHA),
                                                (IPC_PATH.removeprefix('/lib/'),'ipc',IPC_BYTES,IPC_SHA)):
                    raw = fs.read_inode(fs.walk('/lib/'+library))
                    check_component(library,raw,dict(bytes=size,sha256=digest))
                    binaries[key] = raw
                # 只查本包匿名内存镜像，不查询或创建主机/机身挂载点。
                try:
                    fs.walk('/data/lut')
                    lut_directory_present = True
                except KeyError:
                    lut_directory_present = False
            if investigate_ui:
                from .ui_evidence import STD_PATH, STD_SHA
                inode = fs.walk(STD_PATH)
                if not stat.S_ISREG(fs.inode(inode)[0]):
                    raise ValueError('同包C++库必须是已知普通文件')
                raw = fs.read_inode(inode)
                check_component('libstdc++',raw,dict(bytes=1549496,sha256=STD_SHA))
                binaries['std'] = raw
                from .ui_resource_lookup import OBJ_PATH, OBJ_BYTES, OBJ_SHA
                inode=fs.walk(OBJ_PATH)
                if not stat.S_ISREG(fs.inode(inode)[0]):
                    raise ValueError('同包资源库必须是普通文件')
                raw=fs.read_inode(inode)
                check_component('libObj',raw,dict(bytes=OBJ_BYTES,sha256=OBJ_SHA))
                binaries['obj']=raw
                from .ui_resource_loader import XDB_PATH, XDB_BYTES, XDB_SHA
                resource_files={name.removeprefix('components'):value for name,value in name_resources.items()}
                inode=fs.walk('/share/app/global.xdb')
                if not stat.S_ISREG(fs.inode(inode)[0]):raise ValueError('资源数据库必须是普通文件')
                raw=fs.read_inode(inode)
                check_component('global.xdb',raw,dict(bytes=XDB_BYTES,sha256=XDB_SHA))
                resource_files[XDB_PATH]=raw
                for inode,name,kind in fs.dir_entries(fs.walk('/share/app')):
                    if name.startswith('string_') and name.endswith('_f.uxc'):
                        if '/' in name or not stat.S_ISREG(fs.inode(inode)[0]):
                            raise ValueError('原厂名称分文件路径或类型不符')
                        resource_files['/usr/share/app/'+name]=fs.read_inode(inode)
                if module_raw is not None:
                    from .ui_hash_runtime import GCC_PATH, GCC_BYTES, GCC_SHA
                    inode=fs.walk(GCC_PATH)
                    if not stat.S_ISREG(fs.inode(inode)[0]):
                        raise ValueError('同包编译器辅助库必须是普通文件')
                    raw=fs.read_inode(inode)
                    check_component('libgcc_s',raw,dict(bytes=GCC_BYTES,sha256=GCC_SHA))
                    binaries['gcc']=raw
            del fs, ap_image
            raw = FatImage(archive.extractfile('0700_part_image/dev/nflasha8').read()).read('/cpapp-b.bin')
            checked['components/cpapp-b.bin'] = check_component('CP', raw, expected['components/cpapp-b.bin'])
            binaries['cp'] = raw
            for name, target in expected.items():
                if name.startswith('archive/'):
                    entry = originals[name.removeprefix('archive/')]
                    if (entry['size'], entry['sha256']) != (target['bytes'], target['sha256']):
                        raise ValueError('继承归档成员摘要不符：'+name)
                    checked[name] = dict(bytes=entry['size'], sha256=entry['sha256'])
            for name in originals:
                if name.endswith('.sum'):
                    raw = archive.extractfile(name).read()
                    if checksum_updates(name, raw, originals, current) != raw:
                        raise ValueError('归档校验清单变化：'+name)
    if set(checked) != set(expected):
        raise ValueError('目标组件集合不完整')
    if check_file(source['path'], DAT_IDENTITY) != source:
        raise ValueError('审计期间输入变化')
    report = dict(schema='a7r5-fixed-filter-audit/1', status='BASELINE_VERIFIED_NO_PATCH',
                  created_at=datetime.now(timezone.utc).isoformat(), source=source,
                  version='research-4.06', signature_verified=True, full_frame_validation=True,
                  **frames, tar_entries=len(entries), files=checked,
                  camera_io=False, sd_io=False, private_key_read=False,
                  input_modified=False, firmware_patch_generated=False,
                  device_acceptance_verified=False)
    if investigate:
        from .investigate import inspect_binaries
        from .access_evidence import collect
        from .native_paths import collect as collect_native_paths
        report['investigation'] = inspect_binaries(binaries['ap'], binaries['cp'])
        report['access_evidence'] = collect(binaries['ap'],binaries['cp'],binaries['backup'],binaries['manager'])
        report['native_paths'] = collect_native_paths(binaries['ap'],binaries['cp'],lut_directory_present)
        from .ap_cp_messages import collect as collect_messages
        report['ap_cp_messages'] = collect_messages(binaries['ap'],binaries['cp'],binaries['ipc'])
        from .cp_frame_stages import collect as collect_frame_stages
        report['cp_frame_stages'] = collect_frame_stages(binaries['cp'])
        from .cp_release import collect as collect_release
        report['cp_resource_release'] = collect_release(binaries['cp'])
        from .cp_reply import collect as collect_reply
        report['cp_reply'] = collect_reply(binaries['cp'])
        from .cp_display import collect as collect_display
        report['cp_evf_display_entry'] = collect_display(binaries['cp'])
        from .cp_message_pool import collect as collect_pool
        report['cp_native_message_pool'] = collect_pool(binaries['cp'])
        from .cp_notifications import collect as collect_notifications
        report['cp_native_notifications'] = collect_notifications(binaries['cp'])
        if grid_raw is not None:
            from .native_grid import collect as collect_grid
            report['native_lut_grid']=collect_grid(binaries['cp'],grid_raw)
        if joint_raw is not None:
            from .native_joint import collect as collect_joint
            report['native_joint_core']=collect_joint(binaries['cp'],joint_raw)
        if handshake_raw is not None:
            from .native_handshake import collect as collect_handshake
            report['native_hello_handshake'] = collect_handshake(binaries['ap'],binaries['cp'],binaries['ipc'],*handshake_raw)
        if atomic_raw is not None:
            from .cp_atomic import collect as collect_atomic
            report['cp_atomic_prepare'] = collect_atomic(binaries['cp'],atomic_raw)
        if cp_adapter_raw is not None:
            from .target_cp406 import collect as collect_cp_parameters
            report['target_cp406_parameters'] = collect_cp_parameters(binaries['ap'],binaries['cp'],cp_adapter_raw)
    if investigate_ui:
        if runtime_raw is not None:
            from .native_runtime import collect as collect_runtime
            report['native_task_runtime']=collect_runtime(binaries['ap'],binaries['cp'],binaries['ipc'],
                                                          binaries['std'],*runtime_raw)
        from .ap_request import collect as collect_request
        report['native_ap_request_lifetime'] = collect_request(binaries['ap'],binaries['cp'],binaries['ipc'],binaries['std'])
        from .ui_evidence import collect as collect_ui
        report['ui_evidence'] = collect_ui(binaries['ap'],binaries['std'])
        from .ui_cache import collect as collect_ui_cache
        report['ui_cache'] = collect_ui_cache(binaries['ap'],binaries['std'])
        from .ui_resources import append_name_fixture
        if len(name_resources)!=68:
            raise ValueError('界面研究缺少原68份锁定名称资源')
        report['ui_name_fixtures'] = {name:append_name_fixture(raw)[1]
                                     for name,raw in name_resources.items()}
        from .ui_resource_lookup import collect as collect_resource_lookup
        report['native_resource_lookup']=collect_resource_lookup(binaries['ap'],binaries['obj'],name_resources)
        from .ui_resource_loader import collect as collect_resource_loader
        report['native_resource_loader']=collect_resource_loader(binaries['ap'],binaries['obj'],resource_files)
        if adapter_raw is not None:
            from .target_ui import collect as collect_target_ui
            report['target_ui_adapter'] = collect_target_ui(binaries['ap'],adapter_raw)
        if module_raw is not None:
            from .ap_ui_hooks import collect as collect_ap_ui_hooks
            report['ap_ui_hooks'] = collect_ap_ui_hooks(binaries['ap'],binaries['std'],module_raw,binaries['gcc'])
    return report


def main():
    parser = argparse.ArgumentParser(description='核对固定4.06基线；不修改固件或访问相机')
    parser.add_argument('dat', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--investigate', action='store_true')
    parser.add_argument('--investigate-ui', action='store_true')
    parser.add_argument('--ui-adapter', type=Path, help='只在模拟器执行的独立AArch64测试ELF')
    parser.add_argument('--ap-ui-module', type=Path, help='只在匿名AP内存验证真实分支的AArch64研究ELF')
    parser.add_argument('--cp-parameter-adapter', type=Path, help='只在隔离CP中执行纯参数转换的ARMv7研究ELF')
    parser.add_argument('--cp-atomic-adapter', type=Path, help='只在隔离CP中联验有锁整组输入的ARMv7研究ELF')
    parser.add_argument('--ap-handshake-module', type=Path, help='仅匿名AP私有HELLO入口研究ELF，与CP模块成对')
    parser.add_argument('--cp-handshake-module', type=Path, help='仅匿名CP私有HELLO入口研究ELF，与AP模块成对')
    parser.add_argument('--ap-runtime-module', type=Path, help='仅匿名AP通信任务启动/时钟/接收研究ELF')
    parser.add_argument('--cp-runtime-module', type=Path, help='仅匿名CP通信任务一次启动研究ELF，与AP模块成对')
    parser.add_argument('--grid-adapter', type=Path, help='仅隔离执行的AArch64网格转换/量化/误差及原CP打包研究ELF')
    parser.add_argument('--joint-adapter', type=Path, help='仅隔离执行的联合整数搜索与原CP组件窗口研究ELF')
    args = parser.parse_args()
    output_path(args.report)
    report = audit(args.dat, investigate=args.investigate, investigate_ui=args.investigate_ui,
                   ui_adapter=args.ui_adapter, ap_ui_module=args.ap_ui_module,
                   cp_parameter_adapter=args.cp_parameter_adapter, cp_atomic_adapter=args.cp_atomic_adapter,
                   ap_handshake_module=args.ap_handshake_module, cp_handshake_module=args.cp_handshake_module,
                   ap_runtime_module=args.ap_runtime_module, cp_runtime_module=args.cp_runtime_module,
                   grid_adapter=args.grid_adapter,joint_adapter=args.joint_adapter)
    write_report(args.report, report)
    print(json.dumps(dict(status=report['status'], sha256=report['source']['sha256'],
                          files=len(report['files']), report=str(args.report)), ensure_ascii=False))


if __name__ == '__main__':
    main()
