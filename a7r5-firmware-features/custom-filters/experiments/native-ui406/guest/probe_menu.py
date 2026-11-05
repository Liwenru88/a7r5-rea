"""在独占输出目录运行新4.06客体；固定输入、真实原厂按键和帧。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[5]
LAB=ROOT/'a7r5-qemu'
DATA=ROOT/'.local/fixed-custom-filters/continuation28-menu/guest'
BASE=DATA
sys.path.insert(0,str(LAB/'tools'))
import app_paths
app_paths.paths=lambda:app_paths.AppPaths(LAB,DATA)
from native_vm import NativeVM
from menu_live import FirmwareMonitor,key_command
from menu_bridge import capture
from input_completion import wait_input_completion
from ram_mount import private_tmpfs,STORE_PATH

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def record_parser(manifest):
    # 只允许本文件相邻的新解析器；无字段的历史清单仍锁定旧冻结版本。
    legacy=ROOT/'.local/fixed-custom-filters/continuation29-exporter/parse_export.py'
    expected=Path(__file__).absolute().with_name('record_export.py')
    identity=manifest.get('record_parser')
    if identity is None:
        identity={'path':str(legacy),'sha256':'491b2ccc00742a796efc9164cc50d806e01e06908965b573f3b3ea36dec762a5'}
        expected=legacy
    if not isinstance(identity,dict) or set(identity)!={'path','sha256'} or identity['path']!=str(expected):
        raise ValueError('记录解析器不在固定允许路径')
    if expected.is_symlink() or expected.resolve()!=expected or not expected.is_file() or digest(expected)!=identity['sha256']:
        raise ValueError('严格记录解析器来源变化')
    spec=importlib.util.spec_from_file_location('ui406_live_record_export',expected)
    parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
    return parser,dict(identity)

class UiVM(NativeVM):
    def __init__(self,manifest):
        self.manifest=manifest.absolute();self.runtime_inputs()
        super().__init__('ui406',capid=True,boot_services=True)
    def runtime_inputs(self):
        if self.manifest!=DATA/'manifest.json':raise ValueError('实验清单路径越界')
        r=json.loads(self.manifest.read_text())
        record_parser(r)  # 必须在启动VM之前核验，STORE_EXPORT时再核一次。
        if (r['schema'],r['firmware'],r['AP_sha256'])!=('a7r5-ui406-guest/1','research-4.06',
            'd15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9'):raise ValueError('实验清单身份不符')
        allowed={'binary':LAB/'bin/qemu-system-aarch64','gpe':LAB/'sdk/lib/libgpe.so',
            'kernel':LAB/'build/aspect-guide406-20261026-01/source-02/vmlinux.bin',
            'initrd':DATA/'menu.cpio','dtb':DATA/'virt.dtb'}
        if set(r['files'])!=set(allowed):raise ValueError('输入不完整')
        for key,path in allowed.items():
            f=r['files'][key]
            if (f['path']!=str(path) or path.resolve()!=path.absolute() or not path.is_file() or path.is_symlink()
                or path.stat().st_size!=f['bytes'] or digest(path)!=f['sha256']):raise ValueError('固定输入不符：'+key)
        return allowed

def setup_commands():
    path=LAB/'experiments/aspect-guide406/probe_menu.py'
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location('ui406_readonly_setup_source',path)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    commands=old.setup_commands()
    # tmpfs遮住原/tmp/images；原样恢复同包中文字体，不改fontlist或字体选择。
    commands[-1:-1]=['if test -e /tmp/images/MYingHeiC-GB18030-SJ_wIcon.ltt; then echo UI406_FONT_BEFORE=present; else echo UI406_FONT_BEFORE=missing_after_tmpfs; fi',
        'mkdir -p /tmp/images',
        'cp /simulation/MYingHeiC-GB18030-SJ_wIcon.ltt /simulation/MYingHeiC-Big5-SJ_wIcon.ltt /simulation/Sony_DI_Icons.ttf /tmp/images/',
        'mkdir /tmp/a7r5-custom-filters-lab && mount -t tmpfs -o size=16m,mode=0700 tmpfs /tmp/a7r5-custom-filters-lab']
    restore=['if test -f /simulation/ui406-restore-STORE.ID; then mkdir -m 0700 /tmp/a7r5-custom-filters-lab/A7LOOKS1; fi']
    for name in ('STORE.ID','C07_A.rec','C07_B.rec','C20_A.rec','C20_B.rec'):
        restore.append('if test -f /simulation/ui406-restore-'+name+'; then cp /simulation/ui406-restore-'+name+' /tmp/a7r5-custom-filters-lab/A7LOOKS1/'+name+' && chmod 0600 /tmp/a7r5-custom-filters-lab/A7LOOKS1/'+name+'; fi')
    commands[-1:-1]=restore+['mkdir -m 0700 /tmp/a7r5-explicit-lut-library && cp /simulation/ui406-lut-*.cube /tmp/a7r5-explicit-lut-library/']
    return commands

def interactive(vm,frame,storage=False):
    actions=[];previous=frame;store_fill=False
    def reply(row):print('UI406_REPLY '+json.dumps(row,ensure_ascii=False),flush=True)
    reply({'action':'ready','run':str(vm.out),'frame':previous,'png':str(vm.out/'ui406-baseline-menu.png')})
    for line in sys.stdin:
        request=json.loads(line)
        if not isinstance(request,dict) or set(request)!={'action'}:raise ValueError('仅接受固定按键')
        action=request['action'];details={};FirmwareMonitor(vm.console).check()
        if action=='STOP':reply({'action':'STOP','stopping':True});return
        if action=='PRIVACY':
            vm.command('touch /tmp/a7r5-request-initial-privacy',timeout=30);vm.wait_native_screen(0x1e3)
            after=previous['sequence']
        elif action in ('UP','DOWN','LEFT','RIGHT','ENTER','MENU','C4','MODE_M','DISP'):
            offset=vm.console.stat().st_size;before=vm.last_native_screen()
            vm.command(key_command(action),timeout=30)
            if action=='MENU' and before==0x355:vm.wait_native_screen(0x2d6);after=previous['sequence']
            else:after=max(previous['sequence'],wait_input_completion(vm,action,offset))
        elif action=='STORE_FILL':
            # 仅在已验证的私有16MiB内存挂载填入15MiB；不删除或覆盖现有文件。
            if not storage or not DATA.name.startswith('candidate-overwrite30-') or store_fill:
                raise ValueError('RAM容量故障动作前提不符')
            before=vm.command('cat /proc/mounts',timeout=30);mount=private_tmpfs(before,'rw')
            mount_log=vm.out/('store-fill-%03d-mount.log'%len(actions));mount_log.write_bytes(before)
            path=STORE_PATH+'/UI406_RAM_FILL'
            command='test ! -e '+path+' && test ! -L '+path+' && dd if=/dev/zero of='+path+' bs=1024 count=15360 && ls -ln '+path
            filled=vm.command(command,timeout=30)
            fill_log=vm.out/('store-fill-%03d-write.log'%len(actions));fill_log.write_bytes(filled)
            names=(path.encode(),b'UI406_RAM_FILL')
            rows=[line.split() for line in filled.splitlines() if line.rstrip().endswith(names)]
            rows=[row for row in rows if len(row)>=9 and row[0].startswith(b'-') and row[4]==b'15728640' and row[-1] in names]
            if len(rows)!=1:
                raise RuntimeError('私有RAM填充大小未确认，停止且不回退')
            store_fill=True;details={'storage_fault_fixture':True,'kind':'capacity','bytes':15728640,
                'mount':mount,'logs':[str(mount_log),str(fill_log)]}
            after=previous['sequence']
        elif action=='STORE_EXPORT':
            # 只读固定五文件；任意命令/偏移/CRC/结束错误均不生成可恢复目录。
            raw=vm.command('/simulation/af-export-records; ui406_export_rc=$?; printf "AF_HELPER_RC=%d\\n" "$ui406_export_rc"; test "$ui406_export_rc" -eq 0',timeout=30)
            log=vm.out/('store-export-%03d.log'%len(actions));log.write_bytes(raw)
            if not re.search(rb'^AF_HELPER_RC=0\r?$',raw,re.M):raise ValueError('导出助手没有明确成功返回码')
            parser,parser_identity=record_parser(json.loads(vm.manifest.read_text()))
            files,report=parser.verify(raw.decode('utf-8',errors='strict'))
            export=vm.out/('store-export-%03d'%len(actions));export.mkdir(mode=0o700)
            for name,data in files.items():
                if data is not None:
                    with (export/name).open('xb') as output:output.write(data)
            result={'status':'PASS','source_log':str(log),'source_log_sha256':hashlib.sha256(raw).hexdigest(),
                    'files':report,'missing_records_reconstructed':False,'camera_io':False,'record_parser':parser_identity}
            (export/'records.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            details={'export_directory':str(export),'export_verified':True}
            after=previous['sequence']
        elif action=='SNAPSHOT':after=None
        elif action in ('CONFIG_COPY20','STORE_SNAPSHOT'):
            command='COPY20' if action=='CONFIG_COPY20' else 'SNAPSHOT'
            offset=vm.console.stat().st_size
            vm.command('touch /tmp/a7r5-ui406-manage-'+command,timeout=30)
            needle=('OBS A7R5_UI406_MANAGE_FIXTURE action='+command+' ').encode()
            deadline=time.monotonic()+30
            while needle not in vm.console.read_bytes()[offset:]:
                FirmwareMonitor(vm.console).check()
                if time.monotonic()>deadline:raise TimeoutError('原UI线程未确认管理观察请求')
                time.sleep(.1)
            after=previous['sequence']
        elif action in ('RESET_ARM','RESET_VERIFY_CANCEL','RESET_VERIFY_CONFIRM'):
            suffix,command={'RESET_ARM':('arm','A'),'RESET_VERIFY_CANCEL':('cancel','C'),'RESET_VERIFY_CONFIRM':('confirm','F')}[action]
            offset=vm.console.stat().st_size
            vm.command('touch /tmp/a7r5-ui406-reset-'+suffix,timeout=30)
            needle=('OBS A7R5_UI406_RESET_FIXTURE action='+command+' ').encode()
            deadline=time.monotonic()+30
            while needle not in vm.console.read_bytes()[offset:]:
                FirmwareMonitor(vm.console).check()
                if time.monotonic()>deadline:raise TimeoutError('原UI线程未确认重置快照校验')
                time.sleep(.1)
            _,settled=capture(vm,'ui406-%03d-%s-settle'%(len(actions),action),after=previous['sequence'])
            after=settled['sequence']
        elif action in ('NAME_EN','NAME_ZH','NAME_TOMBSTONE'):
            command={'NAME_EN':'E','NAME_ZH':'Z','NAME_TOMBSTONE':'T'}[action]
            offset=vm.console.stat().st_size
            vm.command('touch /tmp/a7r5-ui406-name-'+command,timeout=30)
            deadline=time.monotonic()+30
            needle=('OBS A7R5_UI406_NAME_FIXTURE action='+command+' ').encode()
            while needle not in vm.console.read_bytes()[offset:]:
                FirmwareMonitor(vm.console).check()
                if time.monotonic()>deadline:raise TimeoutError('原UI线程未确认名称夹具')
                time.sleep(.1)
            # 夹具在draw返回后串行发布；再等两个原帧，避免采集发布前的上一帧。
            _,settled=capture(vm,'ui406-%03d-%s-settle'%(len(actions),action),after=previous['sequence'])
            after=settled['sequence']
        else:raise ValueError('未知按键')
        name='ui406-%03d-%s'%(len(actions),action)
        _,previous=capture(vm,name,after=after)
        values=re.findall(rb'OBS A7R5_UI406_SELECTION ([^\r\n]+)',vm.console.read_bytes())
        row={'action':action,'frame':previous,'screen':vm.last_native_screen(),'png':str(vm.out/(name+'.png')),
             'selection':values[-1].decode() if values else None}
        row.update(details)
        actions.append(row);(vm.out/'ui-actions.json').write_text(json.dumps(actions,indent=2)+'\n');reply(row)
    raise RuntimeError('控制端提前关闭')

def main():
    global DATA
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--attach',action='store_true');parser.add_argument('--seed-c07',action='store_true')
    parser.add_argument('--names-fixture',action='store_true');parser.add_argument('--storage',action='store_true')
    parser.add_argument('--media',action='store_true');parser.add_argument('--chinese',action='store_true');args=parser.parse_args()
    if args.seed_c07 and not args.attach:raise ValueError('C07内存夹具需要显式实验接入')
    if args.names_fixture and not args.seed_c07:raise ValueError('名称文档夹具须显式C07实验目录')
    if args.storage and (not args.attach or args.seed_c07):raise ValueError('真实存储实验须接入且不能seed C07')
    if args.media and not args.storage:raise ValueError('本实验媒体服务必须复用已绑定存储DSO')
    if args.chinese and not args.attach:raise ValueError('语言模型夹具须同源模块已接入')
    chosen=args.manifest.absolute().parent
    if chosen!=BASE and (chosen.parent!=BASE or not chosen.name.startswith('candidate-')):raise ValueError('独占实验目录越界')
    DATA=chosen
    import vm_session
    vm_session.RUNS=DATA/'runs'
    vm=UiVM(args.manifest)
    result={'schema':'a7r5-ui406-guest-run/1','status':'FAIL','stage':'start','camera_io':False,
            'CP_imaging':False,'full_T06d':False,'attach_requested':args.attach,'C07_memory_fixture':args.seed_c07,
            'name_memory_document_fixture':args.names_fixture,'repository_service':args.storage,
            'explicit_RAM_media_fixture':args.media,'Chinese_startup_model_requested':args.chinese}
    error=None
    try:
        print('RUN_DIRECTORY '+str(vm.out),flush=True);vm.start();print('KERNEL_READY',flush=True)
        for i,command in enumerate(setup_commands()):
            if 'LD_PRELOAD=' in command:
                command='export A7R5_INITIAL_PRIVACY_NOTICE=1 A7R5_INPUT_COMPLETIONS=1; '+command
                if args.attach:command='export A7R5_UI406_ATTACH=1; '+command
                if args.seed_c07:command='export A7R5_UI406_SEED_C07=1; '+command
                if args.names_fixture:command='export A7R5_UI406_NAMES_FIXTURE=1; '+command
                if args.storage:command='export A7R5_UI406_STORAGE=1; '+command
                if args.media:command='export A7R5_UI406_MEDIA=1; '+command
                if args.chinese:command='export A7R5_UI406_CHINESE=1; '+command
            FirmwareMonitor(vm.console).check();reply=vm.command(command,timeout=45)
            (vm.out/f'setup-{i:02d}.log').write_bytes(reply);print('SETUP_COMPLETED '+str(i),flush=True)
        result['stage']='native-module-and-AP-init'
        if args.attach:
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                FirmwareMonitor(vm.console).check();raw=vm.console.read_bytes()
                if b'OBS A7R5_UI406_REJECTED ' in raw or b'OBS A7R5_UI406_CONFLICT ' in raw:raise RuntimeError('原进程接入拒绝，保留现场')
                if b'OBS A7R5_UI406_READY ' in raw:break
                if vm.process.poll() is not None:raise RuntimeError('客体提前退出')
                time.sleep(.2)
            else:raise TimeoutError('机内完整文件校验/绑定未在180秒内完成')
        vm.prime_native_menu();_,frame=capture(vm,'ui406-baseline-menu')
        result['stage']='interactive-original-menu';interactive(vm,frame,args.storage);result['status']='PASS'
    except BaseException as failure:
        error=failure;result['error']=repr(failure)
    finally:
        result['close']=vm.close();result['run_directory']=str(vm.out)
        result['Chinese_model_applied']=bool(re.search(rb'OBS A7R5_LOCALE28_MODEL [^\r\n]*model=25 ',vm.console.read_bytes()))
        (vm.out/'ui406-run.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2),flush=True)
    if error is not None or result['close'].get('exit_code')!=0:raise SystemExit(1)

if __name__=='__main__':main()
