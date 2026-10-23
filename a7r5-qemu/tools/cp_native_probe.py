"""固定原厂 CP 矩阵窗口的真实 QEMU 验收；不是完整 CP/ISP 启动。"""
import argparse
from collections import Counter
import fcntl
import hashlib
import json
from pathlib import Path
import re
import socket
import struct
import subprocess
import tempfile
import time

from app_paths import open_vm_lock
from cp_boot_state import export_boot_state
from cp_transport_state import analyze as analyze_transport
from media_candidate import extract
from native_vm import NativeVM, sandbox_profile
from runtime_manifest import LAB, verified_inputs, verified_libraries, digest

CP_SHA = '3269bf62426339791fcfbe8529698cd4accbe6c3d2ea61cd7c368a90ab7ee7c8'
TOMCO_SHA = '524bb8c841f29e609e7606d56e6d393023afa8e0d3f61acbce7f957572323115'
BACKUP_SHA = '92697b50f6e3e25f5560a8c3eee357ea30b54e4e15cf29cd13bc30295759e3ce'
SLOTS = (0, 15, 16, 0xffffffff)
CALIBRATION = ((0, 0, 0), (256, 256, 256), (65535, 32768, 12345))


def prepare_tomco(raw, without_watchdog=False):
    """先固定原件身份；模拟变体只允许原厂支持的一个配置项变化。"""
    if len(raw) != 686 or hashlib.sha256(raw).hexdigest() != TOMCO_SHA:
        raise ValueError('原厂 TOMCO 身份不符')
    if without_watchdog:
        if raw.count(b'\nwdt_on=1\n') != 1:
            raise ValueError('TOMCO 看门狗配置身份不符')
        return raw.replace(b'\nwdt_on=1\n', b'\nwdt_on=0\n')
    return raw


def prepare_backup(raw):
    """仅加载清单已固定的模拟种子；让 CP 原厂 BK4 解析器自行建索引。"""
    if len(raw)!=2372469 or hashlib.sha256(raw).hexdigest()!=BACKUP_SHA:
        raise ValueError('固定模拟备份种子身份不符')
    offset=(sum(struct.unpack_from('<2I',raw,0x18))+0xfff)&~0xfff
    if raw[12:16]!=b'BK4\0' or raw[offset+12:offset+16]!=b'BK4\0':
        raise ValueError('固定备份双表布局不符')
    return raw


def reference(profile, slot, calibration):
    """独立展开测试系数；没有复制固件指令或调用其输出。"""
    bank = profile & 3 if profile <= 51 else 0
    slot = slot if slot <= 15 else 0
    values = []
    for group in range(3):
        a, b, c, d, e, f = (((bank*211+group*71+slot*17+k*31) & 1023)-512 for k in range(6))
        x, y, z = CALIBRATION[calibration]
        values.extend((x+a+b, -a, -b, -c, y+c+d, -d, -e, -f, z+e+f))
    return struct.pack('<27H', *(v & 65535 for v in values))+b'\xa5'*10


def verify_output(raw):
    lines = raw.replace(b'\r\n', b'\n').splitlines()
    begin = b'CP_NATIVE_MATRIX_BEGIN version=1 synthetic_parameters=1'
    end = b'CP_NATIVE_MATRIX_END cases=00000c18'
    # 允许启动设备的普通告警；矩阵记录必须完整、唯一、顺序正确。
    selected = [line for line in lines if line.startswith((b'CP_NATIVE_', b'CP_MATRIX'))]
    if not selected or selected[0] != begin or selected[-1] != end or len(selected) != 3098:
        raise ValueError('CP 原生窗口开始、结束或记录数量不完整')
    cursor = 1
    for profile in (*range(257), 0xffffffff):
        for slot in SLOTS:
            for calibration in range(3):
                match = re.fullmatch(rb'CP_MATRIX profile=([0-9a-f]{8}) slot=([0-9a-f]{8}) calibration=([0-2]) data=([0-9a-f]{128})', selected[cursor])
                if not match or tuple(int(v, 16) for v in match.groups()[:3]) != (profile, slot, calibration):
                    raise ValueError('CP 原生窗口输入顺序或身份不符')
                if bytes.fromhex(match[4].decode()) != reference(profile, slot, calibration):
                    raise ValueError(f'CP 矩阵算术不符：profile={profile} slot={slot} calibration={calibration}')
                cursor += 1
    return {'native_instruction_cases': 3096, 'independent_arithmetic_exact': True,
            'synthetic_parameters': True, 'CP_RTOS_booted': False, 'ISP_pixels_verified': False}


def build():
    inputs = verified_inputs()
    raw = extract(inputs['initrd'], ['cp/cpapp-b.bin'])['cp/cpapp-b.bin']
    if len(raw) != 17617008 or hashlib.sha256(raw).hexdigest() != CP_SHA:
        raise ValueError('CP 前像不符，拒绝执行未知程序')
    directory = Path(tempfile.mkdtemp(prefix='cp-native-', dir=LAB/'build'))
    (directory/'cpapp-b.bin').write_bytes(raw)
    layout = directory/'probe.ld'
    layout.write_text('ENTRY(_start)\nSECTIONS { . = 0; .vectors : { *(.vectors) } . = 0x10000; .text : { *(.startup) *(.text*) } .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) } /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) } }\n')
    command = ['/opt/homebrew/opt/llvm/bin/clang', '--target=armv7a-none-eabi', '-mcpu=cortex-a9',
               '-mthumb', '-mfloat-abi=soft', '-mno-unaligned-access', '-nostdlib', '-ffreestanding', '-fno-builtin',
               '-fno-stack-protector', '-O2', '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
               '-Wl,-T,'+str(layout), '-Wl,--build-id=none',
               str(LAB/'source/guest/cp-native-start.S'), str(LAB/'source/guest/cp-native-matrix.c'),
               '-o', str(directory/'probe.elf')]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
    (directory/'compiler.log').write_text(compiled.stdout+compiled.stderr)
    if compiled.returncode:
        raise RuntimeError('CP 试验入口构建失败：'+compiled.stderr[-1200:])
    record = {'CP_sha256': CP_SHA, 'base_initrd_sha256': digest(inputs['initrd']), 'command': command,
              'files': {p.name: {'bytes': p.stat().st_size, 'sha256': digest(p)}
                        for p in (directory/'cpapp-b.bin', directory/'probe.elf', layout)},
              'sources': {name: digest(LAB/'source/guest'/name)
                          for name in ('cp-native-start.S', 'cp-native-matrix.c')},
              'CP_modified': False, 'default_manifest_modified': False}
    (directory/'receipt.json').write_text(json.dumps(record, indent=2)+'\n')
    return directory


def qmp_command(vm, command):
    """仅连接本次实例的 Unix QMP；不提供客体命令或 TCP 接口。"""
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(5)
        vm.connect_qmp(sock)
        with sock.makefile('rwb') as stream:
            if 'QMP' not in json.loads(stream.readline()):
                raise RuntimeError('CP QMP 握手不符')
            for request in ({'execute':'qmp_capabilities'},command):
                stream.write(json.dumps(request).encode()+b'\n');stream.flush()
                while True:
                    reply=json.loads(stream.readline())
                    if 'error' in reply:raise RuntimeError(str(reply['error']))
                    if 'return' in reply:break
            return reply['return']


def research_binary(directory):
    directory=Path(directory).absolute()
    if directory.parent!=LAB/'build' or directory.is_symlink() or not directory.name.startswith('cp-qemu-'):
        raise ValueError('CP QEMU 目录越界')
    receipt=directory/'receipt.json'
    if receipt.is_symlink():raise ValueError('CP QEMU 收据包含软链接')
    record=json.loads(receipt.read_text())
    relative=Path(record['binary'])
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('CP QEMU 二进制路径越界')
    binary=directory/relative
    if (any(path.is_symlink() for path in (binary,*binary.parents) if path.is_relative_to(directory)) or
            binary.stat().st_size!=record['binary_bytes'] or digest(binary)!=record['binary_sha256'] or
            digest(LAB/'source/qemu/a7r5-cp-boot.c')!=record['board_sha256']):
        raise ValueError('CP QEMU 二进制或实验板源码身份不符')
    sources=record.get('model_sources',{})
    if set(sources)!={'a7r5-cp-edma.h'}:
        raise ValueError('CP DMA 模型源码收据不完整')
    for name,want in sources.items():
        path=LAB/'source/qemu'/name
        if path.is_symlink() or digest(path)!=want:
            raise ValueError('CP DMA 模型源码身份不符')
    return binary,record


def run(directory, *, boot_trace=False, cp_qemu=None, observe_ms=250, boot_detail=False, with_tomco=False,
        without_watchdog=False, with_backup=False):
    if type(observe_ms) is not int or not 50<=observe_ms<=2000:
        raise ValueError('CP 观察窗口必须为50至2000毫秒')
    if boot_detail and not boot_trace:
        raise ValueError('CP 全指令观察仅用于原入口启动')
    if with_tomco and not (boot_trace and cp_qemu is not None):
        raise ValueError('原厂 TOMCO 仅用于隔离四核原入口启动')
    if without_watchdog and not with_tomco:
        raise ValueError('关闭虚拟看门狗必须使用固定 TOMCO 候选')
    if with_backup and not (boot_trace and cp_qemu is not None and with_tomco):
        raise ValueError('备份种子仅用于带 TOMCO 的隔离 CP 原入口')
    directory = Path(directory).absolute()
    if directory.parent != LAB/'build' or directory.is_symlink():
        raise ValueError('CP 候选目录越界')
    record = json.loads((directory/'receipt.json').read_text())
    if record['CP_sha256'] != CP_SHA:
        raise ValueError('CP 候选身份不符')
    for name in ('cpapp-b.bin', 'probe.elf', 'probe.ld'):
        path = directory/name
        if path.is_symlink() or path.stat().st_size != record['files'][name]['bytes'] or digest(path) != record['files'][name]['sha256']:
            raise ValueError('CP 候选摘要不符')
    if digest(directory/'cpapp-b.bin') != CP_SHA:
        raise ValueError('CP 固定原件身份不符')
    inputs = verified_inputs()
    if digest(inputs['initrd']) != record['base_initrd_sha256']:
        raise ValueError('CP 候选基线已变化')
    result = {'status': 'failed', 'CP_sha256': CP_SHA, 'CP_modified': False,
              'CP_RTOS_booted': False, 'ISP_pixels_verified': False}
    binary=inputs['binary']
    if cp_qemu is not None:
        if not boot_trace:raise ValueError('独立 CP QEMU 仅用于启动观察')
        binary,binary_record=research_binary(cp_qemu)
        result['research_binary_sha256']=binary_record['binary_sha256']
        result['experimental_peripherals']=binary_record['peripherals_implemented']
    vm = NativeVM('cp-boot' if boot_trace else 'cp-matrix')
    print('CP_NATIVE_RUN', vm.out, flush=True)
    try:
        vm.lock = open_vm_lock()
        fcntl.flock(vm.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        vm.control = Path(tempfile.mkdtemp(prefix='a7r5-cp-', dir='/private/tmp'))
        if with_backup:
            backup=prepare_backup(extract(inputs['initrd'],['seed-backup.bin'])['seed-backup.bin'])
            (vm.out/'backup-seed.bin').write_bytes(backup)
            result['backup_seed']={'bytes':len(backup),'sha256':BACKUP_SHA,
                'load_address':0x04000000,'original_parser':0x534ef0,
                'source':'pinned simulator initrd seed-backup.bin; not current camera calibration',
                'CP_runtime_pointer_writes':False}
        if with_tomco:
            tomco = extract(inputs['initrd'], ['cp/tomco.txt'])['cp/tomco.txt']
            tomco = prepare_tomco(tomco)
            (vm.out/'tomco.txt').write_bytes(tomco)
            if without_watchdog:
                tomco = prepare_tomco(tomco, True)
                (vm.out/'tomco-simulation.txt').write_bytes(tomco)
            result['tomco'] = {'bytes': len(tomco), 'sha256': TOMCO_SHA, 'load_address': 0x100000,
                               'original_parser': 0x5e3740, 'modified': without_watchdog,
                               'loaded_sha256': hashlib.sha256(tomco).hexdigest(),
                               'changes': ['wdt_on=0 (virtual board only)'] if without_watchdog else []}
        profile = vm.out/'native.sb'
        profile.write_text(sandbox_profile(binary, directory/'cpapp-b.bin', directory/'probe.elf',
            directory/'probe.ld', vm.out, vm.control, libraries=verified_libraries()))
        command = ['/usr/bin/sandbox-exec', '-f', str(profile), str(binary),
            '-machine', 'versatilepb,audiodev=silent', '-cpu', 'cortex-a9', '-accel', 'tcg', '-m', '128M',
            '-nodefaults', '-display', 'none', '-monitor', 'none', '-serial', 'none', '-nic', 'none',
            '-no-reboot', '-audiodev', 'none,id=silent', '-semihosting-config', 'enable=on,target=native',
            '-qmp', f'unix:{vm.control}/qmp.sock,server=on,wait=off',
            '-d', 'in_asm', '-dfilter', '0x10000+0x1000,0x71e41e+0x126', '-D', str(vm.out/'instruction-trace.log'),
            '-device', f'loader,file={directory}/cpapp-b.bin,addr=0x108000,force-raw=on',
            '-device', f'loader,file={directory}/probe.elf,cpu-num=0']
        if boot_trace:
            # 原始入口不使用试验入口的宿主调用，保留固件自身 SVC 语义。
            index=command.index('-semihosting-config')
            del command[index:index+2]
            # 原始入口读取 ARMv8 的 CPUECTLR；A9 只能作普通指令窗口对照。
            command[command.index('-cpu')+1]='cortex-a35,aarch64=off,has_el2=off,has_el3=off'
            command[-1]='loader,addr=0x108000,cpu-num=0'
            command[command.index('-d')+1]='in_asm,int,guest_errors,unimp'
            command[command.index('-dfilter')+1]='0x108000+0x8000,0x128000+0x1000,0x150000+0x1000,0x340000+0x10000,0x5cc000+0x4000,0x5d6000+0x18000'
            if boot_detail:
                command[command.index('-dfilter')+1]='0x108000+0x1100000'
            command.extend(['-trace','enable=gic_dist_write'])
            command.append('-S')
            if cp_qemu is not None:
                # 让原厂次核推进同步计数；禁止改计数或跳过同步指令。
                command[command.index('-machine')+1]='a7r5-cp-boot'
                command[command.index('-serial')+1]='stdio'
                command.extend(['-smp','4'])
                for cpu in range(1,4):
                    command.extend(['-device',f'loader,addr=0x108000,cpu-num={cpu}'])
                if with_tomco:
                    tomco_name = 'tomco-simulation.txt' if without_watchdog else 'tomco.txt'
                    command.extend(['-device', f'loader,file={vm.out}/{tomco_name},addr=0x100000,force-raw=on'])
                if with_backup:
                    command.extend(['-device', f'loader,file={vm.out}/backup-seed.bin,addr=0x4000000,force-raw=on'])
        (vm.out/'native-command.json').write_text(json.dumps(command, indent=2)+'\n')
        vm.log = vm.console.open('wb')
        vm.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=vm.log, stderr=subprocess.STDOUT,
            env={'PATH': '/usr/bin:/bin', 'HOME': str(vm.control), 'TMPDIR': str(vm.control), 'LC_ALL': 'C'},
            start_new_session=True)
        (vm.out/'native-owner.json').write_text(json.dumps({'pid':vm.process.pid,'control':str(vm.control),
            'backend':'macos-native-cp-research','default_runtime_modified':False})+'\n')
        if boot_trace:
            deadline=time.monotonic()+5
            while not (vm.control/'qmp.sock').exists():
                if vm.process.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('CP 启动观察 QMP 未就绪')
                time.sleep(.02)
            qmp_command(vm,{'execute':'cont'})
            started=time.monotonic();deadline=started+observe_ms/1000;stop_reason='observation_window'
            while time.monotonic()<deadline:
                if vm.process.poll() is not None:raise RuntimeError('CP 启动观察提前退出')
                trace_path=vm.out/'instruction-trace.log'
                # 原厂异常处理器可能原指令重试；首个真实数据异常即停止，避免日志风暴。
                with trace_path.open('rb') as trace_stream:
                    trace_stream.seek(max(0,trace_path.stat().st_size-32768))
                    tail=trace_stream.read()
                if b'[Data Abort]' in tail:
                    stop_reason='data_abort';break
                if trace_path.stat().st_size>(16 if boot_detail else 1)*1024*1024:
                    stop_reason='trace_budget';break
                time.sleep(.01)
            qmp_command(vm,{'execute':'stop'})
            registers=qmp_command(vm,{'execute':'human-monitor-command','arguments':{'command-line':'info registers'}})
            (vm.out/'cp-boot-registers.txt').write_text(registers)
            memory=qmp_command(vm,{'execute':'human-monitor-command','arguments':{'command-line':'x /64wx 0x195df28'}})
            (vm.out/'cp-boot-lock-memory.txt').write_text(memory)
            cpus=qmp_command(vm,{'execute':'query-cpus-fast'})
            (vm.out/'cp-boot-cpus.json').write_text(json.dumps(cpus,indent=2)+'\n')
            state=qmp_command(vm,{'execute':'human-monitor-command','arguments':{'command-line':'x /16wx 0x157aa10'}})
            (vm.out/'cp-notify-state-memory.txt').write_text(state)
            export_boot_state(vm, qmp_command, 4 if cp_qemu is not None else 1)
            result.update(status='CP_boot_observed_not_accepted', observation_only=True,
                          requested_observation_ms=observe_ms,
                          full_instruction_trace=boot_detail,
                          actual_observation_ms=round((time.monotonic()-started)*1000),stop_reason=stop_reason,
                          instruction_trace_sha256=digest(vm.out/'instruction-trace.log'))
            trace=(vm.out/'instruction-trace.log').read_text(errors='replace')
            transport = analyze_transport((directory/'cpapp-b.bin').read_bytes(),
                                          (vm.out/'cp-runtime-01500000.bin').read_bytes(), trace)
            (vm.out/'cp-transport-state.json').write_text(json.dumps(transport, ensure_ascii=False, indent=2)+'\n')
            result['transport_blockers'] = transport['transmission_blockers']
            aborts=Counter(re.findall(r'with DFSR (0x[0-9a-f]+) DFAR (0x[0-9a-f]+)',trace))
            result['data_abort_count']=sum(aborts.values())
            result['data_abort_records']=[{'DFSR':status,'DFAR':address,'count':count}
                                           for (status,address),count in aborts.items()]
            result['IRQ_entries']=len(re.findall(r'Taking exception 5 \[IRQ\]',trace))
            return result
        deadline=time.monotonic()+20
        while vm.process.poll() is None:
            if vm.console.stat().st_size>1024*1024:
                raise RuntimeError('CP 指令探针输出超限，停止本次实例')
            if time.monotonic()>deadline:
                raise TimeoutError('CP 指令探针 20 秒内未完成')
            time.sleep(.02)
        if vm.process.returncode:
            raise RuntimeError('CP QEMU 执行失败：'+vm.console.read_text(errors='replace')[-1600:])
        result.update(verify_output(vm.console.read_bytes()), status='native_CP_matrix_window_verified')
        result['completion']='semihosting_exit'
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        result['exit'] = vm.close()
        result['console_sha256'] = digest(vm.console)
        result['candidate'] = str(directory)
        (vm.out/'cp-result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--boot-trace', action='store_true', help='从原 CP 入口有界运行，默认250ms、最多2000ms，不宣称启动成功')
    parser.add_argument('--cp-qemu',type=Path,help='新建的四核 CP 实验板构建目录；不替换默认模拟器')
    parser.add_argument('--observe-ms',type=int,default=250,help='启动观察窗口，50至2000毫秒；不是完成判据')
    parser.add_argument('--boot-detail',action='store_true',help='原入口完整指令范围，16 MiB 有界日志；不改变客体执行')
    parser.add_argument('--with-tomco',action='store_true',help='将固定归档的原厂 TOMCO 加载到原厂解析器读取地址；不修改配置内容')
    parser.add_argument('--without-watchdog',action='store_true',help='显式模拟配置：仅将 TOMCO 的 wdt_on=1 改为0；保留原件，不宣称看门狗已实现')
    parser.add_argument('--with-backup',action='store_true',help='加载固定模拟归档的备份种子供原厂 CP 解析，不改索引指针')
    args = parser.parse_args()
    if args.cp_qemu and not args.boot_trace:parser.error('--cp-qemu requires --boot-trace')
    directory = args.candidate or build()
    print('CP_NATIVE_CANDIDATE', directory, flush=True)
    if not args.build_only:
        print(json.dumps(run(directory,boot_trace=args.boot_trace,cp_qemu=args.cp_qemu,observe_ms=args.observe_ms,boot_detail=args.boot_detail,with_tomco=args.with_tomco,without_watchdog=args.without_watchdog,with_backup=args.with_backup), indent=2))


if __name__ == '__main__':
    main()
