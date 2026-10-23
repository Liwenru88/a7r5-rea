"""在独立 QEMU 中执行 AP 选择器、CP 矩阵/色表/Gamma 窗口；不启动完整固件。"""
import fcntl
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time

from app_paths import open_vm_lock
from look_materials import load, sha
from native_vm import NativeVM, sandbox_profile
from runtime_manifest import LAB, digest, verified_inputs, verified_libraries
from cp_native_probe import qmp_command


def build(which, out, *, live=False, matrix_check=False,joint_check=False):
    guest=LAB/'source/guest'
    names=['look-reference-ap.S','look-reference-ap.c'] if which=='ap' else ['cp-native-start.S','look-reference-cp.c']
    if live:names[-1]='look-live-'+which+'.c'
    if matrix_check:names[-1]='look-inline-matrix-check.c'
    if joint_check:names[-1]='look-joint-check.c'
    layout=out/'probe.ld';elf=out/'probe.elf'
    address='0x40100000' if which=='ap' else '0x03030000'
    layout.write_text('ENTRY(_start)\nSECTIONS { . = '+address+'; .text : { *(.vectors) *(.startup) *(.text*) } .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) } /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) } }\n')
    args=['/opt/homebrew/opt/llvm/bin/clang', '--target='+('aarch64-none-elf' if which=='ap' else 'armv7a-none-eabi'),
        '-mcpu=cortex-a35','-nostdlib','-ffreestanding','-fno-builtin','-fno-stack-protector','-O2',
        '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-Wl,-T,'+str(layout),'-Wl,--build-id=none']
    if which=='cp':args+=['-mthumb','-mfloat-abi=soft']
    else:args+=['-mgeneral-regs-only','-mstrict-align']
    if matrix_check:args+=['-mno-unaligned-access']
    args +=[str(guest/n) for n in names]+['-o',str(elf)]
    result=subprocess.run(args,capture_output=True,text=True,timeout=30)
    (out/'compiler.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('指令窗口构建失败，见 compiler.log')
    (out/'build.json').write_text(json.dumps({'command':args,'ELF_sha256':digest(elf),
        'sources':{n:digest(guest/n) for n in dict.fromkeys(names+(['look-reference-'+which+'.c'] if live or matrix_check else [])+(['look-live-cp.c'] if joint_check else []))}},indent=2)+'\n')
    return elf,layout


def execute(which, folder, *, request=None, matrix_check=False,joint_check=False):
    if matrix_check and (which!='cp' or request is None):raise ValueError('矩阵核对仅支持显式 CP 请求')
    files,material_record=load(folder);inputs=verified_inputs()
    if joint_check and (which!='cp' or material_record['schema']!=7 or request!=[0] or matrix_check):
        raise ValueError('联合参数检查只接受固定CP候选和固定请求')
    if matrix_check and (len(request)!=1 or type(request[0]) is not int or not 0<=request[0]<=3):
        raise ValueError('矩阵核对模式不符')
    if matrix_check and request[0]==3 and material_record['schema'] not in (5,6):
        raise ValueError('完整性负例仅用于已固定的等长候选')
    boot_copy_fixture=which=='cp' and material_record['schema'] in (5,6,7)
    if boot_copy_fixture:
        if request is None or len(request)>4:raise ValueError('等长候选需要明确的逐次参数入口')
        request=list(request)+[0]*(4-len(request))+[1]
    build_dir=Path(tempfile.mkdtemp(prefix='look-native-'+which+'-',dir=LAB/'build'))
    live=request is not None
    elf,layout=build(which,build_dir,live=live,matrix_check=matrix_check,joint_check=joint_check)
    vm=NativeVM('look-'+which)
    receipt={'scope':'isolated original/patched instruction windows; no full AP/CP/ISP',
             'default_runtime_modified':False,'camera_io':False,'AP_CP_connected':False,
             'binary_sha256':digest(inputs['binary']),'CP_sha256':sha(files['cpapp-b.bin'])}
    if live:receipt['request']=request;receipt['live_selection']=True
    receipt['joint_parameters']=material_record['schema']==7
    receipt['joint_stage_check']=joint_check
    if matrix_check:receipt['matrix_equivalence_check']=True;receipt['live_selection']=False
    receipt['boot_copy_fixture_requested']=boot_copy_fixture
    receipt['original_bootstrap_executed']=False
    try:
        vm.lock=open_vm_lock();fcntl.flock(vm.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        vm.control=Path(tempfile.mkdtemp(prefix='a7r5-look-',dir='/private/tmp'))
        profile=vm.out/'native.sb'
        profile.write_text(sandbox_profile(inputs['binary'],Path(folder)/'cpapp-b.bin',elf,layout,
            vm.out,vm.control,libraries=verified_libraries()))
        args=['/usr/bin/sandbox-exec','-f',str(profile),str(inputs['binary']),
            '-accel','tcg','-nodefaults','-display','none','-monitor','none','-serial','none',
            '-nic','none','-no-reboot','-semihosting-config','enable=on,target=native',
            '-qmp',f'unix:{vm.control}/qmp.sock,server=on,wait=off']
        if which=='ap':
            args+=['-machine','virt,secure=off','-cpu','cortex-a35','-m','256M']
            loaders=[('ap-selector.bin',0x43550354),('ap-map.bin',0x44b724d0)]
        else:
            args+=['-machine','versatilepb,audiodev=silent','-cpu','cortex-a15','-m','128M',
                   '-audiodev','none,id=silent','-device',f'loader,file={folder}/cpapp-b.bin,addr=0x108000,force-raw=on']
            loaders=[('matrix-before.bin',0x04000000),('matrix-fixed.bin',0x04010000)]
            if live:loaders.append(('style-property.bin',0x04020000))
        for name,address in loaders:
            path=vm.out/name;path.write_bytes(files[name])
            args+=['-device',f'loader,file={path},addr={address:#x},force-raw=on']
        if live:
            path=vm.out/'request.bin';path.write_bytes(struct.pack('<'+str(len(request))+'I',*request))
            address=0x40300000 if which=='ap' else 0x04100000
            args+=['-device',f'loader,file={path},addr={address:#x},force-raw=on']
        args+=['-device',f'loader,file={elf},cpu-num=0']
        (vm.out/'instruction-errors.log').touch()
        args+=['-d','int,guest_errors'+(',in_asm' if matrix_check else ''),'-D',str(vm.out/'instruction-errors.log')]
        if matrix_check:args+=['-dfilter','0x71e41e+0x126,0xbef6b0+0x50,0xbef3b4+0x18,0x108f40+0xc0']
        (vm.out/'native-command.json').write_text(json.dumps(args,indent=2)+'\n')
        vm.log=vm.console.open('wb')
        vm.process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=vm.log,stderr=subprocess.STDOUT,
            env={'PATH':'/usr/bin:/bin','HOME':str(vm.control),'TMPDIR':str(vm.control),'LC_ALL':'C'},start_new_session=True)
        (vm.out/'native-owner.json').write_text(json.dumps({'pid':vm.process.pid,'control':str(vm.control)})+'\n')
        deadline=time.monotonic()+20
        while vm.process.poll() is None:
            if (time.monotonic()>deadline or vm.console.stat().st_size>1024*1024 or
                    (vm.out/'instruction-errors.log').stat().st_size>1024*1024):
                qmp_command(vm,{'execute':'stop'})
                registers=qmp_command(vm,{'execute':'human-monitor-command','arguments':{'command-line':'info registers'}})
                (vm.out/'failure-registers.txt').write_text(registers)
                if matrix_check:
                    qmp_command(vm,{'execute':'pmemsave','arguments':{'val':0x1a3a000,'size':2304,
                        'filename':str(vm.out/'matrix-at-failure.bin')}})
                raise RuntimeError('指令窗口超时或输出超限；保留失败现场')
            time.sleep(.02)
        if vm.process.returncode:raise RuntimeError('QEMU 指令窗口退出失败：'+vm.console.read_text(errors='replace')[-1500:])
        receipt.update(status='instruction_window_finished',completion='semihosting_exit',
                       console_sha256=digest(vm.console),probe=str(build_dir))
    except Exception as error:
        receipt.update(status='failed',error=str(error));raise
    finally:
        receipt['exit']=vm.close()
        (vm.out/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return vm.out


def parse_ap(raw):
    lines=raw.decode('ascii').splitlines()
    if lines[0]!='LOOK_AP_BEGIN' or lines[-1]!='LOOK_AP_END' or len(lines)!=206:
        raise ValueError('AP 指令窗口输出不完整')
    rows={}
    expected_map=(0,3,2,1,16,15,17,18,5,13,19,20)
    for index,line in enumerate(lines[1:-1]):
        m=re.fullmatch(r'A ([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]{8})',line)
        if not m:raise ValueError('AP 记录格式不符')
        selector,base,marker=map(lambda v:int(v,16),m.groups())
        if (selector,base)!=divmod(index,12):raise ValueError('AP 序列重复或错位')
        expected=255 if selector==16 else 249+selector-10 if base==0 and 10<=selector<=15 else expected_map[base]
        if marker!=expected:raise ValueError('AP 原生标记映射不符')
        rows[f'{selector}:{base}']=marker
    return rows


def expected_bank(cp,table,level):
    order=struct.unpack_from('<405H',cp,0xd841d8)
    if sorted(order)!=list(range(405)) or len(table)!=1215 or not 1<=level<=8:
        raise ValueError('色表打包输入不符')
    values=struct.unpack('1215b',table)
    if any(not -64<=v<=63 for v in values):raise ValueError('色表有符号七位越界')
    output=bytearray(1620)
    for i in range(405):
        a,b,c=(values[i+j*405]*level>>3 for j in range(3))
        struct.pack_into('<I',output,order[i]*4,((a&127)<<22)|((b&127)<<12)|((c&127)<<2))
    return bytes(output)


def parse_cp(raw, files):
    lines=raw.decode('ascii').splitlines()
    if lines[0]!='LOOK_CP_BEGIN' or lines[-1]!='LOOK_CP_END':raise ValueError('CP 指令窗口未完整返回')
    rows={}
    for line in lines[1:-1]:
        m=re.fullmatch(r'([SLMGI]) ([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]+)',line)
        if not m:raise ValueError('CP 记录格式不符')
        tag,a,b,value=m.groups();key=f'{tag}:{int(a,16)}:{int(b,16)}'
        if key in rows:raise ValueError('CP 记录重复')
        rows[key]=bytes.fromhex(value)
    expected=set()
    cp=files['cpapp-b.bin']
    for marker in range(249,255):
        for flag in range(2):
            key=f'S:{marker}:{flag}';expected.add(key);value=rows.get(key,b'')
            pointer=0x108000+0x108d080+576+32+(marker-249)*1215
            if len(value)!=8 or struct.unpack_from('<I',value)[0]!=pointer or value[4:6]!=b'\x01\x02':
                raise ValueError('CP 未选中正确的自定义色表')
            for level in range(1,9):
                key=f'L:{marker}:{flag*8+level}';expected.add(key)
                if rows.get(key)!=expected_bank(cp,files[f'slot{marker-248}.raw-s8.bin'],level):
                    raise ValueError('原厂打包结果与独立格式模型不符')
    for fixed in range(2):
        prop=files['matrix-fixed.bin' if fixed else 'matrix-before.bin']
        for profile in (0,54,55,56,57):
            bank=prop[0x196+profile]
            for slot in range(16):
                key=f'M:{profile}:{fixed*16+slot}';expected.add(key);values=[]
                for group in range(3):
                    a,b,c,d,e,f=struct.unpack_from('<6H',prop,0x1e0+bank*768+group*192+slot*12)
                    values +=[256+a+b,-a,-b,-c,256+c+d,-d,-e,-f,256+e+f]
                if rows.get(key)!=struct.pack('<27H',*(v&65535 for v in values)):
                    raise ValueError('原厂矩阵结果与独立供体算术不符')
    for route in range(2):
        for movie in range(2):
            context=route*2+movie
            for color in (*range(22),*range(249,255)):
                key=f'G:{color}:{context}';incoming=f'I:{color}:{context}'
                expected.update((key,incoming));source=bytearray(96)
                struct.pack_into('<I',source,0x10,color);source[8]=movie;source[0xb]=1
                if route:source[0]=1;struct.pack_into('<I',source,4,color)
                if rows.get(incoming)!=bytes(source):raise ValueError('Gamma 路径改写了输入参数')
                if color>=249 and rows.get(key)!=rows.get(f'G:0:{context}'):
                    raise ValueError('自定义色表没有沿用 ST Gamma 参数')
                if len(rows.get(key,b''))!=96:raise ValueError('Gamma 参数输出长度不符')
    if set(rows)!=expected:raise ValueError('CP 输出项缺失或有额外记录')
    if len({rows[f'M:{p}:0'] for p in range(54,58)})!=1:raise ValueError('基线共用矩阵问题未复现')
    if len({rows[f'M:{p}:16'] for p in range(54,58)})!=4:raise ValueError('修复后矩阵仍有别名')
    return {k:v.hex() for k,v in rows.items()}


def capture(folder):
    files,_=load(folder)
    ap=execute('ap',folder);cp=execute('cp',folder)
    result={'schema':1,'materials':str(Path(folder).absolute()),'AP_run':str(ap),'CP_run':str(cp),
        'AP_mapping':parse_ap((ap/'console.log').read_bytes()),
        'CP_records':parse_cp((cp/'console.log').read_bytes(),files),
        'native_instruction_windows_verified':True,'full_AP_CP_transport_verified':False,
        'ISP_pixels_verified':False,'synthetic_context':True,
        'boundary':'real instruction windows with explicit fixtures; no RTOS, UIPC or physical ISP',
        'material_files':{k:sha(v) for k,v in files.items()}}
    path=cp/'look-parameters.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return path
