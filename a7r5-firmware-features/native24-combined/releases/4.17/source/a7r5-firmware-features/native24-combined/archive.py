"""核对离线门禁并导出研究组件与证据；不签名、不生成DAT、不接设备。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def archive(build, cpu, xml, qemu, manifest, output, empty_qemu=None, empty_manifest=None):
    record = json.loads((build/'build.json').read_text())
    result = json.loads((cpu/'session-result.json').read_text())
    identity = (record['AP_sha256'], record['CP_sha256'])
    if record.get('stability_revision')!=1 or record.get('installable') or record.get('DAT_generated'):
        raise ValueError('只归档本轮不可安装研究组件')
    if result['status']!='PASS' or not result['full_related_suite'] or not result['sources_unchanged']:
        raise ValueError('缺少完整相关CPU回归')
    if (result['AP_sha256'],result['CP_sha256'])!=identity or result['build_receipt_sha256']!=sha(build/'build.json'):
        raise ValueError('CPU证据身份不符')
    tree = ET.parse(xml).getroot()
    cases = list(tree.iter('testcase'))
    if not cases or len(cases)!=len(result['tests']) or any(c.find(tag) is not None for c in cases for tag in ('failure','error','skipped')):
        raise ValueError('CPU原始XML未全通过')
    for name, digest in result['sources'].items():
        if sha(ROOT/name)!=digest:
            raise ValueError('测试后源文件漂移：'+name)
    ui = json.loads((qemu/'qt-research.json').read_text())
    menu = json.loads((qemu/'native410-menu.json').read_text())
    cp_close = json.loads((qemu/'cp/close.json').read_text())
    guest = json.loads(manifest.read_text())
    driver = json.loads((qemu/'validation-driver.json').read_text())
    if driver.get('exit_code')!=0 or driver.get('command',[])[-2:]!=['--manifest',str(manifest)]:
        raise ValueError('QEMU实际驱动与清单不匹配')
    expected_schema = 'native24-tabs-menu/1' if record.get('tabs_revision')==1 else 'native24-parameters-menu/1' if record.get('parameter_revision')==1 else 'native24-background-menu/1' if record.get('interaction_revision')==1 else 'native24-stable-menu/2'
    expected_size = 2444 if record.get('tabs_revision')==1 else 2404 if record.get('parameter_revision')==1 else 2328
    if (guest['AP_sha256'],guest['CP_sha256'])!=identity or guest.get('schema')!=expected_schema or guest.get('readonly_AP_state_bytes')!=expected_size:
        raise ValueError('QEMU清单身份不符')
    if record.get('tabs_revision')==1:
        tabs = json.loads((qemu/'tabs-validation.json').read_text())
        if tabs.get('status')!='PASS' or any(tabs.get(k) is not True for k in (
                'navigation_only_no_application','enter_confirmed_return','right_parameter_page','menu_reopen')):
            raise ValueError('缺少Tab导航、无应用、确认／调参或重入证据')
        if not empty_qemu or not empty_manifest:
            raise ValueError('Tab归档需要合法空库的独立QEMU证据')
        empty = json.loads((empty_qemu/'empty-validation.json').read_text())
        empty_guest = json.loads(empty_manifest.read_text())
        empty_driver = json.loads((empty_qemu/'validation-driver.json').read_text())
        empty_ui = json.loads((empty_qemu/'qt-research.json').read_text())
        empty_menu = json.loads((empty_qemu/'native410-menu.json').read_text())
        empty_cp = json.loads((empty_qemu/'cp/close.json').read_text())
        if (empty_guest.get('AP_sha256'),empty_guest.get('CP_sha256'))!=identity or empty_guest.get('recipe_set')!='empty' or empty_guest.get('readonly_AP_state_bytes')!=expected_size:
            raise ValueError('空组QEMU输入身份不符')
        if empty.get('status')!='PASS' or empty.get('no_application') is not True:
            raise ValueError('空组浏览缺少无应用证据')
        if any(value!=0 for value in (empty_driver.get('exit_code'),empty_ui.get('worker_exit_code'),empty_menu.get('close',{}).get('exit_code'),empty_cp.get('exit_code'))):
            raise ValueError('空组QEMU未正常完成')
        if empty_driver.get('command',[])[-2:]!=['--manifest',str(empty_manifest)] or empty_ui['operations'][-1]['action']!='STOP':
            raise ValueError('空组QEMU驱动或结束状态不符')
        for name, source in json.loads((empty_qemu/'validation-sources.json').read_text()).items():
            if hashlib.sha256(source['text'].encode()).hexdigest()!=source['sha256'] or sha(Path(name))!=source['sha256']:
                raise ValueError('空组验证源码漂移：'+name)
    if record.get('parameter_revision')==1:
        parameters = json.loads((qemu/'parameter-validation.json').read_text())
        if (parameters.get('status')!='PASS' or not parameters.get('reopen_preserved') or
                not parameters.get('reset_verified') or
                [s.get('parameter') for s in parameters.get('steps',[])]!=list(range(8))):
            raise ValueError('缺少实际八项编辑、重入或重置证据')
        previous = parameters['initial']
        for i, step in enumerate(parameters['steps']):
            changed = [p for p in range(8) if previous[p]!=step['values'][p]]
            if changed!=[i] or not (qemu/Path(step['png']).name).is_file():
                raise ValueError('八项工作值与对应原帧不符')
            previous = step['values']
        for name, source in json.loads((qemu/'validation-sources.json').read_text()).items():
            if hashlib.sha256(source['text'].encode()).hexdigest()!=source['sha256'] or sha(Path(name))!=source['sha256']:
                raise ValueError('QEMU验证源码漂移：'+name)
    if ui.get('worker_exit_code')!=0 or menu.get('close',{}).get('exit_code')!=0 or cp_close['exit_code']!=0 or menu.get('status')!='frame-collected':
        raise ValueError('QEMU未正常完成')
    if not ui['operations'] or ui['operations'][-1]['action']!='STOP':
        raise ValueError('Qt控制器未正常STOP')
    sys.path.insert(0,str(ROOT/'a7r5-qemu/tools'))
    from menu_live import snapshot_png
    frames = [p for p in qemu.glob('*.bin') if p.with_suffix('.png').is_file()]
    if not frames:
        raise ValueError('缺少客体原帧')
    for p in frames:
        if snapshot_png(p.read_bytes())!=p.with_suffix('.png').read_bytes():
            raise ValueError('原帧与PNG不一致：'+p.name)
    empty_frames=[]
    if empty_qemu:
        empty_frames=[p for p in empty_qemu.glob('*.bin') if p.with_suffix('.png').is_file()]
        if not empty_frames:raise ValueError('空组缺少客体原帧')
        for p in empty_frames:
            if snapshot_png(p.read_bytes())!=p.with_suffix('.png').read_bytes():
                raise ValueError('空组原帧与PNG不符：'+p.name)
    for name, expected in record['components'].items():
        if sha(build/name)!=expected['sha256'] or (build/name).stat().st_size!=expected['bytes']:
            raise ValueError('组件身份不符：'+name)
    output.mkdir(parents=True,exist_ok=False)
    for name in ('components','source','build','tests','qemu'):
        (output/name).mkdir()
    for name in record['components']:
        shutil.copyfile(build/name,output/'components'/name)
    for name in result['sources']:
        source = ROOT/name
        dest = output/'source'/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,dest)
    for p in (build/'work').rglob('*'):
        if p.is_file() and p.suffix in ('.c','.h','.S','.py','.json','.su') and 'inputs' not in p.relative_to(build/'work').parts:
            dest = output/'build'/p.relative_to(build)
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,dest)
    for p in build.glob('*.json'):
        shutil.copyfile(p,output/'build'/p.name)
    shutil.copytree(build/'unified',output/'build/unified')
    shutil.copytree(cpu,output/'tests/cpu')
    shutil.copyfile(xml,output/'tests/regression.xml')
    shutil.copyfile(manifest,output/'qemu/manifest.json')
    for p in qemu.rglob('*'):
        if p.is_file() and p.suffix in ('.json','.jsonl','.png','.bin','.raw'):
            dest = output/'qemu/run'/p.relative_to(qemu)
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,dest)
    if empty_qemu:
        (output/'qemu/empty').mkdir()
        shutil.copyfile(empty_manifest,output/'qemu/empty/manifest.json')
        for p in empty_qemu.rglob('*'):
            if p.is_file() and p.suffix in ('.json','.jsonl','.png','.bin','.raw'):
                dest=output/'qemu/empty/run'/p.relative_to(empty_qemu)
                dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    notice = HERE.parent/'native12-combined/upstream/THIRD_PARTY_NOTICES.md'
    if notice.exists():
        shutil.copyfile(notice,output/'THIRD_PARTY_NOTICES.md')
    summary = {'schema':'native24-stability-archive/1','status':'NOT_VERIFIED','offline_status':'PASS',
               'interaction_revision':record.get('interaction_revision',0),
               'parameter_revision':record.get('parameter_revision',0),
               'tabs_revision':record.get('tabs_revision',0),
               'AP_sha256':identity[0],'CP_sha256':identity[1],'CPU_tests':len(cases),'raw_png_frames':len(frames),
               'empty_raw_png_frames':len(empty_frames),
               'CP_heap_bytes':record['CP_heap_bytes'],'CP_code_bytes':record['CP_code_bytes'],
               'AP_BSS_bytes':record['AP_bss_bytes'],'stack_budget':record['stack_budget'],
               'installable':False,'DAT_generated':False,'camera_io':False,'QEMU_actual_filter_imaging_verified':False,
               'manual_gates':['真实共享堆及高水位','原E4完整初始化与LCD／EVF／JPEG','真实介质掉电／电源及安装恢复'],
               'source_build':str(build),'source_qemu_run':str(qemu)}
    save(output/'results.json',summary)
    (output/'README.md').write_text('# 二十四槽创意外观离线研究组件\n\n'
        '本归档包含成套AP、CP、两份图形资源、源码及离线证据。不可作为可安装升级包。\n\n'
        f'CPU相关回归{len(cases)}项通过，QEMU原帧与PNG核对{len(frames)}帧。'
        'QEMU未证明实际滤镜成像，真实堆、介质和机身验收仍待完成。\n\n'
        '13～24号只使用合成测试配方验证容量；不随组件包提供可安装滤镜配方。'
        'R5SEL6记录与旧固件不保证写出兼容，回退需配套处理。无私钥、无DAT。\n'
        + ('\n本候选新增原八项调参及按色彩SHA256保存的R5TUNE.BIN。当前BIN没有八项默认标量，'
           '新身份读取原厂ST默认字段建立初始值，不继承ST工作值或其他配方微调。'
           '最多保留128个身份，满时拒绝新身份，不自动淘汰。QEMU只证明工作模型与菜单操作，'
           'E4初始化缺口下仍为待应用，保存／回退由带明确外部边界的CPU回放验证。\n'
           if record.get('parameter_revision')==1 else ''))
    files = {str(p.relative_to(output)):sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    (output/'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name,digest in files.items()))
    bundle = output.with_suffix('.tar.gz')
    if bundle.exists():
        raise ValueError('研究归档已存在')
    with tarfile.open(bundle,'w:gz') as tar:
        tar.add(output,arcname=output.name)
    with tarfile.open(bundle,'r:gz') as tar:
        found = set()
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = str(Path(member.name).relative_to(output.name))
            stream = tar.extractfile(member)
            if name=='SHA256SUMS':
                if stream.read()!=(output/'SHA256SUMS').read_bytes():
                    raise ValueError('归档清单不一致')
            elif name not in files or hashlib.file_digest(stream,'sha256').hexdigest()!=files[name]:
                raise ValueError('归档内容不一致：'+name)
            else:
                found.add(name)
        if found!=files.keys():
            raise ValueError('归档成员集合不一致')
    print(json.dumps({'output':str(output),'bundle':str(bundle),'sha256':sha(bundle),'files':len(files),**summary},ensure_ascii=False))
    return summary


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('build','cpu','xml','qemu','manifest','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--empty-qemu',type=Path)
    parser.add_argument('--empty-manifest',type=Path)
    args = parser.parse_args()
    archive(*(getattr(args,name).resolve() for name in ('build','cpu','xml','qemu','manifest','output')),
            empty_qemu=args.empty_qemu.resolve() if args.empty_qemu else None,
            empty_manifest=args.empty_manifest.resolve() if args.empty_manifest else None)
